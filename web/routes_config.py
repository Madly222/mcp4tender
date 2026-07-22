from __future__ import annotations

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web import context
from web.config_meta import describe
from web.render import (_bool_dot, _control, _e, _help, _layout, _table, _ts,
                        _vtype)
from web.styles import CSS

router = APIRouter()


@router.get("/config")
def config_list(request: Request, msg: str = "", err: str = ""):
    store = request.state.store
    ro = request.state.readonly
    items = [(k, v) for k, v in sorted(store.all().items()) if k != "sources.rank"]
    banner = ""
    if msg:
        banner += f'<div class="ok">{_e(msg)}</div>'
    if err:
        banner += f'<div class="err">{_e(err)}</div>'
    if ro:
        banner += ('<div class="ok">read-only mode — editing is disabled '
                   '(web.read_only = true)</div>')
    if not ro and store.get("web.allow_restart", True):
        banner += (
            '<div class="card"><div class="row">'
            '<form method=post action="/admin/restart" style="margin:0" '
            'onsubmit="return confirm(\'Restart the service now? '
            'The page will reconnect in a few seconds.\')">'
            '<button class="ghost">⟳ Restart service</button></form>'
            '<span class="mut">Needed after deploying new code (a new archive). '
            'Editing settings here applies instantly and needs no restart.</span>'
            '</div></div>')
    if not ro:
        n = request.state.conn.execute("SELECT COUNT(*) c FROM tenders").fetchone()["c"]
        banner += (
            '<div class="card"><div class="row">'
            '<form method=post action="/admin/wipe-all" style="margin:0" '
            'onsubmit="return confirm(\'Delete ALL collected tenders and their analysis, '
            'and reset every crawl position? This cannot be undone.\')">'
            '<button class="ghost danger">⌫ Wipe all tenders</button></form>'
            f'<span class="mut">Empties the tender base ({n} now) across every source and '
            'resets crawl cursors, so the next run collects from scratch. Sites, settings '
            'and your keywords are kept.</span>'
            '</div></div>')
    rows = []
    for key, value in items:
        vtype = _vtype(value)
        if vtype == "bool":
            if ro:
                valcell = _bool_dot(value)
            elif value:
                valcell = (f'<form method=post action="/config/save" style="margin:0">'
                           f'<input type=hidden name=key value="{_e(key)}">'
                           f'<input type=hidden name=vtype value="bool">'
                           f'<button class="ghost"><span class="dot on"></span>on</button>'
                           f'</form>')
            else:
                valcell = (f'<form method=post action="/config/save" style="margin:0">'
                           f'<input type=hidden name=key value="{_e(key)}">'
                           f'<input type=hidden name=vtype value="bool">'
                           f'<input type=hidden name=bval value="1">'
                           f'<button class="ghost"><span class="dot off"></span>off</button>'
                           f'</form>')
        else:
            preview = json.dumps(value, ensure_ascii=False)
            if len(preview) > 90:
                preview = preview[:90] + "…"
            valcell = f'<span class="mono mut">{_e(preview)}</span>'
        rows.append([
            f'<a href="/config/item?key={_e(key)}">{_e(key)}</a>{_help(key)}',
            valcell,
        ])
    return _layout(request, f"Config ({len(items)})", banner + _table(["Key", "Value"], rows))


@router.get("/config/item")
def config_item(request: Request, key: str, saved: int = 0, err: str = ""):
    store = request.state.store
    all_cfg = store.all()
    if key not in all_cfg:
        return _layout(request, "Config", '<div class="card"><div class="empty">key not found</div></div>')
    value = all_cfg[key]
    vtype = _vtype(value)
    history = store.history(key)
    msg = ""
    if saved:
        msg = '<div class="ok">saved — new version active, hot-reload propagated.</div>'
    if err:
        msg = f'<div class="err">{_e(err)}</div>'
    desc = describe(key)
    ro = request.state.readonly
    if ro:
        pretty = json.dumps(value, ensure_ascii=False, indent=2)
        editor = f'<div class="card"><pre class="mono">{_e(pretty)}</pre></div>'
    else:
        control = _control(key, value, vtype)
        editor = (
            f'<form method=post action="/config/save"><div class="card">'
            f'<input type=hidden name=key value="{_e(key)}">'
            f'<input type=hidden name=vtype value="{vtype}">'
            f'{control}'
            f'<div class=row style="margin-top:12px">'
            f'<input type=text name=note placeholder="note (optional)" style="max-width:320px">'
            f'<button>Save</button>'
            f'<a class=mut href="/config">cancel</a></div></div></form>'
        )
    descbox = f'<p class="hint" style="margin-bottom:10px">{_e(desc)}</p>' if desc else ""
    hrows = []
    for h in history:
        actions = ""
        if not ro and not h["active"]:
            actions = (f'<form method=post action="/config/rollback" style="margin:0">'
                       f'<input type=hidden name=key value="{_e(key)}">'
                       f'<input type=hidden name=version value="{_e(h["version"])}">'
                       f'<button class=ghost>rollback</button></form>')
        hrows.append([
            ("<b>v" + _e(h["version"]) + "</b>") if h["active"] else ("v" + _e(h["version"])),
            '<span class="chip v-ok">active</span>' if h["active"] else "",
            _e(h["actor"]), _e(h["note"]), _ts(h["created_at"]), actions,
        ])
    body = (f'<p><a href="/config">&larr; all settings</a></p>{msg}'
            f'<h2>{_e(key)}{_help(key)}</h2>{descbox}{editor}'
            f'<h2>History &amp; rollback</h2>'
            + _table(["Ver", "", "Actor", "Note", "When", ""], hrows))
    return _layout(request, "Config", body)


@router.post("/config/save")
def config_save(request: Request, key: str = Form(...), vtype: str = Form("json"),
                bval: str = Form(None), nval: str = Form(None), sval: str = Form(None),
                lval: str = Form(None), jval: str = Form(None), note: str = Form("")):
    from urllib.parse import quote
    if request.state.readonly:
        return RedirectResponse("/config?err=" + quote("read-only mode"), status_code=303)
    try:
        if vtype == "bool":
            parsed = bval is not None
        elif vtype == "int":
            parsed = int(float(nval))
        elif vtype == "float":
            parsed = float(nval)
        elif vtype == "str":
            parsed = sval if sval is not None else ""
        elif vtype == "list_str":
            parsed = [s.strip() for s in (lval or "").split(",") if s.strip()]
        elif vtype == "list_num":
            parsed = [float(s) if "." in s else int(s)
                      for s in (s.strip() for s in (lval or "").split(",")) if s]
        else:
            parsed = json.loads(jval or "null")
    except Exception as ex:
        return RedirectResponse(
            f"/config/item?key={quote(key)}&err={quote('invalid value: ' + str(ex))}",
            status_code=303)
    request.state.store.set(key, parsed, actor="web", note=note or "edit via web")
    if vtype == "bool":
        return RedirectResponse("/config?msg=" + quote("updated " + key), status_code=303)
    return RedirectResponse(f"/config/item?key={quote(key)}&saved=1", status_code=303)


@router.post("/config/rollback")
def config_rollback(request: Request, key: str = Form(...), version: int = Form(...)):
    if request.state.readonly:
        return _layout(request, "Config", '<div class="err">read-only mode</div>')
    from urllib.parse import quote
    try:
        request.state.store.rollback(key, version, actor="web")
    except KeyError as ex:
        return RedirectResponse(f"/config/item?key={quote(key)}&err={quote(str(ex))}",
                                status_code=303)
    return RedirectResponse(f"/config/item?key={quote(key)}&saved=1", status_code=303)


@router.post("/admin/wipe-all")
def admin_wipe_all(request: Request):
    from urllib.parse import quote
    if request.state.readonly:
        return RedirectResponse("/config?err=" + quote("read-only mode"), status_code=303)
    from workflows.analysis import wipe_all
    n = wipe_all(request.state.conn)
    return RedirectResponse(
        "/config?msg=" + quote(f"wiped {n} tender(s); crawl cursors reset"), status_code=303)


@router.post("/admin/restart")
def admin_restart(request: Request):
    from urllib.parse import quote
    store = request.state.store
    if request.state.readonly:
        return RedirectResponse("/config?err=" + quote("read-only mode"), status_code=303)
    if not store.get("web.allow_restart", True):
        return RedirectResponse(
            "/config?err=" + quote("restart is disabled (web.allow_restart=false)"),
            status_code=303)
    context._schedule_restart()
    title = _e(store.get("web.title", "TenderEngine"))
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset=utf-8>"
        f"<meta http-equiv=refresh content='6;url=/'>"
        f"<title>{title} &middot; restarting</title><style>{CSS}</style></head><body>"
        f"<main style='max-width:480px;margin-top:14vh'><div class=card>"
        f"<h1>Restarting…</h1>"
        f"<p class=mut>The service is restarting; this page will reconnect "
        f"automatically in a few seconds. If it does not, <a href='/'>click here</a>.</p>"
        f"<p class=hint>If the service is not managed by systemd it will not come back "
        f"on its own — start it manually.</p>"
        f"</div></main></body></html>")
