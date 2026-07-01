from __future__ import annotations

import json

from fastapi import APIRouter, Request

from workflows.supervisor import build_digest, check_coverage
from web.render import _e, _layout, _loose, _table, _ts, _vclass

router = APIRouter()


@router.get("/")
def home(request: Request):
    conn, store = request.state.conn, request.state.store
    limit = int(store.get("web.digest_limit", 50))
    digest = build_digest(conn, store, limit=limit)
    if not digest:
        body = ('<div class="card"><div class="empty">No can/partial tenders analyzed yet. '
                'Run the pipeline (collect -> triage -> extract -> '
                'applicability -> suppliers).</div></div>')
        return _layout(request, "Digest", body)
    rows = []
    for d in digest:
        margin = "-"
        if d.get("margin") is not None:
            margin = f"{d['margin'] * 100:.0f}%" + ("~" if d.get("margin_partial") else "")
        title = _e((d.get("title") or "")[:90])
        link = f'<a href="/tender?id={d["tender_id"]}">{title or "(no title)"}</a>'
        buyer = f'<div class="mut" style="font-size:12px">{_e(d.get("buyer"))}</div>' if d.get("buyer") else ""
        gaps = ""
        if d.get("gaps"):
            gaps = '<div class="gaps">' + _e("; ".join(str(g)[:70] for g in d["gaps"])) + "</div>"
        rows.append([
            f'<span class="rank">{_e(d.get("rank_score"))}</span>',
            link + buyer + gaps,
            f'<span class="{_vclass(d.get("verdict"))}">{_e(d.get("verdict"))}</span>',
            f'<span class="r">{_e(d.get("readiness_score"))}</span>',
            f'<span class="nowrap">{_e(margin)} {_e(d.get("currency"))}</span>',
            f'<span class="nowrap">{_e(d.get("deadline") or "?")}</span>',
        ])
    body = _table(["Rank", "Tender", "Verdict", "Score", "Margin", "Deadline"], rows)
    return _layout(request, f"Digest ({len(digest)})", body)


@router.get("/tender")
def tender(request: Request, id: int):
    conn = request.state.conn
    row = conn.execute(
        "SELECT id, source, external_id, status, normalized_json FROM tenders WHERE id = ?",
        (id,)).fetchone()
    if not row:
        return _layout(request, "Tender", '<div class="card"><div class="empty">not found</div></div>')
    nj = _loose(row["normalized_json"])
    docs = nj.get("documents") or []
    doclist = ""
    for d in docs[:30]:
        t = _e(d.get("title") or d.get("documentType") or "doc")
        u = d.get("url")
        doclist += f'<div>{("<a href=" + chr(34) + _e(u) + chr(34) + " target=_blank>" + t + "</a>") if u else t} <span class=mut>[{_e(d.get("format"))}]</span></div>'
    kv = [
        ("title", _e(nj.get("title"))),
        ("buyer", _e(nj.get("buyer"))),
        ("value", f'{_e(nj.get("value_amount"))} {_e(nj.get("value_currency"))}'),
        ("cpv", _e(nj.get("cpv"))),
        ("method", _e(nj.get("method"))),
        ("status", _e(row["status"])),
        ("external_id", f'<span class=mono>{_e(row["external_id"])}</span>'),
    ]
    kvh = "".join(f'<div class=k>{k}</div><div>{v}</div>' for k, v in kv)
    head = f'<div class="card"><div class="kv">{kvh}</div></div>'
    if doclist:
        head += f'<h2>Documents</h2><div class="card">{doclist}</div>'

    ex = conn.execute(
        "SELECT fields_json, method, model, cost FROM extractions WHERE tender_id = ? "
        "ORDER BY id DESC LIMIT 1", (id,)).fetchone()
    exh = ""
    if ex:
        f = _loose(ex["fields_json"])
        equip = f.get("echipamente") or []
        erows = [[_e(e.get("denumire")), _e(e.get("model")), _e(e.get("cantitate")),
                  _e((e.get("specificatii") or "")[:80])] for e in equip]
        exh = f'<h2>Extraction <span class=mut>({_e(ex["method"])} / {_e(ex["model"])})</span></h2>'
        exh += f'<div class="card"><div class=kv><div class=k>obiect</div><div>{_e(f.get("obiect"))}</div>'
        exh += f'<div class=k>termen</div><div>{_e(f.get("termen_livrare"))}</div>'
        exh += f'<div class=k>valoare</div><div>{_e(f.get("valoare_estimata"))}</div></div></div>'
        if erows:
            exh += _table(["Name", "Model", "Qty", "Specs"], erows)

    ap = conn.execute(
        "SELECT verdict, score, confidence, reason, model FROM verdicts "
        "WHERE tender_id = ? AND stage_name = 'applicability' ORDER BY id DESC LIMIT 1",
        (id,)).fetchone()
    aph = ""
    if ap:
        reason = _loose(ap["reason"])
        gaps = reason.get("gaps") or []
        req = reason.get("required_equipment") or reason.get("reason") or ""
        aph = (f'<h2>Applicability</h2><div class="card"><div class=row>'
               f'<span class="{_vclass(ap["verdict"])}" style="font-size:16px">{_e(ap["verdict"])}</span>'
               f'<span class=chip>score {_e(ap["score"])}</span>'
               f'<span class=chip>conf {_e(ap["confidence"])}</span>'
               f'<span class=chip>{_e(ap["model"])}</span></div>')
        if req:
            aph += f'<p>{_e(req if isinstance(req, str) else json.dumps(req, ensure_ascii=False))}</p>'
        if gaps:
            aph += '<div class=gaps>' + _e("; ".join(str(g) for g in gaps)) + '</div>'
        aph += "</div>"

    sup = conn.execute(
        "SELECT items_json, total_cost, tender_value, currency, margin, matched_count, "
        "unmatched_count, margin_partial FROM suppliers WHERE tender_id = ? "
        "ORDER BY id DESC LIMIT 1", (id,)).fetchone()
    suph = ""
    if sup:
        margin = f"{sup['margin'] * 100:.1f}%" if sup["margin"] is not None else "-"
        if sup["margin"] is not None and sup["margin_partial"]:
            margin += "~"
        items = _loose(sup["items_json"]) if sup["items_json"] else []
        irows = []
        if isinstance(items, list):
            for it in items:
                irows.append([_e(it.get("denumire") or it.get("req")),
                              _e(it.get("supplier") or it.get("catalog_id")),
                              _e(it.get("price")), _e(it.get("qty") or it.get("cantitate")),
                              _e(it.get("confidence"))])
        suph = (f'<h2>Suppliers</h2><div class="card"><div class=row>'
                f'<span class=chip>cost {_e(sup["total_cost"])} {_e(sup["currency"])}</span>'
                f'<span class=chip>valoare {_e(sup["tender_value"])} {_e(sup["currency"])}</span>'
                f'<span class=chip>margin {_e(margin)}</span>'
                f'<span class=chip>matched {_e(sup["matched_count"])}</span>'
                f'<span class=chip>unmatched {_e(sup["unmatched_count"])}</span></div></div>')
        if irows:
            suph += _table(["Name", "Supplier", "Price", "Qty", "Conf."], irows)

    back = '<p><a href="/">&larr; digest</a></p>'
    return _layout(request, f"Tender #{id}", back + head + exh + aph + suph)


@router.get("/tenders")
def tenders(request: Request):
    rows = request.state.conn.execute(
        "SELECT id, source, external_id, status, updated_at FROM tenders "
        "ORDER BY id DESC LIMIT 100").fetchall()
    out = [[f'<a href="/tender?id={r["id"]}">{r["id"]}</a>', _e(r["source"]),
            f'<span class=mono>{_e(r["external_id"])}</span>',
            f'<span class="{_vclass(r["status"])}">{_e(r["status"])}</span>',
            _ts(r["updated_at"])] for r in rows]
    return _layout(request, "Tenders", _table(["ID", "Source", "External", "Status", "Updated"], out))


@router.get("/triage")
def triage(request: Request):
    rows = request.state.conn.execute(
        "SELECT t.id, t.normalized_json, v.verdict, v.score, v.reason FROM tenders t "
        "LEFT JOIN verdicts v ON v.tender_id = t.id AND v.stage_name = 'triage' "
        "ORDER BY v.score DESC, t.id DESC LIMIT 200").fetchall()
    out = []
    for r in rows:
        title = _e((_loose(r["normalized_json"]).get("title") or "")[:80])
        out.append([f'<a href="/tender?id={r["id"]}">{r["id"]}</a>',
                    f'<span class="{_vclass(r["verdict"])}">{_e(r["verdict"] or "-")}</span>',
                    _e(r["score"] if r["score"] is not None else "-"), title])
    return _layout(request, "Triage", _table(["ID", "Bucket", "Score", "Title"], out))


@router.get("/applicability")
def applicability(request: Request):
    rows = request.state.conn.execute(
        "SELECT t.id, t.normalized_json, v.verdict, v.score, v.confidence, v.reason "
        "FROM tenders t JOIN verdicts v ON v.tender_id = t.id "
        "AND v.stage_name = 'applicability' ORDER BY v.score DESC LIMIT 200").fetchall()
    out = []
    for r in rows:
        title = _e((_loose(r["normalized_json"]).get("title") or "")[:60])
        ngaps = len((_loose(r["reason"]).get("gaps") or []))
        out.append([f'<a href="/tender?id={r["id"]}">{r["id"]}</a>',
                    f'<span class="{_vclass(r["verdict"])}">{_e(r["verdict"] or "-")}</span>',
                    _e(r["score"] if r["score"] is not None else "-"),
                    _e(r["confidence"] if r["confidence"] is not None else "-"),
                    _e(ngaps), title])
    return _layout(request, "Applicability", _table(["ID", "Verdict", "Score", "Conf", "Gaps", "Title"], out))


@router.get("/suppliers")
def suppliers(request: Request):
    rows = request.state.conn.execute(
        "SELECT tender_id, total_cost, tender_value, currency, margin, matched_count, "
        "unmatched_count, margin_partial FROM suppliers ORDER BY id DESC LIMIT 200").fetchall()
    out = []
    for r in rows:
        margin = f"{r['margin'] * 100:.1f}%" if r["margin"] is not None else "-"
        if r["margin"] is not None and r["margin_partial"]:
            margin += "~"
        out.append([f'<a href="/tender?id={r["tender_id"]}">{r["tender_id"]}</a>',
                    f'{_e(r["total_cost"])} {_e(r["currency"])}',
                    f'{_e(r["tender_value"])} {_e(r["currency"])}', _e(margin),
                    _e(r["matched_count"]), _e(r["unmatched_count"])])
    return _layout(request, "Suppliers", _table(
        ["Tender", "Cost", "Valoare", "Margin", "Matched", "Unmatched"], out))


@router.get("/verifications")
def verifications(request: Request):
    rows = request.state.conn.execute(
        "SELECT tender_id, stage, status, issues_json, retries, needs_review, cost "
        "FROM verifications ORDER BY id DESC LIMIT 200").fetchall()
    out = []
    for r in rows:
        ij = _loose(r["issues_json"])
        out.append([f'<a href="/tender?id={r["tender_id"]}">{r["tender_id"]}</a>',
                    _e(r["stage"]),
                    f'<span class="{_vclass(r["status"])}">{_e(r["status"] or "-")}</span>',
                    _e(len(ij.get("missing", []) or [])), _e(len(ij.get("issues", []) or [])),
                    _e(r["retries"]),
                    '<span class="v-needs_review">YES</span>' if r["needs_review"] else ""])
    return _layout(request, "Verifications", _table(
        ["Tender", "Stage", "Status", "Missing", "Issues", "Retries", "Review"], out))


@router.get("/coverage")
def coverage(request: Request):
    cov = check_coverage(request.state.conn, request.state.store)
    if cov["warnings"]:
        warn = '<div class="err">' + "<br>".join(_e(w) for w in cov["warnings"]) + "</div>"
    else:
        warn = '<div class="ok">ok - no collection warnings</div>'
    out = [[_e(s["source"]), _e(s["age_hours"]), _e(s["last_new"]),
            f'<span class="{_vclass(s["last_status"])}">{_e(s["last_status"])}</span>',
            _e(s["avg_recent_new"])] for s in cov["sources"]]
    body = warn + _table(["Source", "Age (h)", "Last new", "Status", "Avg recent"], out)
    return _layout(request, "Coverage", body)


@router.get("/runs")
def runs(request: Request):
    rows = request.state.conn.execute(
        "SELECT run_id, pipeline, mode, status, started_at, finished_at "
        "FROM pipeline_runs ORDER BY id DESC LIMIT 100").fetchall()
    out = [[f'<span class=mono>{_e(r["run_id"][:12])}</span>', _e(r["pipeline"]),
            _e(r["mode"]), f'<span class="{_vclass(r["status"])}">{_e(r["status"])}</span>',
            _ts(r["started_at"]), _ts(r["finished_at"])] for r in rows]
    return _layout(request, "Runs", _table(
        ["Run", "Pipeline", "Mode", "Status", "Started", "Finished"], out))


@router.get("/stages")
def stages(request: Request):
    rows = request.state.conn.execute(
        "SELECT run_id, stage_name, status, tokens, cost, error, started_at "
        "FROM stage_runs ORDER BY id DESC LIMIT 150").fetchall()
    out = [[f'<span class=mono>{_e(r["run_id"][:12])}</span>', _e(r["stage_name"]),
            f'<span class="{_vclass(r["status"])}">{_e(r["status"])}</span>',
            _e(r["tokens"]), f'${_e(round(r["cost"] or 0, 4))}',
            _e((r["error"] or "")[:50]), _ts(r["started_at"])] for r in rows]
    return _layout(request, "Stages", _table(
        ["Run", "Stage", "Status", "Tokens", "Cost", "Error", "At"], out))


@router.get("/audit")
def audit(request: Request):
    rows = request.state.conn.execute(
        "SELECT ts, actor, action, entity, detail_json FROM audit_log "
        "ORDER BY id DESC LIMIT 200").fetchall()
    out = [[_ts(r["ts"]), _e(r["actor"]), _e(r["action"]),
            f'<span class=mono>{_e(r["entity"])}</span>',
            f'<span class="mono mut">{_e((r["detail_json"] or "")[:80])}</span>'] for r in rows]
    return _layout(request, "Audit", _table(["When", "Actor", "Action", "Entity", "Detail"], out))
