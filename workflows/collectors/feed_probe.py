from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from engine.http import get_text

# Ordered best-first. Each entry: (kind, path, verifier).
# Deliberately a short, closed list of well-known conventions. "Find the API" in general
# is not a solvable problem - there is no discovery standard - but these four cover most
# of what a Moldovan municipal site actually runs, cost no tokens, and fail cleanly.
_LINK_RE = re.compile(
    r'<link[^>]+rel=["\']?alternate["\']?[^>]*>', re.I)
_TYPE_RE = re.compile(r'type=["\']?(application/(?:rss|atom)\+xml)["\']?', re.I)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)


def _is_json_list(text):
    try:
        return isinstance(json.loads(text), list)
    except Exception:
        return False


def _is_feed(text):
    head = (text or "")[:2000].lower()
    return "<rss" in head or "<feed" in head


def _is_sitemap(text):
    head = (text or "")[:2000].lower()
    return "<urlset" in head or "<sitemapindex" in head


_CANDIDATES = (
    ("wordpress", "/wp-json/wp/v2/posts?per_page=1", _is_json_list,
     "WordPress REST API — gives a reliable list with modification dates"),
    ("rss", "/feed", _is_feed, "RSS feed"),
    ("rss", "/rss.xml", _is_feed, "RSS feed"),
    ("sitemap", "/sitemap.xml", _is_sitemap,
     "sitemap with last-modified dates — usable for incremental crawling"),
)


def _root(url):
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _declared_feeds(html, base):
    out = []
    for tag in _LINK_RE.findall(html or ""):
        t = _TYPE_RE.search(tag)
        h = _HREF_RE.search(tag)
        if t and h:
            out.append(urljoin(base, h.group(1)))
    return out


def probe(url, timeout=8, auth=None, fetch=None):
    """Look for a structured way into a site. Returns a list of finds, best first.

    Never raises: a probe failing is normal and must not block adding a site.
    `fetch` is injectable so the tests never touch the network.
    """
    fetch = fetch or (lambda u: get_text(u, timeout=timeout, retries=0))
    finds = []
    seen = set()

    def add(kind, u, note):
        if u not in seen:
            seen.add(u)
            finds.append({"kind": kind, "url": u, "note": note})

    try:
        html = fetch(url)
    except Exception:
        html = ""
    for f in _declared_feeds(html, url):
        try:
            if _is_feed(fetch(f)):
                add("rss", f, "RSS/Atom feed declared by the page itself")
        except Exception:
            continue

    root = _root(url)
    for kind, path, verify, note in _CANDIDATES:
        candidate = root + path
        if candidate in seen:
            continue
        try:
            body = fetch(candidate)
        except Exception:
            continue
        if body and verify(body):
            add(kind, candidate, note)
    return finds


def best(finds):
    return finds[0] if finds else None
