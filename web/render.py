from __future__ import annotations

import datetime as dt
import html
import json

from fastapi.responses import HTMLResponse

from web.config_meta import describe
from web.styles import CSS

NAV = [
    ("/", "Digest"),
    ("/tenders", "Tenders"),
    ("/triage", "Triage"),
    ("/applicability", "Applicability"),
    ("/suppliers", "Suppliers"),
    ("/verifications", "Verifications"),
    ("/coverage", "Coverage"),
    ("/runs", "Runs"),
    ("/stages", "Stages"),
    ("/audit", "Audit"),
    ("/analyze", "Analyze"),
    ("/sites", "Sites"),
    ("/config", "Config"),
]


def _e(v):
    return html.escape("" if v is None else str(v))


def _ts(value):
    if not value:
        return "-"
    try:
        return dt.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)


def _vclass(v):
    return "v-" + str(v or "").lower().replace(" ", "_")


def _table(headers, rows):
    if not rows:
        return '<div class="card"><div class="empty">(empty)</div></div>'
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
    return f'<div class="card"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _loose(text):
    try:
        return json.loads(text) if text else {}
    except Exception:
        return {}


def _help(key):
    d = describe(key)
    return f'<span class="help" title="{_e(d)}">?</span>' if d else ""


def _vtype(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list) and value and all(
            isinstance(x, (str, int, float)) and not isinstance(x, bool) for x in value):
        return "list_num" if all(isinstance(x, (int, float)) for x in value) else "list_str"
    return "json"


def _control(key, value, vtype):
    if vtype == "bool":
        chk = "checked" if value else ""
        return (f'<label class="switch"><input type="checkbox" name="bval" {chk}>'
                f'<span class="slider"></span></label>')
    if vtype in ("int", "float"):
        step = "1" if vtype == "int" else "any"
        return (f'<input class="numfield" type="number" step="{step}" name="nval" '
                f'value="{_e(value)}">')
    if vtype == "str":
        if key.endswith("_prompt") or len(str(value)) > 110 or "\n" in str(value):
            return f'<textarea name="sval" spellcheck="false">{_e(value)}</textarea>'
        return f'<input type="text" name="sval" value="{_e(value)}">'
    if vtype in ("list_str", "list_num"):
        joined = ", ".join(str(x) for x in value)
        return (f'<input type="text" name="lval" value="{_e(joined)}">'
                f'<p class="hint">comma-separated list</p>')
    pretty = json.dumps(value, ensure_ascii=False, indent=2)
    return (f'<textarea name="jval" spellcheck="false">{_e(pretty)}</textarea>'
            f'<p class="hint">structured value — edit as JSON</p>')


def _bool_dot(value):
    return (f'<span class="dot {"on" if value else "off"}"></span>'
            f'{"on" if value else "off"}')


def _layout(request, title, body):
    store = request.state.store
    brand = _e(store.get("web.title", "TenderEngine"))
    path = request.url.path
    nav = "".join(
        f'<a class="{"on" if href == path else ""}" href="{href}">{_e(label)}</a>'
        for href, label in NAV
    )
    ro = ' &middot; <span class="chip">read-only</span>' if request.state.readonly else ""
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{brand} &middot; {_e(title)}</title><style>{CSS}</style></head><body>"
        f"<header><span class=brand>{brand}</span><nav>{nav}</nav></header>"
        f"<main><h1>{_e(title)}{ro}</h1>{body}</main>"
        f"<footer>{brand} &middot; phase 8 web UI</footer></body></html>"
    )


def _login(request, error=""):
    msg = f'<div class="err">{_e(error)}</div>' if error else ""
    store = request.state.store
    brand = _e(store.get("web.title", "TenderEngine"))
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{brand} &middot; login</title><style>{CSS}</style></head><body>"
        f"<main style='max-width:380px;margin-top:12vh'>"
        f"<div class=card><h1>{brand}</h1>{msg}"
        f"<form method=post action='/login'>"
        f"<p class=mut>Access protected by token.</p>"
        f"<input type=password name=token placeholder='token' autofocus>"
        f"<div class=row style='margin-top:10px'><button>Sign in</button></div>"
        f"</form></div></main></body></html>",
        status_code=401,
    )
