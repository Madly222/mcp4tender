from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from engine.dateparse import day_end_ts, humanize
from web.render import _e
from web.user import cards
from web.user.counts import nav_counts
from web.user.icons import icon
from web.user.layout import render
from web.user.routes_inbox import SELECT
from workflows import work
from workflows.analysis import funnel_counts

router = APIRouter()

SOON = 7 * 86400


def _open_rows(conn, acct_id):
    ids = work.ids_in(conn, acct_id, work.OPEN_STAGES)
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"{SELECT.split('WHERE')[0]} WHERE t.id IN ({marks})",
                        tuple(ids)).fetchall()
    out = []
    for r in rows:
        raw, _ = cards.deadline_of(r, cards.nj_of(r))
        ts = day_end_ts(raw) if raw else None
        out.append((ts if ts is not None else float("inf"), r, raw, ts))
    out.sort(key=lambda x: x[0])
    return out


def _kpis(inbox_n, w, closing, waiting):
    openwork = w.get("qualified", 0) + w.get("in_progress", 0) + w.get("submitted", 0)
    return ('<div class="kpis">'
            f'<div class="kpi i-acc"><div class="k">Waiting for your call</div>'
            f'<div class="v">{icon("inbox")}<span class="num">{inbox_n}</span></div>'
            f'<div class="d">New and undecided</div></div>'
            f'<div class="kpi i-ok"><div class="k">Open work</div>'
            f'<div class="v">{icon("check-circle")}<span class="num">{openwork}</span></div>'
            f'<div class="d">{w.get("qualified", 0)} qualified · '
            f'{w.get("in_progress", 0)} in progress · {w.get("submitted", 0)} submitted</div></div>'
            f'<div class="kpi i-warn"><div class="k">Closing in 7 days</div>'
            f'<div class="v">{icon("clock")}<span class="num">{closing}</span></div>'
            f'<div class="d">Of the open work</div></div>'
            f'<div class="kpi i-bad"><div class="k">Waiting for analysis</div>'
            f'<div class="v">{icon("alert")}<span class="num">{waiting}</span></div>'
            f'<div class="d">Collected but not scored yet</div></div>'
            "</div>")


def _strips(openrows, waiting, now):
    out = []
    urgent = [(ts, r) for _, r, _raw, ts in openrows
              if ts is not None and 0 <= ts - now <= 2 * 86400]
    if urgent:
        ts, r = urgent[0]
        nj = cards.nj_of(r)
        title = _e((nj.get("title") or "(untitled)")[:52])
        buyer = _e((nj.get("buyer") or "")[:34])
        word = "deadline passes" if len(urgent) == 1 else "deadlines pass"
        out.append('<div class="strip bad">'
                   f'<div class="ic">{icon("bang", 3)}</div>'
                   f'<div class="tx"><b>{len(urgent)} {word} within 2 days</b>'
                   f'<span>{title} · {buyer}</span></div>'
                   '<a class="btn sm ghost" href="/app/qualified">Open</a></div>')
    if waiting:
        out.append('<div class="strip warn">'
                   f'<div class="ic">{icon("bang", 3)}</div>'
                   f'<div class="tx"><b>{waiting} tenders not scored yet</b>'
                   '<span>Collected, but the analysis has not reached them</span></div>'
                   '<form method="post" action="/app/analyze-now" style="margin:0">'
                   '<button class="btn sm">Analyze now</button></form></div>')
    return f'<div class="strips">{"".join(out)}</div>' if out else ""


def _open_table(openrows, now, portal=None):
    if not openrows:
        return ('<div class="card"><div class="card-h">'
                f'{icon("check-circle")}<h2>Open work</h2></div>'
                '<div class="empty">Nothing in progress. Start from the '
                '<a href="/app/inbox">inbox</a>.</div></div>')
    body = "".join(
        "<tr>" + cards.cell_tender(r, cards.nj_of(r), portal) + cards.cell_match(r)
        + cards.cell_when(r, cards.nj_of(r), now) + "</tr>"
        for _, r, _raw, _ts in openrows[:6])
    return ('<div class="card"><div class="card-h">'
            f'{icon("check-circle")}<h2>Open work</h2><div class="spacer"></div>'
            '<a href="/app/qualified">See all</a></div>'
            '<table><thead><tr><th>Tender</th><th style="width:110px">Match</th>'
            '<th style="width:130px">Deadline</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def _soon(openrows, now):
    soon = [(ts, r) for _, r, _raw, ts in openrows
            if ts is not None and 0 <= ts - now <= 30 * 86400]
    if not soon:
        inner = '<div class="empty" style="padding:18px">No deadlines in the next month.</div>'
    else:
        items = []
        for _ts, r in soon[:5]:
            nj = cards.nj_of(r)
            raw, _ = cards.deadline_of(r, nj)
            parts = str(humanize(raw, with_time=False) or "").replace(",", " ").split()
            day = parts[0] if parts else "--"
            mon = parts[1][:3] if len(parts) > 1 else ""
            items.append(f'<div class="mini"><div class="dt"><b class="num">{_e(day)}</b>'
                         f'<span>{_e(mon)}</span></div><div class="mt">'
                         f'<b>{_e((nj.get("title") or "(untitled)")[:44])}</b>'
                         f'<span>{_e((nj.get("buyer") or "")[:30])}</span></div></div>')
        inner = ('<div class="card-b" style="padding-top:6px;padding-bottom:6px">'
                 + "".join(items) + "</div>")
    return ('<div class="card"><div class="card-h">'
            f'{icon("clock")}<h2>Closing soon</h2></div>{inner}'
            '<div class="note">'
            f'{icon("info")}Dates come from the portal. Where the portal has none, the deadline is '
            'read out of the tender documents and marked as estimated.</div></div>')


def _next_steps(inbox_n):
    label = f"Review {inbox_n} new tender{'s' if inbox_n != 1 else ''}" if inbox_n \
        else "Inbox is clear"
    return ('<div class="card"><div class="card-h"><h2>Next steps</h2></div>'
            '<div class="card-b qa">'
            f'<a class="btn" href="/app/inbox">{icon("inbox")}{_e(label)}</a>'
            f'<a class="btn ghost" href="/app/qualified">{icon("check-circle")}Open work</a>'
            f'<a class="btn ghost" href="/app/search">{icon("search")}Search the whole base</a>'
            '</div></div>')


@router.get("/app")
def app_home(request: Request, msg: str = "", err: str = ""):
    conn, store = request.state.conn, request.state.store
    acct_id = work.account_id(request)
    now = time.time()
    counts = nav_counts(conn, store, acct_id)
    inbox_n = counts.get("inbox", 0)
    w = work.counts(conn, acct_id)
    openrows = _open_rows(conn, acct_id)
    closing = sum(1 for _, _r, _raw, ts in openrows if ts is not None and 0 <= ts - now <= SOON)
    waiting = funnel_counts(conn)["new"]
    lede = (f"{inbox_n} tender{'s' if inbox_n != 1 else ''} waiting for your call"
            if inbox_n else "Inbox is clear — nothing new to decide.")
    banner = ""
    if msg:
        banner += f'<div class="ok">{_e(msg)}</div>'
    if err:
        banner += f'<div class="err">{_e(err)}</div>'
    body = (banner + _kpis(inbox_n, w, closing, waiting)
            + _strips(openrows, waiting, now)
            + '<div class="two">' + _open_table(openrows, now)
            + '<div>' + _next_steps(inbox_n) + '<div class="gap"></div>'
            + _soon(openrows, now) + '</div></div>')
    return render(request, "Dashboard", body, heading="Today at a glance", lede=lede,
                  counts=counts)


@router.post("/app/analyze-now")
def analyze_now(request: Request):
    from urllib.parse import quote
    if request.state.readonly:
        return RedirectResponse("/app?err=" + quote("read-only mode"), status_code=303)
    conn, store = request.state.conn, request.state.store
    if not funnel_counts(conn)["new"]:
        return RedirectResponse(
            "/app?msg=" + quote("Nothing waiting — everything collected is already scored."),
            status_code=303)

    from engine import LLMGateway
    gw = LLMGateway(store, conn)
    if gw.expects_real_but_stub():
        return RedirectResponse(
            "/app?err=" + quote("No working API key — analysis would produce placeholder data, "
                                "not real results. Add or fix your key in Settings → AI, then try "
                                "again."), status_code=303)
    from engine.health import check_api_key
    chk = {"status": "ok"} if gw.provider.name != "anthropic" \
        else check_api_key(model=gw.model_for("triage"))
    if chk.get("status") != "ok":
        detail = str(chk.get("detail") or chk.get("code") or "unknown error")[:220]
        return RedirectResponse(
            "/app?err=" + quote(f"Your API key isn't working: {detail}. Check the key, "
                                "its balance and rate limits in Settings → AI."), status_code=303)

    from workflows.analysis import run_all
    limit = 25
    try:
        res = run_all(store, conn, limit=limit, scope="all")
    except Exception as exc:
        return RedirectResponse("/app?err=" + quote(f"Analysis failed: {str(exc)[:240]}"),
                                status_code=303)
    done = sum((v or {}).get("done", 0) for v in res.values())
    failed = sum((v or {}).get("failed", 0) for v in res.values())
    left = funnel_counts(conn)["new"]
    if failed and not done:
        return RedirectResponse(
            "/app?err=" + quote(f"Reached tenders but all {failed} failed to analyse — usually an "
                                "API-key problem (spent balance or rate limit). Check Settings → "
                                "AI."), status_code=303)
    triaged = (res.get("triage") or {}).get("done", 0)
    scored = (res.get("applicability") or {}).get("done", 0)
    msg = (f"Analysed a batch — {triaged} triaged, {scored} scored"
           + (f"; {left} still waiting, click again for the next batch." if left
              else "; all caught up."))
    return RedirectResponse("/app?msg=" + quote(msg), status_code=303)
