"""
Общий headless Chromium для Playwright-парсеров.

Раньше каждый из 10 парсеров запускал свой Chromium: несколько секунд на
старт и сотни МБ памяти на каждый. Теперь браузер один на весь обход
(`shared_browser()` в scheduler/jobs.py), а каждый парсер получает свою
вкладку в отдельном контексте — куки и локаль не пересекаются. После обхода
браузер закрывается, чтобы в простое не держать память на сервере (1 ГБ).
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Browser, Locator, Page, Playwright, Route, async_playwright

_LAUNCH_ARGS = ["--disable-dev-shm-usage", "--disable-gpu", "--disable-extensions"]

# Для расписания нужен только текст: картинки, шрифты и видео — лишняя загрузка.
_BLOCKED_TYPES = {"image", "media", "font"}
# Счётчики и пиксели не влияют на содержимое, но держат сеть и CPU занятыми.
_BLOCKED_HOSTS = (
    "mc.yandex.", "google-analytics.com", "googletagmanager.com",
    "connect.facebook.net", "vk.com/rtrg", "top-fwz1.mail.ru",
)

_playwright: Playwright | None = None
_browser: Browser | None = None


async def _launch(p: Playwright) -> Browser:
    return await p.chromium.launch(headless=True, args=_LAUNCH_ARGS)


@asynccontextmanager
async def shared_browser() -> AsyncIterator[None]:
    global _playwright, _browser
    async with async_playwright() as p:
        _playwright = p
        try:
            yield
        finally:
            if _browser is not None:
                try:
                    await _browser.close()
                except Exception:
                    pass
            _browser, _playwright = None, None


async def _block_noise(route: Route) -> None:
    request = route.request
    if request.resource_type in _BLOCKED_TYPES or any(h in request.url for h in _BLOCKED_HOSTS):
        await route.abort()
    else:
        await route.continue_()


@asynccontextmanager
async def _page_in(
    browser: Browser, locale: str | None, cookies: list[dict] | None, block_noise: bool
) -> AsyncIterator[Page]:
    # Часовой пояс Астаны: JS-сайты могут показывать время в поясе посетителя,
    # а в GitHub Actions машина работает по UTC — время игр сдвинулось бы на 5 часов.
    context = await browser.new_context(locale=locale, timezone_id="Asia/Almaty")
    try:
        if cookies:
            await context.add_cookies(cookies)
        if block_noise:
            await context.route("**/*", _block_noise)
        yield await context.new_page()
    finally:
        await context.close()


@asynccontextmanager
async def open_page(
    *, locale: str | None = None, cookies: list[dict] | None = None, block_noise: bool = True
) -> AsyncIterator[Page]:
    """
    Вкладка в общем браузере, если идёт обход через shared_browser(), иначе —
    в собственном (удобно для запуска одного парсера отдельно, при отладке).
    Если общий браузер умер посреди обхода (например, нехватка памяти),
    поднимаем новый, чтобы не потерять остальные источники.

    block_noise=False — грузить страницу целиком, как обычный браузер: на
    сайтах за защитой Cloudflare её проверочный скрипт должен отработать.
    """
    global _browser
    if _playwright is None:
        async with async_playwright() as p:
            browser = await _launch(p)
            try:
                async with _page_in(browser, locale, cookies, block_noise) as page:
                    yield page
            finally:
                await browser.close()
        return

    if _browser is None or not _browser.is_connected():
        _browser = await _launch(_playwright)
    async with _page_in(_browser, locale, cookies, block_noise) as page:
        yield page


async def goto(page: Page, url: str) -> None:
    # Не "networkidle": некоторые сайты (Смузи) никогда не затихают из-за
    # фоновых запросов, и goto падал по таймауту. Готовность страницы
    # определяем по появлению нужных элементов — см. wait_for_items().
    await page.goto(url, wait_until="domcontentloaded")


async def wait_for_items(
    locator: Locator, *, timeout: int = 15_000, settle_s: float = 1.0, max_wait_s: float = 8.0
) -> int:
    """
    Ждёт первый элемент, затем — пока их количество не перестанет меняться
    `settle_s` секунд (сайты на Tilda и Nuxt догружают карточки частями;
    networkidle раньше гарантировал полную загрузку, теперь это делаем мы).
    Возвращает итоговое количество.
    """
    await locator.first.wait_for(state="attached", timeout=timeout)
    count = await locator.count()
    changed_at = time.monotonic()
    deadline = changed_at + max_wait_s
    while time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        current = await locator.count()
        if current != count:
            count, changed_at = current, time.monotonic()
        elif time.monotonic() - changed_at >= settle_s:
            break
    return count
