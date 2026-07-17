from __future__ import annotations

import json
import uuid

from fastapi import Form, Request

from web.render import _e, _layout, _table
from web.sites_common import (_bar, _crawl_rows, _probe_url, _redir_sites,
                              _set_auth, _validate_url, router)


@router.post("/app/settings/sites/estimate")
def sites_estimate(request: Request, id: str = Form("")):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    store = request.state.store
    if not store.get("sources.genericweb", {}).get("enabled", False):
        return _redir_sites(err="web search is off (turn it on first)")
    from engine import run_collector
    params = {"mode": "estimate"}
    if id.strip():
        params["site_id"] = id.strip()
    try:
        run_collector("genericweb", store, request.state.conn, params=params)
    except Exception as ex:
        return _redir_sites(err=f"estimate: {ex}")
    return _redir_sites(msg="estimate updated")

@router.post("/app/settings/sites/collect")
def sites_collect(request: Request):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    from engine import run_collector
    try:
        r = run_collector("genericweb", request.state.store, request.state.conn,
                          params={"mode": "incremental"})
    except Exception as ex:
        return _redir_sites(err=f"collect: {ex}")
    if r.get("status") == "disabled":
        return _redir_sites(err="web search is off (turn it on first)")
    msg = f"check new: {r.get('new', 0)} new of {r.get('fetched', 0)} seen"
    if r.get("too_old"):
        msg += f", skipped {r['too_old']} older than the age limit"
    return _redir_sites(msg=msg)

@router.post("/app/settings/sites/collect-batch")
def sites_collect_batch(request: Request, site_id: str = Form("")):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    from engine import run_collector
    params = {"mode": "backfill"}
    if site_id.strip():
        params["site_id"] = site_id.strip()
    try:
        r = run_collector("genericweb", request.state.store, request.state.conn, params=params)
    except Exception as ex:
        return _redir_sites(err=f"collect: {ex}")
    if r.get("status") == "disabled":
        return _redir_sites(err="web search is off (turn it on first)")
    msg = f"collected {r.get('new', 0)} new"
    if r.get("too_old"):
        msg += f", skipped {r['too_old']} older than the age limit"
    return _redir_sites(msg=msg)

@router.post("/app/settings/sites/wipe")
def sites_wipe(request: Request):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    from workflows.analysis import wipe_collected
    n = wipe_collected(request.state.conn, source="genericweb", forget=True)
    return _redir_sites(msg=f"cleared {n} collected tender(s) and reset all progress")

@router.post("/app/settings/sites/mtender-toggle")
def sites_mtender_toggle(request: Request):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    store = request.state.store
    cfg = dict(store.get("sources.mtender", {}) or {})
    cfg["enabled"] = not cfg.get("enabled", False)
    store.set("sources.mtender", cfg, actor="web", note="toggle mtender via web")
    return _redir_sites(msg="MTender API: " + ("on" if cfg["enabled"] else "off"))

@router.post("/app/settings/sites/collect-mtender")
def sites_collect_mtender(request: Request):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    from engine import run_collector
    try:
        r = run_collector("mtender", request.state.store, request.state.conn)
    except Exception as ex:
        return _redir_sites(err=f"mtender: {ex}")
    if r.get("status") == "disabled":
        return _redir_sites(err="MTender API is off (turn it on first)")
    if r.get("status") == "error":
        return _redir_sites(err=f"mtender: {r.get('error')}")
    return _redir_sites(msg=f"MTender: {r.get('new', 0)} new of {r.get('fetched', 0)} fetched")


@router.post("/app/settings/sites/dedupe-mtender")
def sites_dedupe_mtender(request: Request):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    from workflows.analysis import dedupe_mtender
    n = dedupe_mtender(request.state.conn)
    return _redir_sites(msg=f"MTender dedupe: merged {n} duplicate stage-copy tender(s)")


@router.post("/app/settings/sites/dedupe-docs")
def sites_dedupe_docs(request: Request):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    from workflows.analysis import dedupe_documents_db
    r = dedupe_documents_db(request.state.conn)
    return _redir_sites(msg=f"Document dedupe: removed {r['documents_removed']} repeated "
                            f"file(s) across {r['tenders_changed']} tender(s)")

@router.post("/app/settings/sites/engine-toggle")
def sites_engine_toggle(request: Request):
    if request.state.readonly:
        return _redir_sites(err="read-only mode")
    store = request.state.store
    cfg = dict(store.get("sources.genericweb", {}) or {})
    cur = str(cfg.get("engine", "builtin")).lower()
    cfg["engine"] = "crawl4ai" if cur != "crawl4ai" else "builtin"
    store.set("sources.genericweb", cfg, actor="web", note="switch engine via web")
    msg = f"collection engine: {cfg['engine']}"
    if cfg["engine"] == "crawl4ai":
        try:
            from engine.crawl4ai_fetch import crawl4ai_available
            if not crawl4ai_available():
                return _redir_sites(msg=msg, err="crawl4ai is not installed yet — "
                                    "pip install crawl4ai in the venv")
        except Exception:
            pass
    return _redir_sites(msg=msg)
