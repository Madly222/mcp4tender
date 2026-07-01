from __future__ import annotations

import logging

log = logging.getLogger("tenderengine.render")


def render_available():
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def get_text_rendered(url, timeout=30, headers=None, wait_ms=2500):
    from playwright.sync_api import sync_playwright

    html = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            context = browser.new_context(extra_http_headers=headers or {})
            page = context.new_page()
            page.goto(url, timeout=int(timeout * 1000), wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=int(timeout * 1000))
            except Exception:
                pass
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            html = page.content()
        finally:
            browser.close()
    return html
