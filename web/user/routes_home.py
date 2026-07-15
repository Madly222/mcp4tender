from __future__ import annotations

from fastapi import APIRouter, Request

from web.user.counts import nav_counts, segment_counts
from workflows import work
from web.user.icons import icon
from web.user.layout import render

router = APIRouter()


@router.get("/app")
def app_home(request: Request):
    conn, store = request.state.conn, request.state.store
    seg = segment_counts(conn, store)
    total = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    kpis = (
        '<div class="kpis">'
        f'<div class="kpi i-acc"><div class="k">New this week</div>'
        f'<div class="v">{icon("inbox")}<span class="num">{seg.get("new", 0)}</span></div>'
        f'<div class="d">Found by the daily check</div></div>'
        f'<div class="kpi i-ok"><div class="k">Worth bidding</div>'
        f'<div class="v">{icon("check-circle")}'
        f'<span class="num">{seg.get("new", 0) + seg.get("history", 0)}</span></div>'
        f'<div class="d">Still open, relevant</div></div>'
        f'<div class="kpi i-warn"><div class="k">Archived</div>'
        f'<div class="v">{icon("archive")}<span class="num">{seg.get("archive", 0)}</span></div>'
        f'<div class="d">Closed or aged out</div></div>'
        f'<div class="kpi"><div class="k">Collected in total</div>'
        f'<div class="v">{icon("search")}<span class="num">{total}</span></div>'
        f'<div class="d">Everything ever found</div></div>'
        '</div>')
    body = kpis + (
        '<div class="card"><div class="card-h">'
        f'{icon("info")}<h2>The rest of this page is still being built</h2></div>'
        '<div class="empty">Closing-soon list, alerts and next steps arrive once tenders '
        'carry a work stage. The numbers above are live.</div></div>')
    return render(request, "Dashboard", body, heading="Today at a glance",
                  lede="What the daily check turned up and what is still open.",
                  counts=nav_counts(conn, store, work.account_id(request)))
