from __future__ import annotations

import json
import uuid

from fastapi import Form, Request

from web.render import _e, _layout, _table
from web.sites_common import (append_site, mutate_sites,
                              _bar, _crawl_rows, _probe_url, _redir_sites,
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
    append_site(store, entry, "add site via web", key=key)
    if kind == "tenders" and login.strip():
        _set_auth(request.state.conn, sid,
                  {"type": "basic", "user": login.strip(), "pass": password})

    feed_note = ""
    if kind == "tenders":
        try:
            from workflows.collectors.feed_probe import probe
            top = _save_probe(store, sid, probe(entry["url"]))
            if top:
                feed_note = f" · found a {top['kind']} feed"
        except Exception:
            feed_note = ""

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
        return _redir_sites(msg=f"added (site reachable){est_note}{feed_note}")
    return _redir_sites(msg="added", err=f"warning: site not reachable now ({rmsg}) — "
                        f"saved anyway, check the URL")

def _save_probe(store, sid, finds):
    top = finds[0] if finds else None

    def apply(lst):
        for site in lst:
            if site.get("id") == sid:
                site["feed_kind"] = top["kind"] if top else None
                site["feed_url"] = top["url"] if top else None
                site["feed_note"] = top["note"] if top else "nothing found"

    mutate_sites(store, apply, "feed probe", actor="app")
    return top


@router.post("/app/settings/sites/probe")
def sites_probe(request: Request, id: str = Form(...)):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    store = request.state.store
    site = next((s for s in (store.get("sites.tenders", []) or []) if s.get("id") == id), None)
    if not site:
        return _redir_sites(err="no such site")
    from workflows.collectors.feed_probe import probe
    top = _save_probe(store, id, probe(site.get("url")))
    if not top:
        return _redir_sites(msg="no feed or API found — this site will be read page by page")
    return _redir_sites(msg=f"found {top['kind']}: {top['url']}")


@router.post("/app/settings/sites/settings")
def sites_settings(request: Request, id: str = Form(...), batch_size: str = Form("30"),
                   date_order: str = Form("")):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    try:
        n = max(1, min(1000, int(batch_size)))
    except (TypeError, ValueError):
        n = 30
    order = date_order if date_order in ("dmy", "mdy") else ""

    def apply(lst):
        for s in lst:
            if s.get("id") == id:
                s["batch_size"] = n
                if order:
                    s["date_order"] = order
                elif "date_order" in s:
                    s.pop("date_order")

    mutate_sites(request.state.store, apply, "set batch via web")
    return _redir_sites(msg=f"batch set: {n} tenders")

@router.post("/app/settings/sites/rank")
def sites_rank(request: Request, token: str = Form(...), dir: str = Form("up")):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    from web.source_rank import move
    store = request.state.store
    order = move(store, token.strip(), "up" if dir != "down" else "down")
    store.set("sources.rank", order, actor="web", note="reorder source strength via web")
    return _redir_sites(msg="source strength updated")


@router.post("/app/settings/sites/edit-url")
def sites_edit_url(request: Request, id: str = Form(...), url: str = Form(""),
                   label: str = Form("")):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    ok, err = _validate_url(url)
    if not ok:
        return _redir_sites(err=err)
    hit = {"found": False}

    def apply(lst):
        for s in lst:
            if s.get("id") == id:
                s["url"] = url.strip()
                if label.strip():
                    s["label"] = label.strip()
                hit["found"] = True

    mutate_sites(request.state.store, apply, "edit site url via web")
    if not hit["found"]:
        return _redir_sites(err="site not found")
    return _redir_sites(msg="link updated")


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
    key = "sites.tenders" if kind == "tenders" else "sites.partners"

    def apply(lst):
        lst[:] = [s for s in lst if s.get("id") != id]

    mutate_sites(request.state.store, apply, "remove site via web", key=key)
    if kind == "tenders":
        request.state.conn.execute("DELETE FROM crawl_state WHERE site_id=?", (id,))
        request.state.conn.commit()
    return _redir_sites(msg="removed")

@router.post("/app/settings/sites/toggle")
def sites_toggle(request: Request, id: str = Form(...)):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    def apply(lst):
        for s in lst:
            if s.get("id") == id:
                s["enabled"] = not s.get("enabled", True)

    mutate_sites(request.state.store, apply, "toggle site via web")
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
    box = {"state": False}

    def apply(lst):
        for s in lst:
            if s.get("id") == id:
                s["render"] = not s.get("render", False)
                box["state"] = s["render"]

    mutate_sites(request.state.store, apply, "toggle render via web")
    return _redir_sites(msg="JS rendering " + ("on" if box["state"] else "off"))

from web import routes_sites_collect, routes_sites_diag, sites_view  # noqa: E402,F401
