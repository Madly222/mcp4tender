from __future__ import annotations

from fastapi.responses import HTMLResponse

from web.assets import asset_version
from web.render import _e
from web.user.icons import icon
from web.user.nav import NAV, is_on

SHEETS = ("tokens.css", "user/base.css", "user/components.css")


def _theme(request):
    from engine import user_settings
    return user_settings.theme_of(request)


def _initials(text):
    parts = [p for p in str(text or "").split() if p]
    if not parts:
        return "TE"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _links():
    return "".join(
        f'<link rel="stylesheet" href="/static/{s}?v={asset_version(s)}">' for s in SHEETS)


def _nav(path, query, counts):
    out = []
    for group, items in NAV:
        out.append(f'<div class="grp">{_e(group)}</div>')
        for it in items:
            on = " on" if is_on(it["href"], path, query) else ""
            badge = ""
            key = it.get("count")
            if key and counts.get(key):
                badge = f'<span class="badge num">{_e(counts[key])}</span>'
            out.append(f'<a class="item{on}" href="{_e(it["href"])}">'
                       f'{icon(it.get("icon", "info"))}{_e(it["label"])}{badge}</a>')
            if it.get("sub"):
                sub = []
                for s in it["sub"]:
                    son = " on" if is_on(s["href"], path, query) else ""
                    n = counts.get(s.get("count"))
                    ntxt = f'<span class="n num">{_e(n)}</span>' if n is not None else ""
                    sub.append(f'<a class="{son.strip()}" href="{_e(s["href"])}">'
                               f'{_e(s["label"])}{ntxt}</a>')
                out.append('<div class="sub">' + "".join(sub) + "</div>")
    return "".join(out)


def _admin_link(request):
    from engine import accounts
    acct = getattr(request.state, "account", None)
    if acct is not None and not accounts.is_admin(acct):
        return ""
    return ('<div class="side-foot">'
            f'<a class="adm" href="/">{icon("shield")}Engine admin</a></div>')


def _who(request):
    acct = getattr(request.state, "account", None)
    from engine import accounts
    name = (acct["company"] or acct["login"]) if acct else "TenderEngine"
    role = "Token access"
    if acct is not None:
        role = "Administrator" if accounts.is_admin(acct) else "Company account"
    return (f'<div class="who"><div class="av">{_e(_initials(name))}</div>'
            f'<div class="nm">{_e(name)}<small>{_e(role)}</small></div></div>')


def render(request, title, body, lede="", heading=None, heading_icon=None,
           actions="", counts=None, head_extra=""):
    store = request.state.store
    brand = _e(store.get("web.title", "TenderEngine"))
    acct = getattr(request.state, "account", None)
    company = _e(acct["company"] or acct["login"]) if acct else brand
    counts = counts or {}
    head = ""
    if heading is not None:
        ic = icon(heading_icon) if heading_icon else ""
        led = f'<p class="lede">{_e(lede)}</p>' if lede else ""
        if actions:
            head = (f'<div class="head-row"><div><h1>{ic}{_e(heading)}</h1>{led}</div>'
                    f'<div class="spacer"></div>{actions}</div>')
        else:
            head = f"<h1>{ic}{_e(heading)}</h1>{led}"
    return HTMLResponse(
        f'<!doctype html><html lang=en data-theme="{_theme(request)}">'
        "<head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{brand} &middot; {_e(title)}</title>{_links()}{head_extra}</head><body>"
        '<input type="checkbox" id="navtoggle" class="nav-toggle" aria-label="Menu">'
        '<div class="shell">'
        '<label for="navtoggle" class="nav-scrim"></label><aside>'
        f'<div class="brand"><div class="mark">{_e(_initials(company))}</div>'
        f'<div class="co">{company}<small>{brand}</small></div></div>'
        f'<nav>{_nav(request.url.path, str(request.url.query or ""), counts)}</nav>'
        f'{_admin_link(request)}</aside><div class="col"><header>'
        f'<label for="navtoggle" class="nav-btn">{icon("menu")}</label>'
        '<div class="title">Tender Management<small>Powered by AI analysis</small></div>'
        f'<div class="spacer"></div>{_who(request)}'
        '<a class="btn ghost sm" href="/logout">Sign out</a>'
        f'</header><main>{head}{body}</main></div></div></body></html>')
