from __future__ import annotations

import json
import uuid

from fastapi import Form, Request

from web.render import _e, _layout, _table
from web.sites_common import (_bar, _crawl_rows, _probe_url, _redir_sites,
                              _set_auth, _validate_url, router)


@router.post("/app/settings/sites/add")
def sites_add(request: Request, kind: str = Form(...), label: str = Form(""),
              url: str = Form(""), category: str = Form(""), notes: str = Form(""),
              batch_size: str = Form("30"), login: str = Form(""), password: str = Form(""),
              render: str = Form(""), engine: str = Form("")):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    ok, why = _validate_url(url)
    if not ok:
        return _redir_sites(err=f"invalid URL: {why}")
    reachable, rmsg = _probe_url(url)
    store = request.state.store
    key = "sites.tenders" if kind == "tenders" else "sites.partners"
    lst = list(store.get(key, []) or [])
    sid = uuid.uuid4().hex[:8]
    entry = {"id": sid, "label": label.strip() or url.strip(), "url": url.strip()}
    if kind == "tenders":
        entry["enabled"] = True
        entry["render"] = render in ("1", "on", "true")
        if engine.strip().lower() in ("builtin", "crawl4ai"):
            entry["engine"] = engine.strip().lower()
        try:
            entry["batch_size"] = max(1, min(1000, int(batch_size)))
        except (TypeError, ValueError):
            entry["batch_size"] = 30
    else:
        entry["category"] = category.strip()
        entry["notes"] = notes.strip()
    lst.append(entry)
    store.set(key, lst, actor="web", note="add site via web")
    if kind == "tenders" and login.strip():
        _set_auth(request.state.conn, sid,
                  {"type": "basic", "user": login.strip(), "pass": password})

    est_note = ""
    if kind == "tenders" and store.get("sources.genericweb", {}).get("enabled", False):
        from engine import run_collector
        try:
            run_collector("genericweb", store, request.state.conn,
                          params={"mode": "estimate", "site_id": sid})
            row = request.state.conn.execute(
                "SELECT total_estimate FROM crawl_state WHERE site_id=?", (sid,)).fetchone()
            if row and row["total_estimate"]:
                est_note = f" · estimated ~{row['total_estimate']} tenders"
        except Exception:
            est_note = ""
    if reachable:
        return _redir_sites(msg=f"added (site reachable){est_note}")
    return _redir_sites(msg="added", err=f"warning: site not reachable now ({rmsg}) — "
                        f"saved anyway, check the URL")

@router.post("/app/settings/sites/settings")
def sites_settings(request: Request, id: str = Form(...), batch_size: str = Form("30")):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    try:
        n = max(1, min(1000, int(batch_size)))
    except (TypeError, ValueError):
        n = 30
    store = request.state.store
    lst = list(store.get("sites.tenders", []) or [])
    for s in lst:
        if s.get("id") == id:
            s["batch_size"] = n
    store.set("sites.tenders", lst, actor="web", note="set batch via web")
    return _redir_sites(msg=f"batch set: {n} tenders")

@router.post("/app/settings/sites/auth")
def sites_auth(request: Request, id: str = Form(...), login: str = Form(""),
               password: str = Form("")):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    auth = {"type": "basic", "user": login.strip(), "pass": password} if login.strip() else None
    _set_auth(request.state.conn, id, auth)
    return _redir_sites(msg="login saved" if auth else "login cleared")

@router.post("/app/settings/sites/reset-cursor")
def sites_reset(request: Request, id: str = Form(...)):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    request.state.conn.execute(
        "UPDATE crawl_state SET next_url=NULL, exhausted=0, total_collected=0 WHERE site_id=?",
        (id,))
    request.state.conn.commit()
    return _redir_sites(msg="crawl position reset")

@router.post("/app/settings/sites/remove")
def sites_remove(request: Request, kind: str = Form(...), id: str = Form(...)):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    store = request.state.store
    key = "sites.tenders" if kind == "tenders" else "sites.partners"
    lst = [s for s in (store.get(key, []) or []) if s.get("id") != id]
    store.set(key, lst, actor="web", note="remove site via web")
    if kind == "tenders":
        request.state.conn.execute("DELETE FROM crawl_state WHERE site_id=?", (id,))
        request.state.conn.commit()
    return _redir_sites(msg="removed")

@router.post("/app/settings/sites/toggle")
def sites_toggle(request: Request, id: str = Form(...)):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    store = request.state.store
    lst = list(store.get("sites.tenders", []) or [])
    for s in lst:
        if s.get("id") == id:
            s["enabled"] = not s.get("enabled", True)
    store.set("sites.tenders", lst, actor="web", note="toggle site via web")
    return _redir_sites()

@router.post("/app/settings/sites/search-toggle")
def sites_search_toggle(request: Request):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    store = request.state.store
    cfg = dict(store.get("sources.genericweb", {}) or {})
    cfg["enabled"] = not cfg.get("enabled", False)
    store.set("sources.genericweb", cfg, actor="web", note="toggle web search via web")
    return _redir_sites(msg="web search: " + ("on" if cfg["enabled"] else "off"))

@router.post("/app/settings/sites/render-toggle")
def sites_render_toggle(request: Request, id: str = Form(...)):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    store = request.state.store
    lst = list(store.get("sites.tenders", []) or [])
    state = False
    for s in lst:
        if s.get("id") == id:
            s["render"] = not s.get("render", False)
            state = s["render"]
    store.set("sites.tenders", lst, actor="web", note="toggle render via web")
    return _redir_sites(msg="JS rendering " + ("on" if state else "off"))

from web import routes_sites_collect, routes_sites_diag, sites_view  # noqa: E402,F401
