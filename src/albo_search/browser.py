"""Optional browser transport (playwright).

Iscrivo (JSF/PrimeFaces), CNDCEC (Kendo UI) and the Ministry of Interior
registry are JavaScript-heavy and are queried through a headless browser.
Playwright is an optional extra: import here fails lazily, never at
package import time.
"""

from __future__ import annotations

import glob
import os
import time
from typing import Iterator

from .errors import TransportMissing


def _chromium_executable() -> str | None:
    patterns = (
        os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"),
        os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux/chrome"),
        os.path.expanduser("~/Library/Caches/ms-playwright/chromium-*/chrome-mac/Google Chrome"),
    )
    for pattern in patterns:
        hits = sorted(glob.glob(pattern), reverse=True)
        if hits:
            return hits[0]
    return None


def playwright():
    """Return a configured sync_playwright context manager.

    Raises TransportMissing with an actionable message when the optional
    dependency or a chromium binary is unavailable.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise TransportMissing(
            "this source needs a real browser: install the optional extra "
            "with 'pip install -e \".[browser]\"' (playwright + chromium)"
        ) from exc
    return sync_playwright()


def new_page(p, locale: str = "it-IT", timeout_ms: int = 30000):
    """Launch chromium headless and open a page with sensible defaults."""
    executable = _chromium_executable()
    try:
        browser = p.chromium.launch(
            headless=True, args=["--no-sandbox"],
            executable_path=executable,
        )
    except Exception as exc:  # chromium missing or broken
        raise TransportMissing(
            "chromium binary not found: run 'python -m playwright install chromium'"
        ) from exc
    ctx = browser.new_context(
        locale=locale,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
    )
    page = ctx.new_page()
    page.set_default_timeout(timeout_ms)
    return browser, page


def settle(page, seconds: float = 2.5) -> None:
    """Brief, conservative pause so JS-rendered content settles."""
    time.sleep(seconds)
