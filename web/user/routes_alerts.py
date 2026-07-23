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
        (f'<tr><td><a style="color:var(--acc)" href="/app/costs/calls?site_id='
         f'{_e(r["site_id"])}">{_e(labels.get(r["site_id"], r["site_id"]))}</a></td>'
         f'<td class="num">{r["n"]}</td><td class="num">{r["h"]}</td>'
         f'<td class="num">{r["itok"]}</td><td class="num">{r["otok"]}</td>'
         f'<td class="num"><b>{_money(r["c"])}</b></td></tr>')
        for r in conn.execute(
            "SELECT site_id, COUNT(*) n, COALESCE(SUM(cached),0) h, "
            "COALESCE(SUM(input_tokens),0) itok, COALESCE(SUM(output_tokens),0) otok, "
            "COALESCE(SUM(cost),0) c FROM llm_spend WHERE site_id IS NOT NULL "
            "GROUP BY site_id ORDER BY c DESC")]

    tender_rows = [
        (f'<tr><td>{_tender_cell(conn, r["tender_id"])}</td>'
         f'<td class="num">{r["n"]}</td><td class="num">{r["h"]}</td>'
         f'<td class="num">{r["itok"]}</td><td class="num">{r["otok"]}</td>'
         f'<td class="num"><b>{_money(r["c"])}</b></td>'
         f'<td><a class="chip plain" href="/app/costs/calls?tender_id='
         f'{r["tender_id"]}">calls</a></td></tr>')
        for r in conn.execute(
            "SELECT tender_id, COUNT(*) n, COALESCE(SUM(cached),0) h, "
            "COALESCE(SUM(input_tokens),0) itok, COALESCE(SUM(output_tokens),0) otok, "
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
                           "<th>Site</th><th>Calls</th><th>Cached</th><th>Tokens in</th>"
                           "<th>Tokens out</th><th>Spent</th>", site_rows)
            + _spend_table("Top tenders (analysis)",
                           "<th>Tender</th><th>Calls</th><th>Cached</th><th>Tokens in</th>"
                           "<th>Tokens out</th><th>Spent</th><th></th>", tender_rows)
            + empty)
    every = ('<a class="btn ghost sm" href="/app/costs/calls">Every call</a> '
             '<a class="btn ghost sm" href="/app/costs/calls?sort=cost">'
             "Most expensive calls</a>")
    return render(request, "Spending", body, heading="AI spending",
                  heading_icon="sliders", actions=every,
                  lede="Every model call in dollars — by stage, by site, by tender. "
                       "For finding leaks, not for accounting.",
                  counts=nav_counts(conn, store, work.account_id(request)))


def _sort_links(base_qs, sort):
    parts = []
    for key, lbl in (("time", "Newest first"), ("cost", "Most expensive first"),
                     ("tokens", "Most tokens in first")):
        if key == sort:
            parts.append(f'<b style="margin-left:8px">{lbl}</b>')
        else:
            qs = f"{base_qs}&sort={key}" if base_qs else f"sort={key}"
            parts.append(f'<a style="margin-left:8px;color:var(--acc)" '
                         f'href="/app/costs/calls?{qs}">{lbl}</a>')
    return ('<div class="card"><div class="card-b" style="padding:10px 16px">'
            '<span class="mut" style="font-size:12px">Sort:</span> '
            + " ".join(parts) + "</div></div><div class=\"gap\"></div>")


@router.get("/app/costs/calls")
def costs_calls(request: Request, tender_id: int = 0, site_id: str = "",
                sort: str = "time"):
    conn, store = request.state.conn, request.state.store
    where, args, crumbs, base_qs = [], [], [], ""
    if tender_id:
        where.append("tender_id=?")
        args.append(tender_id)
        base_qs = f"tender_id={tender_id}"
        crumbs.append(f"tender {_tender_cell(conn, tender_id)}")
    if site_id:
        where.append("site_id=?")
        args.append(site_id)
        base_qs = f"site_id={_e(site_id)}"
        labels = {str(s.get("id")): s.get("label") or s.get("url") or s.get("id")
                  for s in (store.get("sites.tenders", []) or []) if isinstance(s, dict)}
        crumbs.append(f"site <b>{_e(labels.get(site_id, site_id))}</b>")
    order = {"cost": "cost DESC, ts DESC", "tokens": "input_tokens DESC, ts DESC",
             "time": "ts DESC"}.get(sort, "ts DESC")
    sql = ("SELECT ts, stage, model, input_tokens, output_tokens, cost, cached, "
           "tender_id, site_id FROM llm_spend")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order} LIMIT 200"
    rows = conn.execute(sql, tuple(args)).fetchall()
    if not rows:
        table = ('<div class="card"><div class="empty">No calls recorded here yet.'
                 "</div></div>")
    else:
        body_rows = []
        for r in rows:
            if r["tender_id"]:
                belongs = _tender_cell(conn, r["tender_id"])
            elif r["site_id"]:
                belongs = (f'<a style="color:var(--acc)" href="/app/costs/calls?site_id='
                           f'{_e(r["site_id"])}">site {_e(r["site_id"])}</a>')
            else:
                belongs = "—"
            cached = '<span class="chip ok">cache</span>' if r["cached"] else ""
            body_rows.append(
                "<tr>"
                f'<td class="mut" style="white-space:nowrap">{_e(_ts(r["ts"]))}</td>'
                f'<td>{_e(r["stage"] or "?")}</td><td>{_e(r["model"] or "")}</td>'
                f"<td>{belongs}</td>"
                f'<td class="num">{r["input_tokens"]}</td>'
                f'<td class="num">{r["output_tokens"]}</td>'
                f"<td>{cached}</td>"
                f'<td class="num"><b>{_money(r["cost"] or 0)}</b></td></tr>')
        table = ('<div class="card"><div class="tbl-wrap"><table><thead><tr>'
                 "<th>When</th><th>Stage</th><th>Model</th><th>Belongs to</th>"
                 "<th>Tokens in</th><th>Tokens out</th><th></th><th>Cost</th>"
                 f'</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'
                 "</div>")
    head = ""
    if crumbs:
        head = ('<div class="card"><div class="card-b" style="padding:10px 16px">'
                'Showing calls for ' + ", ".join(crumbs)
                + ' · <a style="color:var(--acc)" href="/app/costs/calls">show all'
                "</a></div></div><div class=\"gap\"></div>")
    lede = ("One row per model call — newest 200 shown. Filter from the tables on AI "
            "spending, or sort by cost to see the expensive ones.")
    crumb = '<a class="btn ghost sm" href="/app/costs">AI spending</a>'
    return render(request, "Model calls", head + _sort_links(base_qs, sort) + table,
                  heading="Model calls", heading_icon="sliders", lede=lede,
                  actions=crumb,
                  counts=nav_counts(conn, store, work.account_id(request)))
