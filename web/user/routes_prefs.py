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


def _field(key, meta, value, overridden):
    tag = ('<span class="chip acc">yours</span>' if overridden
           else '<span class="chip plain">default</span>')
    return ('<div class="pref">'
            f'<div class="pref-h"><label for="{key}">{_e(meta["label"])}</label>{tag}</div>'
            '<div class="pref-b">'
            f'<input id="{key}" class="note-in" type="number" name="{key}" value="{_e(value)}" '
            f'min="{meta["min"]}" max="{meta["max"]}" style="max-width:110px">'
            f'<span class="mut">{_e(meta["unit"])}</span></div>'
            f'<div class="pref-help">{_e(meta["help"])}</div></div>')


@router.post("/app/preferences")
async def prefs_save(request: Request):
    conn, store = request.state.conn, request.state.store
    acct_id = work.account_id(request)
    form = await request.form()
    if store.get("web.read_only") or not acct_id:
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
    values = user_settings.effective(conn, store, acct_id)
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
                  '<div class="tx"><b>Saved</b><span>Your lists already use the new '
                  "numbers.</span></div></div></div>")

    if not acct_id:
        form = ('<div class="card"><div class="empty">This install still runs on the shared '
                "token, so there is no account to attach preferences to. Create an account and "
                "sign in with it.</div></div>")
    else:
        fields = "".join(_field(k, m, values[k], k in mine) for k, m in user_settings.KEYS.items())
        form = ('<form method="post" action="/app/preferences" class="card">'
                f'<div class="card-h">{icon("sliders")}<h2>What you see</h2></div>'
                f'<div class="card-b">{fields}</div>'
                '<div class="fb" style="border-top:1px solid var(--line);gap:8px">'
                '<button class="btn">Save</button>'
                '<button class="btn ghost" name="reset" value="1">Reset to defaults</button>'
                "</div></form>")

    shared = ('<div class="card"><div class="card-h">'
              f'{icon("shield")}<h2>Set for everyone, not for you</h2></div>'
              '<div class="card-b">'
              '<p class="mut" style="margin:0 0 10px;line-height:1.6">These decide which tenders '
              'reach you at all, and they are shared across the whole installation:</p>'
              '<div class="t-tags" style="margin-bottom:12px">'
              '<span class="chip">Keywords</span><span class="chip">Capability profile</span>'
              '<span class="chip">Supplier catalog</span><span class="chip">Sources</span>'
              '<span class="chip">Schedule</span></div>'
              '<p class="mut" style="margin:0;line-height:1.6">They cannot be yours alone yet. '
              'The engine scores every tender once, against one capability profile — so a second '
              'company would read an answer computed for the first. Splitting that means scoring '
              'each tender per company, which costs real money per company. Until that is '
              'decided, these stay with whoever administers TenderEngine.</p>'
              "</div></div>")

    body = banner + '<div class="two">' + form + "<div>" + shared + "</div></div>"
    return render(request, "Preferences", body, heading="Preferences", heading_icon="sliders",
                  lede="Settings that belong to your company account.",
                  counts=nav_counts(conn, store, acct_id))
