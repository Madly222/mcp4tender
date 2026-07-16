from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from engine import user_settings
from web.render import _e
from web.user.counts import nav_counts
from web.user.icons import icon
from web.user.layout import render
from workflows import work

router = APIRouter()


def _choices(key, meta, current, mine):
    tag = ('<span class="chip acc">yours</span>' if key in mine
           else '<span class="chip plain">default</span>')
    opts = "".join(
        f'<label class="pick"><input type="radio" name="{key}" value="{c}"'
        f'{" checked" if c == current else ""}><span>{_e(label)}</span></label>'
        for c, label in meta["choices"])
    return ('<div class="pref">'
            f'<div class="pref-h"><label>{_e(meta["label"])}</label>{tag}</div>'
            f'<div class="pref-b" style="display:block"><div class="picks">{opts}</div></div>'
            f'<div class="pref-help">{_e(meta["help"])}</div></div>')


@router.post("/app/preferences")
async def prefs_save(request: Request):
    conn = request.state.conn
    acct_id = work.account_id(request)
    form = await request.form()
    if not acct_id:
        return RedirectResponse("/app/preferences", status_code=303)
    if form.get("reset"):
        user_settings.reset(conn, acct_id)
        return RedirectResponse("/app/preferences?saved=1", status_code=303)
    try:
        user_settings.set_many(conn, acct_id, {k: form.get(k) for k in user_settings.KEYS
                                               if form.get(k) is not None})
    except ValueError as e:
        return RedirectResponse(f"/app/preferences?error={_e(str(e))}", status_code=303)
    return RedirectResponse("/app/preferences?saved=1", status_code=303)


@router.get("/app/preferences")
def prefs(request: Request, saved: str = "", error: str = ""):
    conn, store = request.state.conn, request.state.store
    acct_id = work.account_id(request)
    values = user_settings.effective(conn, acct_id)
    mine = user_settings.raw(conn, acct_id)

    banner = ""
    if error:
        banner = ('<div class="strips" style="grid-template-columns:1fr">'
                  f'<div class="strip bad"><div class="ic">{icon("bang", 3)}</div>'
                  f'<div class="tx"><b>Not saved</b><span>{_e(error)}</span></div></div></div>')
    elif saved:
        banner = ('<div class="strips" style="grid-template-columns:1fr">'
                  '<div class="strip" style="background:var(--ok-weak);'
                  'border:1px solid var(--ok-line)">'
                  f'<div class="ic" style="background:var(--ok)">{icon("check", 3)}</div>'
                  '<div class="tx"><b>Saved</b><span>Applied right away.</span></div></div></div>')

    if not acct_id:
        form = ('<div class="card"><div class="empty">This install still runs on the shared '
                "token, so there is no account to attach preferences to.</div></div>")
    else:
        fields = "".join(_choices(k, m, values[k], mine) for k, m in user_settings.KEYS.items())
        form = ('<form method="post" action="/app/preferences" class="card">'
                f'<div class="card-h">{icon("sliders")}<h2>How it looks to you</h2></div>'
                f'<div class="card-b">{fields}</div>'
                '<div class="fb" style="border-top:1px solid var(--line);gap:8px">'
                '<button class="btn">Save</button>'
                '<button class="btn ghost" name="reset" value="1">Reset</button>'
                "</div></form>")

    aside = ('<div class="card"><div class="card-h">'
             f'{icon("gear")}<h2>Looking for the engine?</h2></div><div class="card-b">'
             '<p class="mut" style="margin:0 0 12px;line-height:1.6">This page is only about how '
             'the app looks on your screen. Anything that changes which tenders you get, how they '
             'are scored, when they are collected or what they cost lives in '
             '<a href="/app/settings">Company settings</a> — those are shared with everyone at '
             'your company.</p>'
             '<a class="btn ghost" href="/app/settings">Company settings</a>'
             "</div></div>")

    body = banner + '<div class="two">' + form + "<div>" + aside + "</div></div>"
    return render(request, "Preferences", body, heading="Preferences", heading_icon="sliders",
                  lede="Yours alone — nobody else at your company sees these.",
                  counts=nav_counts(conn, store, acct_id))
