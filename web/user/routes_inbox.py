from __future__ import annotations

import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from web.render import _e
from web.user import cards, lifecycle
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

ORDER = " ORDER BY t.created_at DESC, t.id DESC"

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


def _filters(q, match, sort="new"):
    opts = "".join(
        f'<option value="{k}"{" selected" if k == match else ""}>{_e(v)}</option>'
        for k, v in MATCH_FILTERS.items())
    sorts = {"new": "Newest", "deadline": "By deadline"}
    sopts = "".join(
        f'<option value="{k}"{" selected" if k == sort else ""}>{_e(v)}</option>'
        for k, v in sorts.items())
    return ('<form method="get" action="/app/inbox" class="filters">'
            f'<div class="fh">{icon("filter")}Filters</div><div class="fb">'
            f'<input class="grow" type="text" name="q" value="{_e(q)}" '
            'placeholder="Title, buyer or CPV code">'
            f'<select name="match">{opts}</select>'
            f'<select name="sort">{sopts}</select>'
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


@router.post("/app/inbox/sweep")
def inbox_sweep(request: Request):
    conn, store = request.state.conn, request.state.store
    if store.get("web.read_only"):
        return RedirectResponse("/app/inbox", status_code=303)
    acct_id = work.account_id(request)
    rows = conn.execute(SELECT + ORDER + " LIMIT 3000").fetchall()
    _kept, closed_ids, _waiting = lifecycle.split(partition(rows, store)["new"], store,
                                                 work.decided_ids(conn, acct_id))
    for tid in closed_ids:
        work.set_stage(conn, tid, acct_id, "skipped", note="bidding closed")
    return RedirectResponse(f"/app/inbox?swept={len(closed_ids)}", status_code=303)


@router.get("/app/inbox")
def inbox(request: Request, q: str = "", match: str = "", swept: str = "", sort: str = "new"):
    conn, store = request.state.conn, request.state.store
    acct_id = work.account_id(request)
    portal = cards.portal_of(store)
    rows = conn.execute(SELECT + ORDER + " LIMIT 3000").fetchall()
    buckets = partition(rows, store)
    decided = work.decided_ids(conn, acct_id)
    fresh, closed_ids, _waiting = lifecycle.split(buckets["new"], store, decided)
    hidden = len(closed_ids)
    shown = [(r, st) for r, st in fresh if _keep(r, q, match)]
    if sort == "deadline":
        def _dl_key(item):
            ts = cards.deadline_ts(item[0], cards.nj_of(item[0]))
            return (ts is None, ts or 0)
        shown = sorted(shown, key=_dl_key)
    now = time.time()

    if shown:
        back = request.url.path + ("?" + str(request.url.query)
                                   if request.url.query else "")
        body_rows = "".join(
            "<tr>" + cards.cell_ref(r) + cards.cell_tender(r, cards.nj_of(r), portal,
                                                          extra=lifecycle.chip(st, cards.nj_of(r)))
            + cards.cell_value(cards.nj_of(r)) + cards.cell_docs(cards.nj_of(r))
            + cards.cell_match(r) + cards.cell_when(r, cards.nj_of(r), now)
            + cards.cell_decide(r, back)
            + "</tr>" for r, st in shown)
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

    note = ""
    if swept:
        note = ('<div class="note" style="margin:0 0 12px;border-color:var(--ok-line);'
                f'background:var(--ok-weak)">{icon("check")}'
                f'<span>{_e(swept)} closed tender(s) moved to Skipped. They are listed under '
                '<a href="/app/qualified?stage=skipped">Skipped</a> if you need them back.'
                '</span></div>')
    if hidden:
        note = ('<form method="post" action="/app/inbox/sweep" class="note sweep" '
                'style="margin:0 0 12px">'
                f'{icon("info")}<span>{hidden} tender(s) hidden — bidding has closed on them. '
                'They stay in <a href="/app/search">Search</a>.</span>'
                '<button class="btn ghost sm">Skip them for good</button></form>')

    counts = nav_counts(conn, store, acct_id)
    lede = ("Soonest deadline first; tenders with no deadline (N/A) are listed last. "
            "Only tenders you can still bid on are shown."
            if sort == "deadline" else
            "New finds from the daily check, newest first. Only tenders you can still bid on "
            "are listed. Keep what is worth a bid — kept tenders move to Qualified.")
    return render(request, "Tender inbox", _filters(q, match, sort) + note + table,
                  heading="Tender inbox", heading_icon="inbox", lede=lede, counts=counts)
