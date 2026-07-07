from __future__ import annotations

import logging
from urllib.parse import urljoin

from engine.jsonutil import loads_loose
from engine.llm import LLMGateway
from workflows.collectors import genericweb as _gw

log = logging.getLogger("tenderengine.collector.genericweb.analyze")


ANALYZE_PROMPT = (
    "You are profiling a web page to decide how to monitor it for public-procurement tenders. "
    "Links in the text are shown as 'text [absolute-url]'. Reply with a JSON object ONLY, no markdown: "
    "{\"page_type\": one of 'listing','hub','document_library','single_notice','search_form','js_app','other'; "
    "\"has_tenders\": boolean (does THIS page directly list tender/procurement announcements?); "
    "\"tender_count\": number (how many tender items are directly on this page, 0 if none); "
    "\"follow\": [{\"label\":string,\"url\":string}] up to 6 links on this page that most likely lead to "
    "tender/procurement listings or documents (labels like Tenders, Procurement, Achizitii, Anunturi, "
    "Documents, Licitatii); use absolute urls from the [url] markers; "
    "\"needs_login\": boolean (does reaching the tenders require signing in?); "
    "\"recommendation\": string (one short sentence: how to best monitor this site, or why it cannot be scraped)}. "
    "Use empty list / false / 0 when unsure."
)


def analyze_site(store, conn, url, render=False, auth=None, engine=None):
    sc = store.get("sources.genericweb", {}) or {}
    if engine:
        sc = dict(sc)
        sc["engine"] = engine
    max_chars = int(sc.get("max_input_chars", 120000))
    headers = _gw._auth_headers(auth)
    try:
        text, rendered = _gw._page_text(url, sc, headers, render, max_chars)
    except Exception as exc:
        return {"error": str(exc), "url": url}
    gw = LLMGateway(store, conn)
    out = gw.complete("site_analyze", ANALYZE_PROMPT,
                      [{"role": "user", "content": f"PAGE URL: {url}\n\n{text}"}],
                      max_tokens=int(sc.get("max_output_tokens", 8192)), prefill="{")
    data = loads_loose(out["text"])
    if not isinstance(data, dict):
        data = {}
    follow = []
    for f in (data.get("follow") or [])[:6]:
        if isinstance(f, dict) and f.get("url"):
            try:
                absu = urljoin(url, str(f["url"]))
            except Exception:
                absu = str(f["url"])
            follow.append({"label": str(f.get("label") or absu)[:90], "url": absu})
    if len(text) < 300 and not rendered:
        rec = "Very little readable text — likely a JavaScript site; try the JS toggle or an API."
    else:
        rec = str(data.get("recommendation") or "")[:400]
    return {"url": url, "rendered": rendered, "chars": len(text),
            "page_type": str(data.get("page_type") or "other"),
            "has_tenders": bool(data.get("has_tenders")),
            "tender_count": _gw._parse_int(data.get("tender_count")) or 0,
            "needs_login": bool(data.get("needs_login")),
            "follow": follow, "recommendation": rec}


def preview_site(store, conn, url, render=False, auth=None, engine=None):
    sc = store.get("sources.genericweb", {}) or {}
    if engine:
        sc = dict(sc)
        sc["engine"] = engine
    max_chars = int(sc.get("max_input_chars", 120000))
    headers = _gw._auth_headers(auth)
    try:
        text, rendered = _gw._page_text(url, sc, headers, render, max_chars)
    except Exception as exc:
        return {"error": str(exc), "url": url}
    gw = LLMGateway(store, conn)
    tenders, nxt, est = _gw._extract(gw, store, text, url, sc)
    titles = [t.get("title") for t in tenders[:10] if isinstance(t, dict) and t.get("title")]
    return {"url": url, "chars": len(text), "rendered": rendered, "count": len(tenders),
            "titles": titles, "next": nxt, "estimate": est,
            "note": _gw._diag_note(text, len(tenders), est)}


DETECT_FUNNEL = (
    {"engine": "builtin", "render": False, "label": "plain HTML"},
    {"engine": "builtin", "render": True, "label": "rendered (JS)"},
    {"engine": "crawl4ai", "render": True, "label": "crawl4ai (JS + markdown)"},
)

DETECT_IMPROVEMENT_RATIO = 1.2


def detect_site_profile(store, conn, url, auth=None):
    steps = []
    best = None
    needs_login = False

    for step in DETECT_FUNNEL:
        if step["engine"] == "crawl4ai":
            from engine import crawl4ai_fetch
            if not crawl4ai_fetch.crawl4ai_available():
                steps.append({**step, "skipped": "crawl4ai not installed"})
                continue

        result = preview_site(store, conn, url, render=step["render"], auth=auth,
                              engine=step["engine"])
        if result.get("error"):
            steps.append({**step, "error": result["error"]})
            continue

        step_result = {**step, "rendered": result["rendered"], "chars": result["chars"],
                       "count": result["count"], "estimate": result["estimate"],
                       "next": bool(result["next"]), "note": result["note"]}
        steps.append(step_result)

        if step_result["count"] == 0 and result["chars"] < 400:
            diag = analyze_site(store, conn, url, render=step["render"], auth=auth,
                                engine=step["engine"])
            if not diag.get("error") and diag.get("needs_login"):
                needs_login = True
                step_result["needs_login"] = True
                step_result["recommendation"] = diag.get("recommendation")
                break

        est = step_result["estimate"]
        if est and step_result["count"] >= est:
            best = step_result
            break

        if best is None:
            best = step_result
            continue

        if step_result["count"] >= best["count"] * DETECT_IMPROVEMENT_RATIO:
            best = step_result
            continue

        break

    if best is None and steps:
        scored = [s for s in steps if "count" in s]
        best = max(scored, key=lambda s: s["count"]) if scored else None

    profile = {
        "url": url,
        "engine": best["engine"] if best else "builtin",
        "render": bool(best.get("render")) if best else False,
        "count": best.get("count", 0) if best else 0,
        "estimate": best.get("estimate") if best else None,
        "next": bool(best.get("next")) if best else False,
        "needs_login": needs_login,
        "steps": steps,
    }
    return profile
