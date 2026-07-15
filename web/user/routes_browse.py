from __future__ import annotations

import time

from fastapi import APIRouter, Request

from web.render import _e
from web.user import cards
from web.user.counts import nav_counts
from web.user.icons import icon
from web.user.layout import render
from web.user.routes_inbox import SELECT
from workflows import work
from workflows.segments import partition

router = APIRouter()

PER_PAGE = 40
BASE = SELECT.split("WHERE")[0]


def _search_filters(q, action, placeholder):
    return (f'<form method="get" action="{action}" class="filters">'
            f'<div class="fh">{icon("filter")}Filters</div><div class="fb">'
            f'<input class="grow" type="text" name="q" value="{_e(q)}" '
            f'placeholder="{_e(placeholder)}">'
            '<button class="btn">Search</button>'
            f'<a class="btn ghost" href="{action}">Clear</a>'
            "</div></form>")


def _pager(action, q, page, total):
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    if pages <= 1:
        return ""
    qs = f"q={_e(q)}&" if q else ""
    prev = (f'<a class="btn ghost sm" href="{action}?{qs}page={page - 1}">Previous</a>'
            if page > 1 else "")
    nxt = (f'<a class="btn ghost sm" href="{action}?{qs}page={page + 1}">Next</a>'
           if page < pages else "")
    return ('<div class="fb" style="justify-content:space-between;align-items:center;'
            'padding:12px 15px;border-top:1px solid var(--line)">'
            f'{prev or "<span></span>"}'
            f'<span class="t-doc-n num">Page {page} of {pages} · {total} tenders</span>'
            f'{nxt or "<span></span>"}</div>')


def _table(rows, now, decide_back=None):
    body = []
    for r in rows:
        nj = cards.nj_of(r)
        cells = (cards.cell_ref(r) + cards.cell_tender(r, nj) + cards.cell_value(nj)
                 + cards.cell_match(r) + cards.cell_when(r, nj, now))
        if decide_back is not None:
            cells += cards.cell_decide(r, decide_back)
        body.append("<tr>" + cells + "</tr>")
    extra = '<th style="width:90px">Decide</th>' if decide_back is not None else ""
    return ('<table><thead><tr>'
            '<th style="width:150px">Reference</th><th>Tender</th>'
            '<th style="width:120px">Value</th><th style="width:110px">Match</th>'
            f'<th style="width:130px">Deadline</th>{extra}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


@router.get("/app/search")
def search(request: Request, q: str = "", page: int = 1):
    conn, store = request.state.conn, request.state.store
    page = max(1, page)
    where, args = "", []
    if q:
        where = ("WHERE (t.normalized_json LIKE ? OR t.external_id LIKE ?)")
        args = [f"%{q}%", f"%{q}%"]
    total = conn.execute(f"SELECT COUNT(*) FROM tenders t {where}", args).fetchone()[0]
    rows = conn.execute(
        f"{BASE} {where} ORDER BY t.created_at DESC LIMIT ? OFFSET ?",
        (*args, PER_PAGE, (page - 1) * PER_PAGE)).fetchall()
    now = time.time()
    back = "/app/search" + (f"?q={q}&page={page}" if q else f"?page={page}")

    if rows:
        inner = _table(rows, now, decide_back=back) + _pager("/app/search", q, page, total)
    elif q:
        inner = f'<div class="empty">Nothing in the base matches “{_e(q)}”.</div>'
    else:
        inner = '<div class="empty">Nothing collected yet.</div>'

    lede = ("Everything ever collected — relevant or not, open or closed. This is the raw base, "
            "not a filtered shortlist.")
    return render(request, "Search", _search_filters(q, "/app/search", "Title, buyer, CPV or reference")
                  + f'<div class="card">{inner}</div>',
                  heading="Search all tenders", heading_icon="search", lede=lede,
                  counts=nav_counts(conn, store, work.account_id(request)))


@router.get("/app/archive")
def archive(request: Request, q: str = ""):
    conn, store = request.state.conn, request.state.store
    rows = conn.execute(SELECT + " LIMIT 3000").fetchall()
    aged = partition(rows, store)["archive"]
    if q:
        needle = q.lower()
        aged = [r for r in aged
                if needle in f"{cards.nj_of(r).get('title') or ''} "
                             f"{cards.nj_of(r).get('buyer') or ''}".lower()]
    now = time.time()
    if aged:
        inner = _table(aged[:200], now)
    elif q:
        inner = f'<div class="empty">Nothing in the archive matches “{_e(q)}”.</div>'
    else:
        inner = '<div class="empty">The archive is empty — nothing has aged out yet.</div>'
    lede = ("Relevant tenders whose deadline has passed or that aged past the archive limit. "
            "Kept for reference, never deleted.")
    return render(request, "Archive", _search_filters(q, "/app/archive", "Title or buyer")
                  + f'<div class="card">{inner}</div>',
                  heading="Archive", heading_icon="archive", lede=lede,
                  counts=nav_counts(conn, store, work.account_id(request)))
