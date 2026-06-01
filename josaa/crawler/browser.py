"""Thin Playwright wrapper for the JoSAA ASP.NET WebForms pages.

The pages use the jQuery "Chosen" plugin, which hides the real <select>
(display:none) behind a custom widget — so we drive the native <select> by its
stable control id with force=True (bypasses the visibility check; the dispatched
`change` event still fires the element's `__doPostBack`). Every selection is a
full postback, so we wait for network idle and re-read option lists afterwards.
"""
from __future__ import annotations

import time

from playwright.sync_api import Error as PWError, Page, TimeoutError as PWTimeout, sync_playwright

from ..config import settings
from ..logging_conf import get_logger

log = get_logger(__name__)


class Crawler:
    def __init__(self, headless: bool | None = None):
        self.headless = settings.headless if headless is None else headless
        self._pw = None
        self._browser = None
        self.page: Page | None = None

    def __enter__(self) -> "Crawler":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        ctx = self._browser.new_context()
        ctx.set_default_timeout(45_000)
        self.page = ctx.new_page()
        return self

    def __exit__(self, *exc):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def goto(self, url: str) -> None:
        log.debug("navigate -> %s", url)
        self.page.goto(url, wait_until="networkidle")

    def wait_postback(self) -> None:
        self.page.wait_for_timeout(400)
        try:
            self.page.wait_for_load_state("networkidle")
        except PWTimeout:
            pass
        time.sleep(settings.request_delay_seconds)

    # ---- chosen-hidden <select> driven by id --------------------------
    def options(self, sid: str) -> list[str]:
        # Resilient to an in-flight postback navigation (esp. the seat-matrix page,
        # which chains postbacks): wait for the <select>, retry if the execution
        # context is destroyed mid-read.
        for _ in range(4):
            try:
                self.page.wait_for_selector(f"#{sid}", state="attached", timeout=20_000)
                el = self.page.query_selector(f"#{sid}")
                if not el:
                    return []
                return el.eval_on_selector_all(
                    "option", "els => els.map(e => e.textContent.trim())")
            except PWError as e:
                if "context was destroyed" in str(e) or "navigation" in str(e):
                    try:
                        self.page.wait_for_load_state("networkidle")
                    except PWTimeout:
                        pass
                    continue
                raise
        return []

    def has_option(self, sid: str, label: str) -> bool:
        return any(o == label for o in self.options(sid))

    def select(self, sid: str, label: str) -> bool:
        """Select an option by exact label; returns False if it isn't present."""
        if not self.has_option(sid, label):
            return False
        self.page.select_option(f"#{sid}", label=label, force=True)
        self.wait_postback()
        return True

    def submit(self) -> bool:
        btn = self.page.query_selector("input[type=submit][value*='Submit']")
        if not btn:
            return False
        btn.click(force=True)
        self.wait_postback()
        return True

    def content(self) -> str:
        return self.page.content()
