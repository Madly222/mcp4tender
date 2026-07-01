from __future__ import annotations

import asyncio
import logging
import threading

log = logging.getLogger("tenderengine.crawl4ai")


def crawl4ai_available():
    try:
        import crawl4ai  # noqa: F401
        return True
    except Exception:
        return False


def _run_async(coro):
    try:
        asyncio.get_running_loop()
        running = True
    except RuntimeError:
        running = False
    if not running:
        return asyncio.run(coro)
    box = {}
    err = {}

    def worker():
        try:
            box["v"] = asyncio.run(coro)
        except Exception as exc:
            err["e"] = exc

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    if "e" in err:
        raise err["e"]
    return box.get("v")


async def _crawl(url, timeout, wait_ms, headers):
    from crawl4ai import (AsyncWebCrawler, BrowserConfig, CacheMode,
                          CrawlerRunConfig)
    browser = BrowserConfig(headless=True, headers=headers or {},
                            extra_args=["--no-sandbox", "--disable-dev-shm-usage"])
    run = CrawlerRunConfig(cache_mode=CacheMode.BYPASS,
                           page_timeout=int(timeout * 1000),
                           delay_before_return_html=max(0.0, wait_ms / 1000.0),
                           scan_full_page=True)
    async with AsyncWebCrawler(config=browser) as crawler:
        res = await crawler.arun(url=url, config=run)
    md = getattr(res, "markdown", None)
    if md is None:
        return getattr(res, "cleaned_html", "") or getattr(res, "html", "") or ""
    if isinstance(md, str):
        return md
    return (getattr(md, "fit_markdown", None) or getattr(md, "raw_markdown", None)
            or str(md))


def fetch_markdown(url, timeout=30, wait_ms=1500, headers=None):
    return _run_async(_crawl(url, timeout, wait_ms, headers))
