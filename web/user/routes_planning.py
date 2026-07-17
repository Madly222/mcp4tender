from __future__ import annotations

import time

from fastapi import APIRouter, Request

from web.user import cards, lifecycle
from web.user.counts import _RELEVANT, nav_counts
from web.user.icons import icon
from web.user.layout import render
from workflows import work
from workflows.segments import partition

router = APIRouter()


@router.get("/app/planning")
def planning(request: Request):
    conn, store = request.state.conn, request.state.store
    acct_id = work.account_id(request)
    portal = cards.portal_of(store)
    rows = conn.execute(_RELEVANT).fetchall()
    ids = [r["id"] for r in partition(rows, store)["new"]]
    full = conn.execute(
        "SELECT t.id, t.source, t.external_id, t.normalized_json, t.origin, t.created_at, "
        "av.verdict av_verdict, av.score av_score, tv.verdict tv_verdict, "
        "s.margin, s.margin_partial, e.fields_json ex_fields "
        "FROM tenders t "
        "LEFT JOIN verdicts av ON av.tender_id=t.id AND av.stage_name='applicability' "
        "LEFT JOIN verdicts tv ON tv.tender_id=t.id AND tv.stage_name='triage' "
        "LEFT JOIN suppliers s ON s.tender_id=t.id "
        "LEFT JOIN extractions e ON e.tender_id=t.id "
        f"WHERE t.id IN ({','.join('?' * len(ids))}) ORDER BY t.created_at DESC"
        if ids else "SELECT * FROM tenders WHERE 0", tuple(ids)).fetchall()
    _live, _gone, waiting = lifecycle.split(full, store, work.decided_ids(conn, acct_id))
    now = time.time()

    if waiting:
        body_rows = "".join(
            "<tr>" + cards.cell_ref(r) + cards.cell_tender(r, cards.nj_of(r), portal,
                                                          extra=lifecycle.chip(st,
                                                                               cards.nj_of(r)))
            + cards.cell_value(cards.nj_of(r)) + cards.cell_docs(cards.nj_of(r))
            + cards.cell_match(r) + cards.cell_when(r, cards.nj_of(r), now)
            + "</tr>" for r, st in waiting)
        table = ('<div class="card"><table><thead><tr>'
                 '<th style="width:150px">Reference</th><th>Tender</th>'
                 '<th style="width:120px">Value</th><th style="width:170px">Documents</th>'
                 '<th style="width:110px">Match</th><th style="width:130px">Deadline</th>'
                 f"</tr></thead><tbody>{body_rows}</tbody></table></div>")
    else:
        table = ('<div class="card"><div class="empty">Nothing waiting. Announcements with no '
                 "bidding window yet will collect here.</div></div>")

    note = (f'<div class="note" style="margin:0 0 12px">{icon("info")}'
            "These are announced but not yet open for bids — usually a planning notice with no "
            "documents and no submission window. There is nothing to decide yet, so there are no "
            "buttons here on purpose: the moment the buyer publishes a deadline they move into "
            'your <a href="/app/inbox">Inbox</a> on their own.</div>')

    return render(request, "Not open yet", note + table, heading="Not open yet",
                  heading_icon="clock",
                  lede="Announced, but bidding has not started. Nothing to do until it does.",
                  counts=nav_counts(conn, store, acct_id))
