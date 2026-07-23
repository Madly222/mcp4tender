from __future__ import annotations

import time

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from engine.dateparse import humanize
from web.render import _e, _loose, _ts
from web.user import cards
from web.user.counts import nav_counts
from web.user.icons import icon
from web.user.layout import render
from workflows import qualify, work

router = APIRouter()

DASH = "—"

FIELD_LABELS = {
    "obiect": "What they buy",
    "cerinte_tehnice": "Technical requirements",
    "echipamente": "Equipment asked for",
    "termen_livrare": "Delivery term",
    "data_depunerii": "Submission deadline (from documents)",
    "criterii_calificare": "Qualification criteria",
    "valoare_estimata": "Estimated value",
    "raw": "Raw extraction",
}

ONE = ("SELECT t.id, t.source, t.external_id, t.normalized_json, t.origin, t.status, "
       "t.created_at, av.verdict av_verdict, av.score av_score, av.reason av_reason, "
       "av.model av_model, tv.verdict tv_verdict, tv.reason tv_reason, "
       "s.margin, s.margin_partial, s.items_json, s.total_cost, s.tender_value, s.currency, "
       "s.matched_count, s.unmatched_count, e.fields_json ex_fields "
       "FROM tenders t "
       "LEFT JOIN verdicts av ON av.tender_id=t.id AND av.stage_name='applicability' "
       "LEFT JOIN verdicts tv ON tv.tender_id=t.id AND tv.stage_name='triage' "
       "LEFT JOIN suppliers s ON s.tender_id=t.id "
       "LEFT JOIN extractions e ON e.tender_id=t.id "
       "WHERE t.id=?")


def _fact(label, value):
    return (f'<div class="fact"><span class="fk">{_e(label)}</span>'
            f'<span class="fv">{value}</span></div>')


def _facts(row, nj, portal=None):
    url = cards.tender_link(row, nj, portal)
    portal = (f'<a href="{_e(url)}" target=_blank>Open on the portal</a>' if url else DASH)
    cpv = nj.get("cpv") or []
    chips = ""
    if isinstance(cpv, list):
        chips = "".join(
            f'<span class="chip">{_e(" ".join(str(x) for x in (c.get("id"), c.get("description")) if x))}</span>'
            for c in cpv if isinstance(c, dict))
    amount = nj.get("value_amount")
    if amount in (None, "", 0):
        val = f'<span class="mut">{DASH} not stated</span>'
    else:
        try:
            val = f'{float(amount):,.0f}'.replace(",", " ") + " " + _e(nj.get("value_currency") or "")
        except (TypeError, ValueError):
            val = _e(str(amount))
    raw, estimated = cards.deadline_of(row, nj)
    dl = _e(humanize(raw) or str(raw)) if raw else DASH
    if estimated:
        dl += ' <span class="chip plain">estimated</span>'
    body = (_fact("Reference", f'<span class="mono">{_e(row["external_id"] or DASH)}</span>')
            + _fact("Source", f'{_e(cards.source_label(row, nj))} · {portal}')
            + _fact("Buyer", _e(nj.get("buyer") or DASH))
            + _fact("Value", f'<span class="num">{val}</span>')
            + _fact("Published", _e(humanize(nj.get("publication_date") or nj.get("published"),
                                             with_time=False) or DASH))
            + _fact("Enquiry until", _e(humanize(nj.get("enquiry_deadline")) or DASH))
            + _fact("Deadline", f'<span class="num">{dl}</span>')
            + _fact("CPV", chips or DASH)
            + _fact("Pipeline status", f'<span class="chip">{_e(row["status"] or DASH)}</span>'))
    return f'<div class="card"><div class="card-h"><h2>Facts</h2></div><div class="card-b">{body}</div></div>'


def _verdict_card(row):
    v = row["av_verdict"]
    if not v:
        tv = row["tv_verdict"]
        note = ("Triage let it through, but the applicability analysis has not run yet."
                if tv == "relevant" else "Not analysed yet.")
        return ('<div class="card"><div class="card-h">'
                f'{icon("check-circle")}<h2>Can we do this?</h2></div>'
                f'<div class="empty">{_e(note)}</div></div>')
    score = row["av_score"] or 0
    cls = cards.VERDICT_CLASS.get(v, "m-none")
    chip = cards.VERDICT_CHIP.get(v, "")
    label = cards.VERDICT_LABEL.get(v, v)
    reason = _e(row["av_reason"] or "No reasoning recorded.")
    model = f'<div class="note">{icon("info")}Judged by {_e(row["av_model"] or "the model")} ' \
            f'against your capability profile.</div>' if row["av_model"] else ""
    return ('<div class="card"><div class="card-h">'
            f'{icon("check-circle")}<h2>Can we do this?</h2><div class="spacer"></div>'
            f'<span class="chip {chip}">{_e(label)}</span></div>'
            '<div class="card-b">'
            f'<div class="match {cls}" style="margin-bottom:12px">'
            f'<div class="bar" style="width:120px"><i style="width:{score}%"></i></div>'
            f'<span class="sc num">{round(score / 10)}/10</span></div>'
            f'<div class="reason">{reason}</div></div>{model}</div>')


def _value_of(v):
    if isinstance(v, list):
        if not v:
            return f'<span class="mut">{DASH}</span>'
        if all(not isinstance(x, dict) for x in v):
            return "<ul class=\"tlist\">" + "".join(f"<li>{_e(x)}</li>" for x in v) + "</ul>"
        rows = []
        for x in v:
            if not isinstance(x, dict):
                continue
            head = _e(x.get("denumire") or x.get("model") or "item")
            bits = [f"{_e(k)}: {_e(val)}" for k, val in x.items()
                    if k != "denumire" and val not in (None, "", [])]
            rows.append(f'<li><b>{head}</b>'
                        + (f'<div class="mut">{" · ".join(bits)}</div>' if bits else "")
                        + "</li>")
        return '<ul class="tlist">' + "".join(rows) + "</ul>"
    if v in (None, ""):
        return f'<span class="mut">{DASH}</span>'
    return _e(str(v))


def _extraction(row):
    ef = _loose(row["ex_fields"]) if row["ex_fields"] else None
    if not isinstance(ef, dict) or not ef:
        return ('<div class="card"><div class="card-h"><h2>What the documents say</h2></div>'
                '<div class="empty">Nothing extracted — the documents have not been read yet, '
                'or there were none.</div></div>')
    body = "".join(
        f'<div class="fact"><span class="fk">{_e(FIELD_LABELS.get(k, k))}</span>'
        f'<span class="fv">{_value_of(v)}</span></div>'
        for k, v in ef.items())
    return ('<div class="card"><div class="card-h"><h2>What the documents say</h2></div>'
            f'<div class="card-b">{body}</div></div>')


def _costing(row):
    items = _loose(row["items_json"]) if row["items_json"] else None
    if not isinstance(items, list) or not items:
        return ""
    body = []
    for it in items:
        if not isinstance(it, dict):
            continue
        sup = it.get("supplier")
        fit = it.get("spec_fit") or ""
        chip = {"full": "ok", "partial": "warn", "none": "bad"}.get(fit, "")
        price = it.get("line_cost_converted") or it.get("line_cost")
        try:
            price_txt = f"{float(price):,.0f}".replace(",", " ")
        except (TypeError, ValueError):
            price_txt = DASH
        body.append(
            f'<tr><td>{_e(it.get("requirement") or DASH)}</td>'
            f'<td>{_e(sup) if sup else "<span class=mut>no supplier matched</span>"}'
            + (f'<div class="t-doc-n">{_e(it.get("model"))}</div>' if it.get("model") else "")
            + f'</td><td class="num">{_e(it.get("quantity") or DASH)}</td>'
            f'<td class="num">{price_txt}</td>'
            f'<td><span class="chip {chip}">{_e(fit or "?")}</span></td></tr>')
    margin = ""
    if row["margin"] is not None:
        pct = row["margin"] * 100
        cls = "ok" if pct >= 12 else ("warn" if pct >= 0 else "bad")
        part = " · partial, unmatched items" if row["margin_partial"] else ""
        margin = f'<span class="chip {cls}">Margin {pct:.1f}%{_e(part)}</span>'
    matched = f'{row["matched_count"] or 0} matched · {row["unmatched_count"] or 0} unmatched'
    return ('<div class="card"><div class="card-h">'
            f'<h2>Costing</h2><div class="spacer"></div>{margin}</div>'
            '<table><thead><tr><th>Requirement</th><th>Supplier</th>'
            '<th style="width:70px">Qty</th><th style="width:100px">Line cost</th>'
            '<th style="width:90px">Fit</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>'
            f'<div class="note">{icon("info")}{_e(matched)}. Costs come from your supplier '
            'catalog, converted to the tender currency where needed.</div></div>')


def _documents(row, nj):
    docs = [d for d in (nj.get("documents") or []) if isinstance(d, dict)]
    if not docs:
        return ('<div class="card"><div class="card-h"><h2>Documents</h2></div>'
                '<div class="empty">No attached documents — the spec is inline.</div></div>')
    items = []
    for d in docs:
        t = _e(d.get("title") or d.get("type") or "document")
        u = d.get("url")
        inner = f'<a href="{_e(u)}" target=_blank>{t}</a>' if u else f"<span>{t}</span>"
        items.append(f'<div class="t-doc" style="margin:0">{icon("download")}{inner}</div>')
    return ('<div class="card"><div class="card-h">'
            f'<h2>Documents</h2><div class="spacer"></div>'
            f'<span class="t-doc-n">{len(docs)}</span></div>'
            f'<div class="card-b" style="display:flex;flex-direction:column;gap:9px">'
            f'{"".join(items)}</div></div>')


def _decision(row, info, back):
    stage = (info or {}).get("stage") or "inbox"
    note = (info or {}).get("note") or ""
    opts = "".join(
        f'<option value="{s}"{" selected" if s == stage else ""}>{_e(work.LABELS[s])}</option>'
        for s in work.STAGES)
    return ('<div class="card"><div class="card-h"><h2>Your decision</h2></div>'
            f'<form method="post" action="/app/tender/{row["id"]}/save" class="card-b qa">'
            f'<select name="stage" style="max-width:none;width:100%">{opts}</select>'
            f'<input class="note-in" type="text" name="note" value="{_e(note)}" '
            'placeholder="Note — yours to use however you like">'
            f'<input type="hidden" name="back" value="{_e(back)}">'
            '<button class="btn">Save</button></form>'
            f'<div class="note">{icon("info")}This decision belongs to your company account. '
            'It never changes the tender itself.</div></div>')


def _analysis_strip(row, run, readonly):
    rerun = "" if readonly else (
        f'<form method="post" action="/app/tender/{row["id"]}/requalify" '
        'style="display:inline"><button class="btn ghost">Re-analyse</button></form>')
    if run is None:
        return ""
    status = run.get("status")
    if status == "running":
        label = qualify.STEP_LABELS.get(run.get("step") or "", run.get("step") or "")
        return ('<div class="card"><div class="card-b">'
                f'<span class="chip acc">Analysing…</span> {_e(label)}. '
                'This page refreshes on its own.</div></div><div class="gap"></div>')
    if status == "failed":
        return ('<div class="card"><div class="card-b">'
                f'<span class="chip bad">Analysis failed</span> {_e(run.get("error") or "")} '
                f'{rerun}</div></div><div class="gap"></div>')
    when = _ts(run.get("finished_at")) if run.get("finished_at") else ""
    return ('<div class="card"><div class="card-b">'
            f'<span class="chip ok">Analysed</span> Full analysis finished {_e(when)}. '
            f'{rerun}</div></div><div class="gap"></div>')


@router.post("/app/tender/{tender_id}/save")
def tender_save(request: Request, tender_id: int, stage: str = Form("qualified"),
                note: str = Form(""), back: str = Form("")):
    target = back if back.startswith("/app") else f"/app/tender/{tender_id}"
    if request.state.store.get("web.read_only"):
        return RedirectResponse(target, status_code=303)
    try:
        work.set_stage(request.state.conn, tender_id, work.account_id(request), stage,
                       note=note.strip())
        qualify.maybe_start(request, tender_id, stage)
    except ValueError:
        pass
    return RedirectResponse(target, status_code=303)


@router.post("/app/tender/{tender_id}/requalify")
def tender_requalify(request: Request, tender_id: int):
    target = f"/app/tender/{tender_id}"
    if request.state.store.get("web.read_only"):
        return RedirectResponse(target, status_code=303)
    if request.state.conn.execute(
            "SELECT 1 FROM tenders WHERE id=?", (tender_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="No such tender")
    qualify.maybe_start(request, tender_id, "qualified")
    return RedirectResponse(target, status_code=303)


@router.get("/app/tender/{tender_id}")
def tender(request: Request, tender_id: int):
    conn, store = request.state.conn, request.state.store
    row = conn.execute(ONE, (tender_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such tender")
    acct_id = work.account_id(request)
    nj = cards.nj_of(row)
    info = work.stages_for(conn, [row["id"]], acct_id).get(row["id"])
    stage = (info or {}).get("stage") or "inbox"
    back = f"/app/tender/{tender_id}"

    portal = cards.portal_of(store)
    run = qualify.status_of(conn, row["id"], acct_id)
    sp = conn.execute(
        "SELECT COALESCE(SUM(cost),0) c, COUNT(*) n, COALESCE(SUM(cached),0) h "
        "FROM llm_spend WHERE tender_id=?", (row["id"],)).fetchone()
    spend = ""
    if sp and sp["n"]:
        val = f"${sp['c']:.4f}" if sp["c"] < 0.1 else f"${sp['c']:.2f}"
        spend = (f'<div class="pref-help" style="margin:0 0 10px">AI spend on this tender: '
                 f'<b class="num">{val}</b> · {sp["n"]} calls, {sp["h"]} from cache · '
                 '<a href="/app/costs" style="color:var(--acc)">all spending</a></div>')
    strip = spend + _analysis_strip(row, run, request.state.readonly)
    left = strip + _verdict_card(row) + '<div class="gap"></div>' + _extraction(row)
    costing = _costing(row)
    if costing:
        left += '<div class="gap"></div>' + costing
    right = (_decision(row, info, back) + '<div class="gap"></div>' + _facts(row, nj, portal)
             + '<div class="gap"></div>' + _documents(row, nj))
    body = f'<div class="two">{left}<div>{right}</div></div>'

    heading = (nj.get("title") or "(untitled)")[:110]
    lede = f'{nj.get("buyer") or ""} · {work.LABELS[stage]}'
    refresh = '<meta http-equiv="refresh" content="5">' \
        if run and run.get("status") == "running" else ""
    return render(request, heading[:40], body, heading=heading, lede=lede,
                  counts=nav_counts(conn, store, acct_id), head_extra=refresh)
