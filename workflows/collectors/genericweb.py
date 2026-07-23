from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import json
import logging
import re
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from engine.collectors import (CollectContext, CollectedItem, CollectResult,
                               Collector, register_collector)
from engine.hashing import content_hash
from engine.http import get_text
from engine.dateparse import normalize_field, parse_date
from engine.lifecycle import archive_reason, collect_ceiling
from engine.jsonutil import loads_loose
from engine.llm import LLMGateway

log = logging.getLogger("tenderengine.collector.genericweb")

DEFAULT_EXTRACT_PROMPT = (
    "You crawl public-procurement / tender listing pages. "
    "From the page text, extract ALL tender announcements present, find the link "
    "to the NEXT page of results, and read the total number of results if the site states it. "
    "Reply with a JSON object ONLY, no markdown, no extra text: "
    "{\"tenders\":[{\"title\":string,\"url\":string|null,\"ref\":string|null,\"buyer\":string|null,"
    "\"deadline\":string|null,\"enquiry_deadline\":string|null,\"date\":string|null,"
    "\"value\":string|null,\"currency\":string|null,"
    "\"description\":string|null}],\"next_page_url\":string|null,\"total_estimate\":number|null,"
    "\"last_page\":number|null}. "
    "Links in the text are shown as 'text [absolute-url]'. "
    "ref = the tender/notice reference number if shown, else null. "
    "next_page_url = the absolute URL of the pagination link to the NEXT / older page "
    "(labels like next, '>', '\u203a', 'urmatorul', 'weiter', or page N+1), or null if none. "
    "total_estimate = the total count of announcements on the whole section if the page shows it "
    "anywhere, in any language (e.g. 'Showing 1-20 of 1234', '1234 results', '1234 rezultate', "
    "'1234 anunturi', '1234 licitatii', 'din 1234', 'total 1234', 'Gasite 1234', "
    "'Найдено 1234', 'Всего 1234', '1-20 din 1234' -> 1234), else null. "
    "last_page = the highest page number visible in the pagination (e.g. links '1 2 3 ... 250', a "
    "'last'/'ultima'/'Последняя' link to page 250, or '?page=250' in a last-page link -> 250), else null. "
    "date = the publication/posting date of the tender if shown, else null. "
    "deadline = the submission deadline (termen limita de depunere), else null. "
    "enquiry_deadline = the deadline for questions/clarifications (limita clarificari), else null. "
    "For all three dates prefer ISO YYYY-MM-DD (append THH:MM when an hour is shown); "
    "if unsure, copy the date text exactly as printed. "
    "Use null for any missing field. If there are no announcements, return an empty tenders list."
)


def _html_to_text(raw, base_url, max_chars):
    if not raw:
        return ""
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)

    def _anchor(m):
        href = m.group("href")
        txt = re.sub(r"<[^>]+>", " ", m.group("txt"))
        txt = re.sub(r"\s+", " ", html.unescape(txt)).strip()
        try:
            absu = urljoin(base_url, href)
        except Exception:
            absu = href
        return f" {txt} [{absu}] "

    raw = re.sub(r'<a\b[^>]*href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<txt>.*?)</a>',
                 _anchor, raw, flags=re.I | re.S)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()[:max_chars]


def _md_links_to_inline(md, base):
    if not md:
        return ""

    def _lnk(m):
        text = (m.group(1) or "").strip()
        href = (m.group(2) or "").strip()
        try:
            absu = urljoin(base, href)
        except Exception:
            absu = href
        return f"{text} [{absu}]"

    md = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)", _lnk, md)
    md = re.sub(r"\[([^\]]*)\]\(([^)\s]+)[^)]*\)", _lnk, md)
    return re.sub(r"\s+", " ", md).strip()


def _page_text(url, sc, headers, render, max_chars):
    engine = str(sc.get("engine") or "builtin").lower()
    if engine == "crawl4ai":
        from engine import crawl4ai_fetch
        if crawl4ai_fetch.crawl4ai_available():
            try:
                md = crawl4ai_fetch.fetch_markdown(
                    url, timeout=int(sc.get("timeout", 30)),
                    wait_ms=int(sc.get("wait_ms", 1500)), headers=headers)
                return _md_links_to_inline(md, url)[:max_chars], True
            except Exception as exc:
                log.warning("crawl4ai fetch failed (%s); falling back to builtin", exc)
        else:
            log.warning("engine=crawl4ai selected but the library is not installed; using builtin")
    raw, rendered = _fetch(url, int(sc.get("timeout", 30)), headers, render)
    return _html_to_text(raw, url, max_chars), rendered


def _parse_value(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^\d,.\-]", "", str(value))
    if not s:
        return None
    has_c, has_d = "," in s, "." in s
    if has_c and has_d:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_c:
        if s.count(",") == 1 and len(s.split(",")[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = re.sub(r"[^\d]", "", str(value))
    return int(s) if s else None


_TRACK_PARAMS = {"fbclid", "gclid", "sid", "sessionid", "phpsessid", "jsessionid"}


def _canon_url(u):
    s = str(u or "").strip()
    try:
        p = urlsplit(s)
    except Exception:
        return s.lower()
    if not p.scheme and not p.netloc:
        return s.lower()
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False)
         if not k.lower().startswith("utm_") and k.lower() not in _TRACK_PARAMS]
    q.sort()
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(q), "")).lower()


def _external_id(site_id, item):
    url = item.get("url")
    if url:
        seed = _canon_url(url)
    elif item.get("ref"):
        seed = re.sub(r"\s+", "", str(item["ref"]).lower())
    else:
        seed = re.sub(r"\s+", " ", str(item.get("title") or "").strip().lower())
    h = hashlib.sha1(seed[:300].encode("utf-8")).hexdigest()[:16]
    return f"{site_id}:{h}"


def _tender_date(date_str):
    return parse_date(date_str)


def _tender_age_days(date_str):
    d = _tender_date(date_str)
    if d is None:
        return None
    return (dt.datetime.now(dt.timezone.utc).date() - d).days


def _normalize_item(site, item):
    url = item.get("url")
    title = item.get("title")
    fmt = None
    if url:
        low = url.lower()
        for ext in (".pdf", ".docx", ".doc", ".xlsx"):
            if low.endswith(ext):
                fmt = ext.lstrip(".")
    docs = []
    if url:
        docs.append({"title": title, "url": url, "type": "tenderNotice",
                     "format": fmt or "html"})
    return {
        "ocid": None,
        "title": title,
        "description": item.get("description"),
        "status": None,
        "buyer": item.get("buyer"),
        "value_amount": _parse_value(item.get("value")),
        "value_currency": item.get("currency"),
        "procurement_method": None,
        "main_category": None,
        "cpv": [],
        "deadline": normalize_field(item.get("deadline")),
        "deadline_raw": item.get("deadline"),
        "enquiry_deadline": normalize_field(item.get("enquiry_deadline")),
        "enquiry_deadline_raw": item.get("enquiry_deadline"),
        "publication_date": normalize_field(item.get("date")),
        "published_raw": item.get("date"),
        "documents": docs,
        "date": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_site": site.get("label") or site.get("url"),
        "source_site_url": site.get("url"),
        "url": url,
    }


_PAGE_PARAM_RE = re.compile(r"([?&](?:page|pagina|pg|p)=)(\d+)", re.I)
_PAGE_PATH_RE = re.compile(r"(/(?:page|pagina)/)(\d+)", re.I)
_OFFSET_PARAM_RE = re.compile(r"([?&](?:offset|start|from)=)(\d+)", re.I)


def _increment_page(url, per_page=None):
    for rx in (_PAGE_PARAM_RE, _PAGE_PATH_RE):
        m = rx.search(url)
        if m:
            return url[:m.start(2)] + str(int(m.group(2)) + 1) + url[m.end(2):]
    if per_page and per_page > 0:
        m = _OFFSET_PARAM_RE.search(url)
        if m:
            return url[:m.start(2)] + str(int(m.group(2)) + per_page) + url[m.end(2):]
    return None


def _auth_headers(auth):
    if not auth:
        return None
    t = auth.get("type")
    if t == "basic" and auth.get("user"):
        token = base64.b64encode(
            f"{auth.get('user', '')}:{auth.get('pass', '')}".encode()).decode()
        return {"Authorization": "Basic " + token}
    if t == "cookie" and auth.get("value"):
        return {"Cookie": auth["value"]}
    if t == "header" and auth.get("name"):
        return {auth["name"]: auth.get("value", "")}
    return None


API_COVERED_HOSTS = ("mtender.md", "www.mtender.md", "mtender.gov.md",
                     "public.mtender.gov.md")


def api_covered(url):
    """Is this host already collected by a dedicated API collector?

    Scraping such a site is pure waste: it costs tokens on the user's key to obtain data
    we already get free and structured. Worse, the scraped copy is poorer - no OCDS status,
    no statusDetails, no awards - so it would quietly undo the inbox filter.
    """
    from urllib.parse import urlparse
    host = (urlparse((url or "").strip()).netloc or "").lower().split(":")[0]
    return any(host == h or host.endswith("." + h) for h in API_COVERED_HOSTS)


def _load_state(conn, site_id):
    row = conn.execute(
        "SELECT next_url, auth_json, total_collected, exhausted, total_estimate, page_hash "
        "FROM crawl_state WHERE site_id = ?", (site_id,)).fetchone()
    if not row:
        return {"next_url": None, "auth": None, "total": 0, "exhausted": 0, "estimate": None,
                "page_hash": None}
    auth = None
    if row["auth_json"]:
        try:
            auth = json.loads(row["auth_json"])
        except Exception:
            auth = None
    return {"next_url": row["next_url"], "auth": auth,
            "total": row["total_collected"] or 0, "exhausted": row["exhausted"] or 0,
            "estimate": row["total_estimate"], "page_hash": row["page_hash"]}


def _save_state(conn, site_id, next_url, total, exhausted):
    conn.execute(
        "INSERT INTO crawl_state(site_id, next_url, last_run_at, total_collected, exhausted) "
        "VALUES(?,?,?,?,?) ON CONFLICT(site_id) DO UPDATE SET next_url=excluded.next_url, "
        "last_run_at=excluded.last_run_at, total_collected=excluded.total_collected, "
        "exhausted=excluded.exhausted",
        (site_id, next_url, time.time(), total, 1 if exhausted else 0))
    conn.commit()


def _save_estimate(conn, site_id, estimate):
    if estimate is None:
        return
    conn.execute(
        "INSERT INTO crawl_state(site_id, total_estimate, last_run_at) VALUES(?,?,?) "
        "ON CONFLICT(site_id) DO UPDATE SET total_estimate=excluded.total_estimate, "
        "last_run_at=excluded.last_run_at",
        (site_id, int(estimate), time.time()))
    conn.commit()


def _save_detected(conn, site_id, count):
    if count is None:
        return
    conn.execute(
        "INSERT INTO crawl_state(site_id, detected_count, last_run_at) VALUES(?,?,?) "
        "ON CONFLICT(site_id) DO UPDATE SET detected_count=excluded.detected_count, "
        "last_run_at=excluded.last_run_at",
        (site_id, int(count), time.time()))
    conn.commit()


def _save_page_hash(conn, site_id, phash):
    conn.execute(
        "INSERT INTO crawl_state(site_id, page_hash, last_run_at) VALUES(?,?,?) "
        "ON CONFLICT(site_id) DO UPDATE SET page_hash=excluded.page_hash, "
        "last_run_at=excluded.last_run_at",
        (site_id, phash, time.time()))
    conn.commit()


def _save_note(conn, site_id, note):
    conn.execute(
        "INSERT INTO crawl_state(site_id, note, last_run_at) VALUES(?,?,?) "
        "ON CONFLICT(site_id) DO UPDATE SET note=excluded.note, last_run_at=excluded.last_run_at",
        (site_id, note, time.time()))
    conn.commit()


def _diag_note(text, n_tenders, est):
    if est:
        return f"~{est} tenders detected on site"
    if len(text) < 400:
        return "very little readable text — site is likely JavaScript-rendered (use an API source)"
    if n_tenders == 0:
        return "no tenders read on first page — JavaScript site or wrong URL"
    return "no total count shown by the site (progress % is approximate)"


def _fetch(url, timeout, headers, render):
    if render:
        try:
            from engine.render import get_text_rendered
            return get_text_rendered(url, timeout=timeout, headers=headers), True
        except Exception as exc:
            log.warning("rendered fetch failed (%s); falling back to plain GET", exc)
    return get_text(url, timeout=timeout, headers=headers), False


def _site_sc(sc, site):
    engine = site.get("engine")
    if engine:
        sc = dict(sc)
        sc["engine"] = engine
    return sc


def _touch_state(conn, site_id):
    conn.execute(
        "INSERT INTO crawl_state(site_id, last_run_at) VALUES(?,?) "
        "ON CONFLICT(site_id) DO UPDATE SET last_run_at=excluded.last_run_at",
        (site_id, time.time()))
    conn.commit()


def _exists(conn, ext):
    return conn.execute(
        "SELECT 1 FROM tenders WHERE source = 'genericweb' AND external_id = ?",
        (ext,)).fetchone() is not None


def _extract(gw, store, page_text, current_url, sc):
    prompt = sc.get("extract_prompt") or DEFAULT_EXTRACT_PROMPT
    user = f"PAGE URL: {current_url}\n\n{page_text}"
    max_tokens = int(sc.get("max_output_tokens", 8192))
    out = gw.complete("site_collect", prompt, [{"role": "user", "content": user}],
                      max_tokens=max_tokens, prefill="{")
    data = loads_loose(out["text"])
    if isinstance(data, list):
        data = {"tenders": data}
    if not isinstance(data, dict):
        data = {}
    tenders = data.get("tenders") or []
    if not isinstance(tenders, list):
        tenders = []
    nxt = data.get("next_page_url")
    nxt = nxt if isinstance(nxt, str) and nxt.strip() else None
    est = _parse_int(data.get("total_estimate"))
    last_page = _parse_int(data.get("last_page"))
    if est is None and last_page and len(tenders):
        est = last_page * len(tenders)
    log.debug("model=%s out_tokens=%s tenders=%d next=%s est=%s last_page=%s",
              out.get("model"), out.get("output_tokens"), len(tenders), bool(nxt), est, last_page)
    return tenders, nxt, est


def _batch_target(site, fallback):
    n = site.get("batch_size")
    if n is None:
        n = fallback
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = fallback
    return max(1, n)


@register_collector("genericweb")
class GenericWebCollector(Collector):
    def normalize(self, raw, external_id):
        return _normalize_item(raw.get("site", {}), raw.get("item", {}))

    def collect(self, ctx: CollectContext) -> CollectResult:
        store = ctx.config
        conn = store.conn
        sc = ctx.source_config
        params = getattr(ctx, "params", {}) or {}
        mode = params.get("mode", "incremental")
        only_site = params.get("site_id")
        timeout = int(sc.get("timeout", 30))
        max_chars = int(sc.get("max_input_chars", 120000))
        hard_cap = int(sc.get("max_pages_per_run", 60))
        inc_cap = int(sc.get("incremental_max_pages", 5))
        fallback = int(sc.get("fallback_batch", 30))
        max_age = collect_ceiling(store)
        sites = store.get("sites.tenders", []) or []
        gw = LLMGateway(store, conn)
        log.info("collect start mode=%s sites=%d", mode, len(sites))

        items = []
        fetched = 0
        too_old = 0
        for site in sites:
            if not site.get("enabled", True) or not site.get("url"):
                continue
            if api_covered(site["url"]):
                log.warning("skipping %s: already collected via its API, scraping it would "
                            "spend tokens for worse data", site.get("url"))
                continue
            if only_site and site.get("id") != only_site:
                continue
            site_id = site.get("id") or hashlib.sha1(
                site["url"].encode("utf-8")).hexdigest()[:8]
            state = _load_state(conn, site_id)
            headers = _auth_headers(state["auth"])

            site_sc = _site_sc(sc, site)
            if mode == "estimate":
                try:
                    text, _rendered = _page_text(site["url"], site_sc, headers,
                                                 bool(site.get("render")), max_chars)
                except Exception as exc:
                    log.warning("estimate fetch failed site=%s: %s", site.get("label"), exc)
                    continue
                tenders, _, est = _extract(gw, store, text, site["url"], sc)
                if est is not None:
                    _save_estimate(conn, site_id, est)
                _save_note(conn, site_id, _diag_note(text, len(tenders), est))
                log.info("site=%s estimate=%s text_chars=%d tenders=%d",
                         site.get("label"), est, len(text), len(tenders))
                continue

            target = _batch_target(site, fallback)
            page_cap = inc_cap if mode == "incremental" else hard_cap
            current = (state["next_url"] or site["url"]) if mode == "backfill" else site["url"]

            seen_ext = set()
            seen_pages = set()
            new_in_batch = 0
            pages = 0
            resume = current
            first_est = None
            first_diag = None
            site_too_old = 0
            oldest_kept = None
            while current and current not in seen_pages and pages < page_cap:
                seen_pages.add(current)
                pages += 1
                try:
                    text, _rendered = _page_text(current, site_sc, headers,
                                                 bool(site.get("render")), max_chars)
                except Exception as exc:
                    log.warning("fetch failed site=%s url=%s: %s",
                                site.get("label"), current, exc)
                    break
                phash = content_hash(text) if (mode == "incremental" and pages == 1) else None
                if phash and state["page_hash"] == phash:
                    _save_note(conn, site_id,
                               "front page unchanged since last check — model call skipped")
                    log.info("site=%s incremental: front page unchanged, skipped",
                             site.get("label"))
                    resume = None
                    break
                tenders, next_url, est = _extract(gw, store, text, current, sc)
                if phash:
                    _save_page_hash(conn, site_id, phash)
                if first_est is None and est is not None:
                    first_est = est
                if first_diag is None:
                    first_diag = _diag_note(text, len(tenders), est)
                page_new = 0
                for t in tenders:
                    if not isinstance(t, dict) or not t.get("title"):
                        continue
                    if max_age and max_age > 0:
                        reason = archive_reason(parse_date(t.get("date")),
                                                parse_date(t.get("deadline")),
                                                archive_days=max_age)
                        if reason:
                            too_old += 1
                            site_too_old += 1
                            continue
                    try:
                        ext = _external_id(site_id, t)
                        if ext in seen_ext:
                            continue
                        seen_ext.add(ext)
                        d = _tender_date(t.get("date"))
                        if d is not None and (oldest_kept is None or d < oldest_kept):
                            oldest_kept = d
                        items.append(CollectedItem(
                            external_id=ext, raw={"site": site, "item": t},
                            normalized=_normalize_item(site, t)))
                        fetched += 1
                        if not _exists(conn, ext):
                            new_in_batch += 1
                            page_new += 1
                    except Exception as exc:
                        log.warning("skipped malformed tender site=%s: %s",
                                    site.get("label"), exc)
                        continue
                log.info("site=%s page=%d url=%s tenders=%d new=%d next=%s",
                         site.get("label"), pages, current, len(tenders), page_new,
                         bool(next_url))
                if not tenders:
                    resume = None
                    break
                inc = _increment_page(current, len(tenders))
                if inc:
                    next_url = inc
                resume = next_url
                if mode == "incremental" and page_new == 0:
                    break
                if mode == "backfill" and new_in_batch >= target:
                    break
                if site_too_old > 0:
                    resume = None
                    break
                current = next_url

            if first_est is not None:
                _save_estimate(conn, site_id, first_est)
            if mode == "backfill":
                got = state["total"] + new_in_batch
                est = first_est or state["estimate"]
                if site_too_old > 0:
                    kept = oldest_kept.isoformat() if oldest_kept else "unknown"
                    _save_state(conn, site_id, None, got, True)
                    _save_note(conn, site_id,
                               f"reached age limit ({max_age}d): last kept tender {kept}, "
                               f"{site_too_old} older skipped — stopping (nothing newer past here).")
                elif resume is None:
                    if est and got < int(est * 0.9):
                        _save_state(conn, site_id, None, got, False)
                        _save_note(conn, site_id,
                                   f"stopped at ~{got}/{est}: no readable tenders past page "
                                   f"{pages} — this site likely loads further pages with JavaScript. "
                                   f"Turn on JS (needs Playwright) or use an API source.")
                    else:
                        _save_state(conn, site_id, None, got, True)
                        _save_note(conn, site_id, "all collected")
                else:
                    _save_state(conn, site_id, resume, got, False)
                    _save_note(conn, site_id,
                               f"in progress: {got}" + (f" / {est}" if est else "")
                               + " — press next to continue")
                log.info("site=%s backfill: +%d new (target=%d, est=%s), pages=%d, resume=%s",
                         site.get("label"), new_in_batch, target,
                         first_est or state["estimate"], pages, resume)
            else:
                if first_diag is not None:
                    _save_note(conn, site_id, first_diag)
                else:
                    _touch_state(conn, site_id)
                log.info("site=%s incremental: +%d new, pages=%d",
                         site.get("label"), new_in_batch, pages)

        cursor = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log.info("collect done mode=%s: %d item(s), %d too old", mode, fetched, too_old)
        return CollectResult(items=items, cursor=cursor, fetched=fetched, too_old=too_old)
