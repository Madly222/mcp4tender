from __future__ import annotations

import json

from fastapi import APIRouter, Request

from workflows.supervisor import build_digest
from web.render import _e, _layout, _loose, _table, _ts, _vclass, source_url
from web.routes_results import pub_value, show_date

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
            f'<span class="nowrap">{show_date(d.get("deadline"))}</span>',
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
    if not isinstance(nj, dict):
        nj = {}
    docs = nj.get("documents") or []
    if not isinstance(docs, list):
        docs = []
    doclist = ""
    for d in docs[:30]:
        if not isinstance(d, dict):
            continue
        t = _e(d.get("title") or d.get("documentType") or "doc")
        u = d.get("url")
        doclist += f'<div>{("<a href=" + chr(34) + _e(u) + chr(34) + " target=_blank>" + t + "</a>") if u else t} <span class=mut>[{_e(d.get("format"))}]</span></div>'
    def _fmt_cpv(cpv):
        if isinstance(cpv, list):
            parts = []
            for c in cpv:
                if isinstance(c, dict):
                    parts.append(" ".join(str(x) for x in (c.get("id"), c.get("description")) if x))
                elif c:
                    parts.append(str(c))
            return " · ".join(p for p in parts if p)
        return str(cpv or "")
    ex_row = conn.execute("SELECT fields_json FROM extractions WHERE tender_id=?", (id,)).fetchone()
    ef = _loose(ex_row["fields_json"]) if ex_row else {}
    ef = ef if isinstance(ef, dict) else {}
    est_deadline = ef.get("data_depunerii")
    amount = _e(nj.get("value_amount"))
    currency = _e(nj.get("value_currency"))
    kv = [
        ("title", _e(nj.get("title"))),
        ("buyer", _e(nj.get("buyer"))),
        ("value", f'{amount} {currency}'),
        ("published (data publicării)", show_date(pub_value(nj), with_time=False)),
        ("submission deadline (data depunerii)", show_date(nj.get("deadline"))),
        ("enquiry deadline (limită clarificări)", show_date(nj.get("enquiry_deadline"))),
    ]
    if est_deadline and not nj.get("deadline"):
        est_txt = show_date(est_deadline)
        kv.append(("est. deadline (from documents)",
                   f'{est_txt} <span class=mut>· AI-estimated</span>'))
    portal = (request.state.store.get("sources.mtender", {}) or {}).get("portal_url_template")
    surl = source_url(row["source"], row["external_id"], portal)
    src_link = (f' <a href="{_e(surl)}" target=_blank>open on source portal ↗</a>' if surl else "")
    kv += [
        ("cpv", _e(_fmt_cpv(nj.get("cpv")))),
        ("category", _e(nj.get("main_category") or "—")),
        ("method", _e(nj.get("procurement_method") or nj.get("method") or "—")),
        ("status", _e(row["status"])),
        ("source", (f'<a href="{_e(surl)}" target=_blank>open on source portal ↗</a>'
                    if surl else "—")),
        ("external_id", f'<span class=mono>{_e(row["external_id"])}</span>'),
    ]
    if nj.get("description") and nj.get("description") != nj.get("title"):
        kv.insert(3, ("description", _e(str(nj["description"])[:600])))
    kvh = "".join(f'<div class=k>{k}</div><div>{v}</div>' for k, v in kv)
    head = f'<div class="card"><div class="kv">{kvh}</div>'
    if surl:
        head += (f'<p class="mut" style="font-size:12.5px;margin:10px 0 0">Found on: '
                 f'<a href="{_e(surl)}" target=_blank>{_e(surl)}</a></p>')
    head += '</div>'
    if doclist:
        head += f'<h2>Documents</h2><div class="card">{doclist}</div>'
    else:
        head += ('<div class="card mut" style="font-size:12.5px">No documents attached to this '
                 'tender in the source. Small tenders often carry their spec inline (in the title '
                 'and CPV) rather than as files.' + src_link + '</div>')

    ex = conn.execute(
        "SELECT fields_json, method, model, cost FROM extractions WHERE tender_id = ? "
        "ORDER BY id DESC LIMIT 1", (id,)).fetchone()
    exh = ""
    if ex:
        f = _loose(ex["fields_json"])
        if not isinstance(f, dict):
            f = {}
        equip = f.get("echipamente") or []
        if not isinstance(equip, list):
            equip = []
        erows = [[_e(e.get("denumire")), _e(e.get("model")), _e(e.get("cantitate")),
                  _e((e.get("specificatii") or "")[:80])] for e in equip if isinstance(e, dict)]
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
        if not isinstance(reason, dict):
            reason = {}
        gaps = reason.get("gaps") or []
        if not isinstance(gaps, list):
            gaps = []
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
