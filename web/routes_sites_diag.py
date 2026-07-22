from __future__ import annotations

import json
import uuid

from fastapi import Form, Request

from web.render import _e
from web.sites_common import (_bar, _crawl_rows, _probe_url, _redir_sites,
                              _set_auth, _validate_url, router)
from web.user.counts import nav_counts
from web.user.icons import icon
from web.user.layout import render as _urender
from workflows import work


def _kv(pairs):
    rows = ''.join(
        f'<div class="fact"><span class="fk">{_e(k)}</span>'
        f'<span class="fv">{v}</span></div>' for k, v in pairs)
    return f'<div class="card"><div class="card-b">{rows}</div></div>'


def _page(request, title, body):
    conn, store = request.state.conn, request.state.store
    crumb = '<a class="btn ghost sm" href="/app/settings/sources">Back to sites</a>'
    acct = work.account_id(request)
    return _urender(request, title, body, heading=title, heading_icon='search',
                    actions=crumb, counts=nav_counts(conn, store, acct))


@router.post("/app/settings/sites/preview")
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
    try:
        r = preview_site(store, conn, target, render=do_render, auth=auth)
    except Exception as exc:
        return _redir_sites(err=f"test failed: {exc}")
    if r.get("error"):
        return _redir_sites(err=f"fetch failed: {r['error']}")
    hint = ""
    if do_render and not r["rendered"]:
        hint = (f'<div class="note" style="margin-bottom:12px">{icon("bang")}'
                '<span>JS rendering was requested but is not available on the server — showing '
                "the plain-HTML result.</span></div>")
    meta = _kv([
        ("URL", f'<span class="mono">{_e(target)}</span>'),
        ("Rendered with JS", "yes" if r["rendered"] else "no"),
        ("Readable text", f'{_e(r["chars"])} characters'),
        ("Tenders found", _e(r["count"])),
        ("Next-page link", "found" if r["next"] else "not found"),
        ("Total estimate", _e(r["estimate"]) if r["estimate"] else "—"),
        ("Diagnosis", _e(r["note"])),
    ])
    if r["titles"]:
        items = "".join(f'<li>{_e(t)}</li>' for t in r["titles"])
        listing = ('<div class="card"><div class="card-h"><h2>Sample tenders on this page</h2>'
                   f'</div><div class="card-b"><ul class="tlist">{items}</ul></div></div>')
    else:
        listing = ('<div class="card"><div class="empty">No tenders were extracted from this '
                   "page.</div></div>")
    return _page(request, "Site test", hint + meta + '<div class="gap"></div>' + listing)

@router.post("/app/settings/sites/analyze")
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
    try:
        r = analyze_site(store, conn, target, render=do_render, auth=auth)
    except Exception as exc:
        return _redir_sites(err=f"analysis failed: {exc}")
    if r.get("error"):
        return _redir_sites(err=r["error"])
    verdict = ('<span class="chip ok">yes</span>' if r["has_tenders"]
               else '<span class="chip plain">not on this page</span>')
    login = '<span class="chip warn">yes — needs sign-in</span>' if r["needs_login"] else "no"
    meta = _kv([
        ("URL", f'<span class="mono">{_e(target)}</span>'),
        ("Page type", _e(r["page_type"])),
        ("Tenders here?", f'{verdict} ({_e(r["tender_count"])} on page)'),
        ("Needs login", login),
        ("Rendered with JS", "yes" if r["rendered"] else "no"),
        ("Readable text", f'{_e(r["chars"])} characters'),
        ("Recommendation", _e(r["recommendation"])),
    ])
    follow_html = ""
    if r["follow"]:
        items = ""
        for f in r["follow"]:
            fu = _e(f["url"])
            items += (
                '<div class="site-h" style="padding:9px 0;border-bottom:1px solid var(--line)">'
                f'<div class="site-t"><a href="{fu}" target="_blank">{_e(f["label"])}</a>'
                f'<span class="t-doc-n mono">{fu}</span></div>'
                f'<form method=post action="/app/settings/sites/analyze" style="margin:0">'
                f'<input type=hidden name=url value="{fu}">'
                f'<button class="btn ghost sm">Analyse</button></form>'
                f'<form method=post action="/app/settings/sites/add" style="margin:0">'
                f'<input type=hidden name=kind value="tenders">'
                f'<input type=hidden name=url value="{fu}">'
                f'<input type=hidden name=label value="{_e(f["label"])}">'
                f'<button class="btn sm">Add as site</button></form></div>')
        follow_html = ('<div class="card"><div class="card-h"><h2>Where the tenders might be</h2>'
                       f'<div class="spacer"></div><span class="chip num">{len(r["follow"])}</span>'
                       f'</div><div class="card-b">{items}'
                       '<div class="pref-help" style="margin-top:10px">Candidate links the '
                       "analyser found. Analyse one, and if it lists tenders, add it as a site."
                       "</div></div></div>")
    else:
        follow_html = (f'<div class="note">{icon("info")}<span>No obvious "go here for tenders" '
                       "links were found. If the site needs a login or loads via JavaScript, a "
                       "simple crawler cannot reach it — use its API or RSS if it has one "
                       "(the Find feed button on the site card checks for that).</span></div>")
    return _page(request, "Site analysis", meta + '<div class="gap"></div>' + follow_html)


_ENGINE_LABELS = {"builtin": "plain HTML", "crawl4ai": "crawl4ai (JS + markdown)"}


@router.post("/app/settings/sites/detect")
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
    from workflows.collectors.genericweb_analyze import smart_detect

    target = url.strip()
    auth = {"type": "basic", "user": login.strip(), "pass": password} if login.strip() else None
    profile = smart_detect(store, conn, target, auth=auth)
    resolved = profile.get("url") or target

    lst = list(store.get("sites.tenders", []) or [])
    sid = uuid.uuid4().hex[:8]
    try:
        step = max(1, min(1000, int(batch_size)))
    except (TypeError, ValueError):
        step = 30
    entry = {"id": sid, "label": label.strip() or resolved, "url": resolved,
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
    if not est and profile["count"] > 0 and not profile.get("paginated"):
        est = profile["count"]
    if est:
        _gw._save_estimate(conn, sid, est)

    if profile["needs_login"]:
        _gw._save_note(conn, sid, "needs login — added disabled; set credentials, "
                                  "then turn the site back on")
        return _redir_sites(msg=f"added '{entry['label']}' (disabled)",
                            err="this site needs a login the crawler could not satisfy — "
                                "add credentials (HTTP Basic only), then enable it")

    pag = "paginated" if profile.get("paginated") else "single page"
    note = f"auto-detected: {method}, {profile['count']} tenders on test page, {pag}"
    if est:
        note += f" (est. {est} total)"
    if resolved != target:
        note += f" — using tender list {resolved}"
    _gw._save_note(conn, sid, note)
    msg = f"added '{entry['label']}' — {method}, {profile['count']} tenders found"
    if resolved != target:
        msg += " (found the tender list automatically)"
    if est:
        msg += f", ~{est} total"
    return _redir_sites(msg=msg)
