from __future__ import annotations

import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from engine import alerts
from web.render import _e, _ts
from web.user.counts import nav_counts
from web.user.icons import icon
from web.user.layout import render
from workflows import work

router = APIRouter()


def _tender_cell(conn, tender_id):
    if not tender_id:
        return "—"
    row = conn.execute("SELECT normalized_json FROM tenders WHERE id=?",
                       (tender_id,)).fetchone()
    title = ""
    if row:
        try:
            title = (json.loads(row["normalized_json"]) or {}).get("title") or ""
        except Exception:
            title = ""
    return (f'<a href="/app/tender/{tender_id}" style="color:var(--acc)">'
            f'{_e(title[:60] or f"tender #{tender_id}")}</a>')


@router.get("/app/alerts")
def alerts_page(request: Request):
    conn, store = request.state.conn, request.state.store
    items = alerts.recent(conn)
    if not items:
        inner = ('<div class="card"><div class="empty">No errors in the last 7 days. '
                 "When a run fails — the API key running out of credit is the usual "
                 "one — it shows up here.</div></div>")
    else:
        rows = []
        for a in items:
            hint = (f'<div class="pref-help" style="color:var(--bad)">{_e(a["hint"])}</div>'
                    if a["hint"] else "")
            rows.append(
                "<tr>"
                f'<td class="mut" style="white-space:nowrap">{_e(_ts(a["ts"]))}</td>'
                f'<td><span class="chip bad">{_e(a["stage"])}</span></td>'
                f'<td>{_tender_cell(conn, a["tender_id"])}</td>'
                f'<td style="max-width:520px;overflow-wrap:anywhere">{_e(a["error"][:400])}'
                f"{hint}</td></tr>")
        inner = ('<div class="card"><div class="tbl-wrap"><table><thead><tr>'
                 "<th>When</th><th>Where</th><th>Tender</th><th>What happened</th>"
                 f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>')
    mark = ("" if request.state.store.get("web.read_only") else
            '<form method="post" action="/app/alerts/seen" style="display:inline">'
            '<button class="btn ghost sm">Mark all read</button></form>')
    return render(request, "Alerts", inner, heading="Alerts", heading_icon="bang",
                  lede="Every failed run from the last 7 days, newest first.",
                  actions=mark, counts=nav_counts(conn, store, work.account_id(request)))


@router.post("/app/alerts/seen")
def alerts_seen(request: Request):
    if not request.state.store.get("web.read_only"):
        request.state.store.set("alerts.seen_until", time.time(), actor="web")
    return RedirectResponse("/app/alerts", status_code=303)


def _money(v):
    return f"${v:.4f}" if v < 0.1 else f"${v:.2f}"


def _spend_table(title, head, rows):
    if not rows:
        return ""
    body = "".join(rows)
    return ('<div class="card"><div class="card-h">'
            f'{icon("sliders")}<h2>{_e(title)}</h2></div>'
            f'<div class="tbl-wrap"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></div><div class=\"gap\"></div>")


@router.get("/app/costs")
def costs_page(request: Request):
    conn, store = request.state.conn, request.state.store
    now = time.time()
    totals = []
    for label, cutoff in (("Today", now - 86400), ("7 days", now - 7 * 86400),
                          ("30 days", now - 30 * 86400), ("All time", 0)):
        r = conn.execute(
            "SELECT COALESCE(SUM(cost),0) c, COUNT(*) n, "
            "COALESCE(SUM(cached),0) h FROM llm_spend WHERE ts > ?", (cutoff,)).fetchone()
        totals.append(
            f'<div class="strip"><div class="ic">{icon("clock", 3)}</div><div class="tx">'
            f'<b>{_money(r["c"])}</b><span>{_e(label)} · {r["n"]} calls, '
            f'{r["h"]} from cache</span></div></div>')
    kpi = f'<div class="strips">{"".join(totals)}</div><div class="gap"></div>'

    stage_rows = [
        (f'<tr><td>{_e(r["stage"] or "?")}</td><td>{_e(r["model"] or "")}</td>'
         f'<td class="num">{r["n"]}</td><td class="num">{r["h"]}</td>'
         f'<td class="num">{r["itok"]}</td><td class="num">{r["otok"]}</td>'
         f'<td class="num"><b>{_money(r["c"])}</b></td></tr>')
        for r in conn.execute(
            "SELECT stage, model, COUNT(*) n, COALESCE(SUM(cached),0) h, "
            "COALESCE(SUM(input_tokens),0) itok, COALESCE(SUM(output_tokens),0) otok, "
            "COALESCE(SUM(cost),0) c FROM llm_spend GROUP BY stage, model "
            "ORDER BY c DESC")]

    labels = {str(s.get("id")): s.get("label") or s.get("url") or s.get("id")
              for s in (store.get("sites.tenders", []) or []) if isinstance(s, dict)}
    site_rows = [
        (f'<tr><td>{_e(labels.get(r["site_id"], r["site_id"]))}</td>'
         f'<td class="num">{r["n"]}</td><td class="num">{r["h"]}</td>'
         f'<td class="num"><b>{_money(r["c"])}</b></td></tr>')
        for r in conn.execute(
            "SELECT site_id, COUNT(*) n, COALESCE(SUM(cached),0) h, "
            "COALESCE(SUM(cost),0) c FROM llm_spend WHERE site_id IS NOT NULL "
            "GROUP BY site_id ORDER BY c DESC")]

    tender_rows = [
        (f'<tr><td>{_tender_cell(conn, r["tender_id"])}</td>'
         f'<td class="num">{r["n"]}</td><td class="num">{r["h"]}</td>'
         f'<td class="num"><b>{_money(r["c"])}</b></td></tr>')
        for r in conn.execute(
            "SELECT tender_id, COUNT(*) n, COALESCE(SUM(cached),0) h, "
            "COALESCE(SUM(cost),0) c FROM llm_spend WHERE tender_id IS NOT NULL "
            "GROUP BY tender_id ORDER BY c DESC LIMIT 25")]

    empty = ""
    if not (stage_rows or site_rows or tender_rows):
        empty = ('<div class="card"><div class="empty">Nothing recorded yet — spending '
                 "starts being tracked from the first model call after this update. Cached "
                 "answers are listed too (at $0) so leaks are visible.</div></div>")
    body = (kpi
            + _spend_table("By stage and model",
                           "<th>Stage</th><th>Model</th><th>Calls</th><th>Cached</th>"
                           "<th>Tokens in</th><th>Tokens out</th><th>Spent</th>", stage_rows)
            + _spend_table("By site (collection)",
                           "<th>Site</th><th>Calls</th><th>Cached</th><th>Spent</th>",
                           site_rows)
            + _spend_table("Top tenders (analysis)",
                           "<th>Tender</th><th>Calls</th><th>Cached</th><th>Spent</th>",
                           tender_rows)
            + empty)
    return render(request, "Spending", body, heading="AI spending",
                  heading_icon="sliders",
                  lede="Every model call in dollars — by stage, by site, by tender. "
                       "For finding leaks, not for accounting.",
                  counts=nav_counts(conn, store, work.account_id(request)))
