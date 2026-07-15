from __future__ import annotations

import datetime as dt
import html
import json

from fastapi.responses import HTMLResponse

from web.config_meta import describe
from web.styles import CSS

NAV = [
    ("/", "Digest"),
    ("/results", "Results"),
    ("/tenders", "Tenders"),
    ("/stage/triage", "Triage"),
    ("/stage/extract", "Extract"),
    ("/stage/applicability", "Applicability"),
    ("/stage/suppliers", "Suppliers"),
    ("/analyze", "Analyze"),
    ("/sites", "Sites"),
    ("/schedule", "Schedule"),
    ("/user-settings", "User Settings"),
    ("/config", "Config"),
]


def source_url(source, external_id, portal=None):
    ext = str(external_id or "")
    if source == "mtender" and ext.startswith("ocds-"):
        tpl = portal or "https://mtender.gov.md/tenders/{ocid}"
        try:
            return tpl.format(ocid=ext)
        except Exception:
            return None
    return None


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
    acct = getattr(request.state, "account", None)
    if acct is not None:
        who = _e(acct["company"] or acct["login"])
        ro += (f' &middot; <span class="mut">{who}</span> '
               f'&middot; <a href="/logout">sign out</a>')
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{brand} &middot; {_e(title)}</title><style>{CSS}</style></head><body>"
        f"<header><span class=brand>{brand}</span><nav>{nav}</nav></header>"
        f"<main><h1>{_e(title)}{ro}</h1>{body}</main>"
        f"<footer>{brand} &middot; phase 8 web UI</footer></body></html>"
    )


def _accounts_mode(request):
    conn = getattr(request.state, "conn", None)
    if conn is None:
        return False
    try:
        from engine import accounts
        return accounts.count(conn) > 0
    except Exception:
        return False


def _login(request, error=""):
    msg = f'<div class="err">{_e(error)}</div>' if error else ""
    store = request.state.store
    brand = _e(store.get("web.title", "TenderEngine"))
    if _accounts_mode(request):
        fields = (f"<p class=mut>Sign in with your company account.</p>"
                  f"<input type=text name=login placeholder='login' autocapitalize=off "
                  f"autocorrect=off autofocus>"
                  f"<input type=password name=password placeholder='password' "
                  f"style='margin-top:8px'>")
    else:
        fields = (f"<p class=mut>Access protected by token.</p>"
                  f"<input type=password name=token placeholder='token' autofocus>")
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{brand} &middot; login</title><style>{CSS}</style></head><body>"
        f"<main style='max-width:380px;margin-top:12vh'>"
        f"<div class=card><h1>{brand}</h1>{msg}"
        f"<form method=post action='/login'>"
        f"{fields}"
        f"<div class=row style='margin-top:10px'><button>Sign in</button></div>"
        f"</form></div></main></body></html>",
        status_code=401,
    )
