from __future__ import annotations

import json
import uuid

from fastapi import Form, Request

from web.render import _e, _layout, _table
from web.sites_common import (_bar, _crawl_rows, _probe_url, _redir_sites,
                              _set_auth, _validate_url, router)


@router.post("/sites/preview")
def sites_preview(request: Request, id: str = Form(""), url: str = Form(""),
                  render: str = Form("")):
    store = request.state.store
    conn = request.state.conn
    from workflows.collectors.genericweb import _load_state
    from workflows.collectors.genericweb_analyze import preview_site
    site = None
    for s in (store.get("sites.tenders", []) or []):
        if s.get("id") == id:
            site = s
            break
    target = (site["url"] if site else url).strip()
    if not target:
        return _redir_sites(err="no URL to test")
    if not store.get("sources.genericweb", {}).get("enabled", False):
        return _redir_sites(err="web search is off (turn it on first)")
    do_render = bool(site.get("render")) if site else (render in ("1", "on"))
    auth = _load_state(conn, site["id"])["auth"] if site else None
    r = preview_site(store, conn, target, render=do_render, auth=auth)

    back = '<p><a href="/sites">&larr; back to sites</a></p>'
    if r.get("error"):
        body = back + f'<div class="err">fetch failed: {_e(r["error"])}</div>'
        return _layout(request, "Site preview", body)
    hint = ""
    if do_render and not r["rendered"]:
        hint = ('<div class="err">JS rendering was requested but is not available on the '
                'server — showing the plain-HTML result. Install Playwright '
                '(<span class=mono>pip install playwright &amp;&amp; playwright install chromium</span>) '
                'to read JavaScript sites.</div>')
    meta = (f'<div class="card"><div class="kv">'
            f'<div class=k>URL</div><div class="mono">{_e(target)}</div>'
            f'<div class=k>rendered with JS</div><div>{"yes" if r["rendered"] else "no"}</div>'
            f'<div class=k>readable text</div><div>{_e(r["chars"])} characters</div>'
            f'<div class=k>tenders found</div><div>{_e(r["count"])}</div>'
            f'<div class=k>next page link</div><div>{"found" if r["next"] else "not found"}</div>'
            f'<div class=k>total estimate</div><div>{_e(r["estimate"]) if r["estimate"] else "—"}</div>'
            f'<div class=k>diagnosis</div><div>{_e(r["note"])}</div>'
            f'</div></div>')
    rows = [[_e(t)] for t in r["titles"]]
    listing = _table(["Sample tender titles (first 10)"], rows) if rows else \
        '<div class="card"><div class="empty">no tenders were extracted from this page</div></div>'
    return _layout(request, "Site preview", back + hint + meta + listing)

@router.post("/sites/analyze")
def sites_analyze(request: Request, id: str = Form(""), url: str = Form(""),
                  render: str = Form("")):
    store = request.state.store
    conn = request.state.conn
    from workflows.collectors.genericweb import _load_state
    from workflows.collectors.genericweb_analyze import analyze_site
    site = None
    for s in (store.get("sites.tenders", []) or []):
        if s.get("id") == id:
            site = s
            break
    target = (site["url"] if site else url).strip()
    if not target:
        return _redir_sites(err="no URL to analyze")
    if not store.get("sources.genericweb", {}).get("enabled", False):
        return _redir_sites(err="web search is off (turn it on first)")
    do_render = bool(site.get("render")) if site else (render in ("1", "on"))
    auth = _load_state(conn, site["id"])["auth"] if site else None
    r = analyze_site(store, conn, target, render=do_render, auth=auth)

    back = '<p><a href="/sites">&larr; back to sites</a></p>'
    if r.get("error"):
        return _layout(request, "Site analysis",
                       back + f'<div class="err">fetch failed: {_e(r["error"])}</div>')
    verdict = ('<span class="v-ok">yes</span>' if r["has_tenders"]
               else '<span class="v-partial">not on this page</span>')
    login = '<span class="v-cannot">yes — needs sign-in</span>' if r["needs_login"] else "no"
    meta = (f'<div class="card"><div class="kv">'
            f'<div class=k>URL</div><div class="mono">{_e(target)}</div>'
            f'<div class=k>page type</div><div>{_e(r["page_type"])}</div>'
            f'<div class=k>tenders here?</div><div>{verdict} ({_e(r["tender_count"])} on page)</div>'
            f'<div class=k>needs login</div><div>{login}</div>'
            f'<div class=k>rendered with JS</div><div>{"yes" if r["rendered"] else "no"}</div>'
            f'<div class=k>readable text</div><div>{_e(r["chars"])} characters</div>'
            f'<div class=k>recommendation</div><div>{_e(r["recommendation"])}</div>'
            f'</div></div>')
    follow_html = ""
    if r["follow"]:
        items = ""
        for f in r["follow"]:
            fu = _e(f["url"])
            items += (
                f'<div class="row" style="border-bottom:1px solid var(--line);padding:8px 0">'
                f'<div style="flex:1;min-width:220px"><a href="{fu}" target="_blank">{_e(f["label"])}</a>'
                f'<div class="mono mut" style="font-size:11px">{fu}</div></div>'
                f'<form method=post action="/sites/preview" style="margin:0">'
                f'<input type=hidden name=url value="{fu}"><button class="ghost">test</button></form>'
                f'<form method=post action="/sites/analyze" style="margin:0">'
                f'<input type=hidden name=url value="{fu}"><button class="ghost">analyze</button></form>'
                f'<form method=post action="/sites/add" style="margin:0">'
                f'<input type=hidden name=kind value="tenders">'
                f'<input type=hidden name=url value="{fu}">'
                f'<input type=hidden name=label value="{_e(f["label"])}">'
                f'<button>+ add as site</button></form></div>')
        follow_html = (f'<h2>Where the tenders might be ({len(r["follow"])} links to follow)</h2>'
                       f'<div class="card">{items}</div>'
                       f'<p class="hint">These are candidate links the analyzer found. Test or '
                       f'analyze one, and if it lists tenders, add it as a site.</p>')
    else:
        follow_html = ('<p class="hint">No obvious "go here for tenders" links were found on this '
                       'page. If the site needs a login or loads content via JavaScript, a simple '
                       'crawler cannot reach it — use the site\'s API/RSS if it has one.</p>')
    return _layout(request, "Site analysis", back + meta + follow_html)


_ENGINE_LABELS = {"builtin": "plain HTML", "crawl4ai": "crawl4ai (JS + markdown)"}


@router.post("/sites/detect")
def sites_detect(request: Request, label: str = Form(""), url: str = Form(""),
                 batch_size: str = Form("30"), login: str = Form(""),
                 password: str = Form("")):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    ok, why = _validate_url(url)
    if not ok:
        return _redir_sites(err=f"invalid URL: {why}")
    store = request.state.store
    conn = request.state.conn
    if not store.get("sources.genericweb", {}).get("enabled", False):
        return _redir_sites(err="web search is off (turn it on first)")

    from workflows.collectors import genericweb as _gw
    from workflows.collectors.genericweb_analyze import detect_site_profile

    target = url.strip()
    auth = {"type": "basic", "user": login.strip(), "pass": password} if login.strip() else None
    profile = detect_site_profile(store, conn, target, auth=auth)

    lst = list(store.get("sites.tenders", []) or [])
    sid = uuid.uuid4().hex[:8]
    try:
        step = max(1, min(1000, int(batch_size)))
    except (TypeError, ValueError):
        step = 30
    entry = {"id": sid, "label": label.strip() or target, "url": target,
             "enabled": not profile["needs_login"], "render": bool(profile["render"]),
             "engine": profile["engine"], "batch_size": step}
    lst.append(entry)
    store.set("sites.tenders", lst, actor="web", note="add site via auto-detect")
    if auth:
        _set_auth(conn, sid, auth)

    method = _ENGINE_LABELS.get(profile["engine"], profile["engine"])
    if profile["render"] and profile["engine"] != "crawl4ai":
        method += " + JS render"
    _gw._save_detected(conn, sid, profile["count"])
    est = profile.get("estimate")
    if not est and profile["count"] > 0 and not profile.get("next"):
        est = profile["count"]
    if est:
        _gw._save_estimate(conn, sid, est)

    if profile["needs_login"]:
        _gw._save_note(conn, sid, "needs login — added disabled; set credentials, "
                                  "then turn the site back on")
        return _redir_sites(msg=f"added '{entry['label']}' (disabled)",
                            err="this site needs a login the crawler could not satisfy — "
                                "add credentials (HTTP Basic only), then enable it")

    note = f"auto-detected: {method}, {profile['count']} tenders on test page"
    if est:
        note += f" (est. {est} total)"
    _gw._save_note(conn, sid, note)
    msg = f"added '{entry['label']}' — {method}, {profile['count']} tenders found"
    if est:
        msg += f", ~{est} total"
    return _redir_sites(msg=msg)
