from __future__ import annotations

import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from engine import user_settings
from web.render import _e
from web.user import cards
from web.user.counts import nav_counts
from web.user.icons import icon
from web.user.layout import render
from workflows import work
from workflows.segments import partition

router = APIRouter()

SELECT = (
    "SELECT t.id, t.source, t.external_id, t.normalized_json, t.origin, t.created_at, "
    "av.verdict av_verdict, av.score av_score, tv.verdict tv_verdict, "
    "s.margin, s.margin_partial, e.fields_json ex_fields "
    "FROM tenders t "
    "LEFT JOIN verdicts av ON av.tender_id=t.id AND av.stage_name='applicability' "
    "LEFT JOIN verdicts tv ON tv.tender_id=t.id AND tv.stage_name='triage' "
    "LEFT JOIN suppliers s ON s.tender_id=t.id "
    "LEFT JOIN extractions e ON e.tender_id=t.id "
    "WHERE (av.verdict IN ('can','partial') "
    "OR (av.verdict IS NULL AND tv.verdict='relevant'))")

MATCH_FILTERS = {
    "": "Any match",
    "can": "Full fit only",
    "can_partial": "Full and partial",
    "scored": "Scored only",
}


def _keep(row, q, match):
    if q:
        nj = cards.nj_of(row)
        hay = f"{nj.get('title') or ''} {nj.get('buyer') or ''} {row['external_id'] or ''}".lower()
        cpv = nj.get("cpv") or []
        if isinstance(cpv, list) and cpv and isinstance(cpv[0], dict):
            hay += " " + str(cpv[0].get("id") or "")
        if q.lower() not in hay:
            return False
    v = row["av_verdict"]
    if match == "can":
        return v == "can"
    if match == "can_partial":
        return v in ("can", "partial")
    if match == "scored":
        return bool(v)
    return True


def _filters(q, match):
    opts = "".join(
        f'<option value="{k}"{" selected" if k == match else ""}>{_e(v)}</option>'
        for k, v in MATCH_FILTERS.items())
    return ('<form method="get" action="/app/inbox" class="filters">'
            f'<div class="fh">{icon("filter")}Filters</div><div class="fb">'
            f'<input class="grow" type="text" name="q" value="{_e(q)}" '
            'placeholder="Title, buyer or CPV code">'
            f'<select name="match">{opts}</select>'
            '<button class="btn">Apply</button>'
            '<a class="btn ghost" href="/app/inbox">Clear</a>'
            "</div></form>")


@router.post("/app/inbox/{tender_id}/stage")
def inbox_stage(request: Request, tender_id: int, stage: str = Form("qualified"),
                back: str = Form("/app/inbox")):
    if request.state.store.get("web.read_only"):
        return RedirectResponse(back, status_code=303)
    try:
        work.set_stage(request.state.conn, tender_id, work.account_id(request), stage)
    except ValueError:
        pass
    return RedirectResponse(back if back.startswith("/app") else "/app/inbox", status_code=303)


@router.get("/app/inbox")
def inbox(request: Request, q: str = "", match: str = ""):
    conn, store = request.state.conn, request.state.store
    acct_id = work.account_id(request)
    portal = cards.portal_of(store)
    rows = conn.execute(SELECT + " LIMIT 3000").fetchall()
    buckets = partition(rows, user_settings.view(conn, store, acct_id))
    decided = work.decided_ids(conn, acct_id)
    fresh = [r for r in buckets["new"] if r["id"] not in decided]
    shown = [r for r in fresh if _keep(r, q, match)]
    now = time.time()

    if shown:
        body_rows = "".join(
            "<tr>" + cards.cell_ref(r) + cards.cell_tender(r, cards.nj_of(r), portal)
            + cards.cell_value(cards.nj_of(r)) + cards.cell_docs(cards.nj_of(r))
            + cards.cell_match(r) + cards.cell_when(r, cards.nj_of(r), now)
            + cards.cell_decide(r, request.url.path + ("?" + str(request.url.query)
                                                       if request.url.query else ""))
            + "</tr>" for r in shown)
        table = (
            '<div class="card"><table><thead><tr>'
            '<th style="width:150px">Reference</th><th>Tender</th>'
            '<th style="width:120px">Value</th><th style="width:170px">Documents</th>'
            '<th style="width:110px">Match</th><th style="width:130px">Deadline</th>'
            '<th style="width:90px">Decide</th>'
            f"</tr></thead><tbody>{body_rows}</tbody></table></div>")
    elif fresh:
        table = ('<div class="card"><div class="empty">Nothing matches this filter. '
                 f'{len(fresh)} new tender(s) are waiting behind it.</div></div>')
    else:
        table = ('<div class="card"><div class="empty">Inbox is clear. '
                 'Everything the daily check found has been decided.</div></div>')

    counts = nav_counts(conn, store, acct_id)
    lede = ("New finds from the daily check. Keep what is worth a bid — kept tenders "
            "move to Qualified. Skipped ones stop showing up here.")
    return render(request, "Tender inbox", _filters(q, match) + table,
                  heading="Tender inbox", heading_icon="inbox", lede=lede, counts=counts)
