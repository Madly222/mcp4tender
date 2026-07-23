from __future__ import annotations

import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from engine.dateparse import day_end_ts
from web.render import _e
from web.user import cards
from web.user.counts import nav_counts
from web.user.icons import icon
from web.user.layout import render
from web.user.routes_inbox import SELECT
from workflows import work

router = APIRouter()

TABS = ("qualified", "in_progress", "submitted", "won", "lost", "skipped")
OPEN_LABEL = "Open work"


def _wanted(stage):
    return [stage] if stage in work.STAGES and stage != "inbox" else list(work.OPEN_STAGES)


def _tabs(stage, counts):
    out = [f'<a class="tab{"" if stage else " on"}" href="/app/qualified">{OPEN_LABEL}</a>']
    for s in TABS:
        n = counts.get(s, 0)
        cnt = f'<span class="n num">{n}</span>' if n else ""
        on = " on" if stage == s else ""
        out.append(f'<a class="tab{on}" href="/app/qualified?stage={s}">'
                   f"{_e(work.LABELS[s])}{cnt}</a>")
    return '<div class="tabs">' + "".join(out) + "</div>"


def _kpis(counts, closing):
    return ('<div class="kpis">'
            f'<div class="kpi"><div class="k">Qualified</div>'
            f'<div class="v"><span class="num">{counts.get("qualified", 0)}</span></div>'
            f'<div class="d">Kept, not started</div></div>'
            f'<div class="kpi i-acc"><div class="k">In progress</div>'
            f'<div class="v"><span class="num">{counts.get("in_progress", 0)}</span></div>'
            f'<div class="d">Bid being prepared</div></div>'
            f'<div class="kpi i-ok"><div class="k">Submitted</div>'
            f'<div class="v"><span class="num">{counts.get("submitted", 0)}</span></div>'
            f'<div class="d">Awaiting the result</div></div>'
            f'<div class="kpi i-warn"><div class="k">Closing in 7 days</div>'
            f'<div class="v"><span class="num">{closing}</span></div>'
            f'<div class="d">Of the open work</div></div>'
            "</div>")


def _closing_soon(rows, now):
    n = 0
    for r in rows:
        raw, _ = cards.deadline_of(r, cards.nj_of(r))
        ts = day_end_ts(raw) if raw else None
        if ts is not None and 0 <= ts - now <= 7 * 86400:
            n += 1
    return n


@router.post("/app/qualified/{tender_id}/save")
def qualified_save(request: Request, tender_id: int, stage: str = Form("qualified"),
                   note: str = Form(""), back: str = Form("/app/qualified")):
    if request.state.store.get("web.read_only"):
        return RedirectResponse(back, status_code=303)
    try:
        work.set_stage(request.state.conn, tender_id, work.account_id(request), stage,
                       note=note.strip())
    except ValueError:
        pass
    return RedirectResponse(back if back.startswith("/app") else "/app/qualified",
                            status_code=303)


@router.post("/app/qualified/{tender_id}/send")
def qualified_send(request: Request, tender_id: int, back: str = Form("/app/qualified")):
    from urllib.parse import quote
    target = back if back.startswith("/app") else "/app/qualified"
    sep = "&" if "?" in target else "?"
    if request.state.store.get("web.read_only"):
        return RedirectResponse(target, status_code=303)
    from workflows import notify
    res = notify.notify_tender(request.state.store, request.state.conn, tender_id)
    key = "msg" if res["status"] == "ok" else "err"
    return RedirectResponse(f"{target}{sep}{key}=" + quote(res["detail"]), status_code=303)


@router.get("/app/qualified")
def qualified(request: Request, stage: str = "", msg: str = "", err: str = "",
              sort: str = "deadline"):
    conn, store = request.state.conn, request.state.store
    acct_id = work.account_id(request)
    wanted = _wanted(stage)
    ids = work.ids_in(conn, acct_id, wanted)
    counts = work.counts(conn, acct_id)

    rows = []
    if ids:
        marks = ",".join("?" * len(ids))
        rows = conn.execute(f"{SELECT} AND t.id IN ({marks})", tuple(ids)).fetchall()
        missing = set(ids) - {r["id"] for r in rows}
        if missing:
            marks2 = ",".join("?" * len(missing))
            rows += conn.execute(
                f"{SELECT.split('WHERE')[0]} WHERE t.id IN ({marks2})",
                tuple(missing)).fetchall()
    if sort == "deadline":
        def _dlk(r):
            raw, _est = cards.deadline_of(r, cards.nj_of(r))
            ts = day_end_ts(raw) if raw else None
            return (ts is None, ts or 0)
        rows = sorted(rows, key=_dlk)
    else:
        rows = sorted(rows, key=lambda r: r["created_at"] or 0, reverse=True)

    info = work.stages_for(conn, [r["id"] for r in rows], acct_id)
    now = time.time()
    back = request.url.path + ("?" + str(request.url.query) if request.url.query else "")

    if rows:
        body_rows = "".join(
            f'<tr><form method="post" action="/app/qualified/{r["id"]}/save" '
            'style="display:contents">'
            + cards.cell_stage_since(info.get(r["id"]), now)
            + cards.cell_tender(r, cards.nj_of(r), cards.portal_of(store))
            + cards.cell_value(cards.nj_of(r))
            + cards.cell_match(r)
            + cards.cell_when(r, cards.nj_of(r), now)
            + cards.cell_note(info.get(r["id"]))
            + cards.cell_move(r, info.get(r["id"]), back)
            + (f'<td><button class="btn sm ghost" '
               f'formaction="/app/qualified/{r["id"]}/send" '
               f'title="Send the analysis by email / Telegram">{icon("send")}</button></td>')
            + "</form></tr>" for r in rows)
        table = ('<div class="card"><table><thead><tr>'
                 '<th style="width:130px">Stage</th><th>Tender</th>'
                 '<th style="width:120px">Value</th><th style="width:110px">Match</th>'
                 '<th style="width:130px">Deadline</th><th style="width:190px">Note</th>'
                 '<th style="width:200px">Move</th><th style="width:52px">Send</th>'
                 f"</tr></thead><tbody>{body_rows}</tbody></table></div>")
    else:
        table = ('<div class="card"><div class="empty">Nothing here yet. '
                 'Keep a tender in the <a href="/app/inbox">inbox</a> and it lands in this list.'
                 "</div></div>")

    lede = ("Tenders you kept. Move them along as the bid takes shape — the note is yours to use "
            "however you like.")
    head = _kpis(counts, _closing_soon(rows, now)) if not stage else ""
    q_stage = f"stage={stage}&" if stage else ""
    sorter = ('<div class="card"><div class="card-b" style="padding:10px 16px">'
              '<span class="mut" style="font-size:12px">Sort:</span> '
              + " ".join(
                  (f'<b style="margin-left:8px">{lbl}</b>' if sort == key else
                   f'<a style="margin-left:8px;color:var(--acc)" '
                   f'href="/app/qualified?{q_stage}sort={key}">{lbl}</a>')
                  for key, lbl in (("deadline", "By deadline"), ("new", "Newest")))
              + '</div></div><div class="gap"></div>')
    flash = ""
    if msg:
        flash = f'<div class="card"><div class="card-b"><span class="chip ok">Sent</span> {_e(msg)}</div></div><div class="gap"></div>'
    elif err:
        flash = f'<div class="card"><div class="card-b"><span class="chip bad">Not sent</span> {_e(err)}</div></div><div class="gap"></div>'
    return render(request, "Qualified", _tabs(stage, counts) + flash + head + sorter + table,
                  heading=work.LABELS.get(stage, "Qualified") if stage else "Qualified",
                  heading_icon="check-circle", lede=lede,
                  counts=nav_counts(conn, store, acct_id))
