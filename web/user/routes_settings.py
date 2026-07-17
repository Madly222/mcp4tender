from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from web.config_meta import CONFIG_META
from web import settings_ops
from web.render import _e
from web.user.counts import nav_counts
from web.user.icons import icon
from web.user import dictforms
from web.user.labels import label_of
from web.user.forms import FORMS, HANDLED
from web.user.layout import render
from web.user.settings_meta import (BY_ID, SECTIONS, keys_in, parse, section_of, vtype_of)
from workflows import work

router = APIRouter()


def _editor(key, value, vtype):
    if vtype == "bool":
        on = " checked" if value else ""
        return (f'<label class="switch"><input type="checkbox" name="v"{on}>'
                f'<span>{"On" if value else "Off"}</span></label>')
    if vtype in ("int", "float"):
        step = "1" if vtype == "int" else "any"
        return (f'<input class="note-in" type="number" step="{step}" name="v" '
                f'value="{_e(value)}" style="max-width:180px">')
    if vtype == "str":
        if len(str(value)) > 90:
            return f'<textarea class="note-in ta" name="v" rows="4">{_e(value)}</textarea>'
        return f'<input class="note-in" type="text" name="v" value="{_e(value)}">'
    if vtype == "list_str":
        return (f'<input class="note-in" type="text" name="v" value="{_e(", ".join(value))}">'
                '<div class="pref-help">Comma separated.</div>')
    pretty = json.dumps(value, indent=2, ensure_ascii=False)
    rows = min(24, max(4, pretty.count("\n") + 2))
    return f'<textarea class="note-in ta" name="v" rows="{rows}">{_e(pretty)}</textarea>'


def _row(key, value, back):
    vtype = vtype_of(value)
    desc = CONFIG_META.get(key, "")
    return ('<form method="post" action="/app/settings/save" class="pref">'
            f'<div class="pref-h"><label>{_e(label_of(key))}</label></div>'
            + (f'<div class="pref-help" style="margin:0 0 9px">{_e(desc)}</div>' if desc else "")
            + f'<div class="pref-b" style="display:block">{_editor(key, value, vtype)}</div>'
            f'<div class="keyname" title="the setting\'s name in the engine">{_e(key)}</div>'
            f'<input type="hidden" name="key" value="{_e(key)}">'
            f'<input type="hidden" name="vtype" value="{vtype}">'
            f'<input type="hidden" name="back" value="{_e(back)}">'
            '<div style="margin-top:9px"><button class="btn sm">Save</button></div>'
            "</form>")


@router.post("/app/settings/save")
async def settings_save(request: Request):
    form = await request.form()
    key = str(form.get("key") or "")
    back = str(form.get("back") or "/app/settings")
    if not back.startswith("/app/settings"):
        back = "/app/settings"
    sid = section_of(key)
    if not sid:
        return RedirectResponse("/app/settings", status_code=303)
    if request.state.store.get("web.read_only"):
        return RedirectResponse(f"{back}?err={quote('read-only mode is on')}", status_code=303)
    try:
        value = parse(str(form.get("vtype") or "json"), form.get("v"))
    except Exception as ex:
        return RedirectResponse(f"{back}?err={quote(f'{key}: {ex}')}", status_code=303)
    request.state.store.set(key, value, actor="app", note="edit via user settings")
    return RedirectResponse(f"{back}?saved={quote(key)}", status_code=303)


@router.get("/app/settings")
def settings_hub(request: Request):
    conn, store = request.state.conn, request.state.store
    cards = []
    for sid, label, ic, blurb, _prefixes in SECTIONS:
        n = len(keys_in(store, sid))
        if not n:
            continue
        cards.append(f'<a class="sect" href="/app/settings/{sid}">'
                     f'<div class="sect-i">{icon(ic)}</div>'
                     f'<div class="sect-t"><b>{_e(label)}</b><span>{_e(blurb)}</span></div>'
                     f'<span class="chip num">{n}</span></a>')
    note = ('<div class="card"><div class="card-h">'
            f'{icon("shield")}<h2>Not here on purpose</h2></div><div class="card-b">'
            '<p class="mut" style="margin:0;line-height:1.6">How this instance is served — port, '
            'host, access token, read-only mode, whether the scheduler runs — stays with whoever '
            'administers TenderEngine. Those are not settings about your tenders; changing them '
            'from in here would cut off the branch you are sitting on.</p></div></div>')
    body = f'<div class="sects">{"".join(cards)}</div><div class="gap"></div>{note}'
    return render(request, "Settings", body, heading="Company settings", heading_icon="gear",
                  lede="Everything the engine uses to work for your company.",
                  counts=nav_counts(conn, store, work.account_id(request)))


@router.get("/app/settings/{section_id}")
def settings_section(request: Request, section_id: str, saved: str = "", err: str = ""):
    conn, store = request.state.conn, request.state.store
    sect = BY_ID.get(section_id)
    if not sect:
        return RedirectResponse("/app/settings", status_code=303)
    _sid, label, ic, blurb, _prefixes = sect
    keys = keys_in(store, section_id)
    back = f"/app/settings/{section_id}"

    banner = ""
    if err:
        banner = ('<div class="strips" style="grid-template-columns:1fr">'
                  f'<div class="strip bad"><div class="ic">{icon("bang", 3)}</div>'
                  f'<div class="tx"><b>Not saved</b><span>{_e(err)}</span></div></div></div>')
    elif saved:
        banner = ('<div class="strips" style="grid-template-columns:1fr">'
                  '<div class="strip" style="background:var(--ok-weak);'
                  'border:1px solid var(--ok-line)">'
                  f'<div class="ic" style="background:var(--ok)">{icon("check", 3)}</div>'
                  f'<div class="tx"><b>Saved</b><span>{_e(label_of(saved) if "." in saved else saved)}'
                  " — the engine picks it up on its next run.</span></div></div></div>")

    friendly = ""
    if section_id in FORMS:
        friendly = FORMS[section_id](store, request) + '<div class="gap"></div>'
        keys = [k for k in keys if k not in HANDLED.get(section_id, ())]
    for k in dictforms.keys_for(section_id):
        if k in keys:
            friendly += dictforms.form_for(store, k) + '<div class="gap"></div>'
            keys = [x for x in keys if x != k]

    if keys:
        rows = "".join(_row(k, store.get(k), back) for k in keys)
        more = ('<div class="card"><div class="card-h">'
                f'{icon("sliders")}<h2>Everything else here</h2></div>'
                f'<div class="card-b">{rows}</div></div>') if friendly else \
            f'<div class="card"><div class="card-b">{rows}</div></div>'
        inner = friendly + more
    elif friendly:
        inner = friendly
    else:
        inner = '<div class="card"><div class="empty">Nothing configurable here.</div></div>'

    crumb = f'<a class="btn ghost sm" href="/app/settings">All settings</a>'
    return render(request, label, banner + inner, heading=label, heading_icon=ic, lede=blurb,
                  actions=crumb, counts=nav_counts(conn, store, work.account_id(request)))


def _back(section_id, msg="", err=""):
    q = ""
    if msg:
        q = "?saved=" + quote(msg)
    elif err:
        q = "?err=" + quote(err)
    return RedirectResponse(f"/app/settings/{section_id}{q}", status_code=303)


def _guard(request, section_id):
    if request.state.store.get("web.read_only"):
        return _back(section_id, err="read-only mode is on")
    return None


@router.post("/app/settings/company/save")
async def company_save(request: Request):
    stop = _guard(request, "company")
    if stop:
        return stop
    form = await request.form()
    return _back("company", msg=settings_ops.save_company(form, request.state.store, actor="app"))


@router.post("/app/settings/keywords/save")
async def keywords_save(request: Request):
    stop = _guard(request, "relevance")
    if stop:
        return stop
    form = await request.form()
    try:
        return _back("relevance",
                     msg=settings_ops.save_keywords(form, request.state.store, actor="app"))
    except settings_ops.SettingsError as ex:
        return _back("relevance", err=str(ex))


@router.post("/app/settings/apikey/save")
async def apikey_save(request: Request):
    stop = _guard(request, "ai")
    if stop:
        return stop
    form = await request.form()
    try:
        return _back("ai", msg=settings_ops.save_apikey(form))
    except settings_ops.SettingsError as ex:
        return _back("ai", err=str(ex))


@router.post("/app/settings/apikey/test")
async def apikey_test(request: Request):
    stop = _guard(request, "ai")
    if stop:
        return stop
    form = await request.form()
    try:
        return _back("ai", msg=settings_ops.run_key_test(form, request.state.store, actor="app"))
    except settings_ops.SettingsError as ex:
        return _back("ai", err=str(ex))


@router.post("/app/settings/schedule/save")
async def schedule_save(request: Request):
    stop = _guard(request, "schedule")
    if stop:
        return stop
    form = await request.form()
    return _back("schedule",
                 msg=settings_ops.save_schedule(form, request.state.store, actor="app"))


@router.post("/app/settings/catalog/save")
async def catalog_save(request: Request):
    stop = _guard(request, "suppliers")
    if stop:
        return stop
    form = await request.form()
    return _back("suppliers",
                 msg=settings_ops.save_catalog(form, request.state.store, actor="app"))


@router.post("/app/settings/kv/save")
async def kv_save(request: Request):
    form = await request.form()
    key = str(form.get("key") or "")
    spec = dictforms.SPECS.get(key)
    sid = section_of(key)
    if not spec or not sid:
        return RedirectResponse("/app/settings", status_code=303)
    stop = _guard(request, sid)
    if stop:
        return stop
    try:
        if spec["kind"] == "pairs":
            msg = settings_ops.save_pairs(form, request.state.store, key,
                                          bool(spec.get("num")), actor="app")
        elif spec["kind"] == "table":
            msg = settings_ops.save_table(form, request.state.store, key,
                                          [c for c, _l in spec["cols"]], actor="app")
        else:
            msg = settings_ops.save_fields(form, request.state.store, key, actor="app")
    except settings_ops.SettingsError as ex:
        return _back(sid, err=str(ex))
    return _back(sid, msg=msg)
