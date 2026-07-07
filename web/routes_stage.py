from __future__ import annotations

from fastapi import APIRouter, Request

from web.render import _e, _layout, _loose, _table, _ts, _vclass, source_url

router = APIRouter()

STAGES = {
    "triage": {
        "title": "Triage",
        "explain": ("Triage is the cheap first filter. Every collected tender's title is scored "
                    "against your keywords and CPV weights (set in User Settings). Tenders scoring "
                    "at or above the “relevant” threshold are kept as <b>relevant</b>, borderline "
                    "ones as <b>gray</b>, and the rest are dropped. This keeps the expensive LLM "
                    "steps focused only on tenders that might actually fit you."),
        "runs": ("triage",), "verif": ("triage",),
    },
    "extract": {
        "title": "Extract",
        "explain": ("Extract reads each surviving tender's attached documents — or, when a tender "
                    "has none, its own metadata (title, CPV, value) — and pulls out the structured "
                    "facts the later stages reason over: object, estimated value, deadline and any "
                    "required equipment. It runs only on tenders that passed triage."),
        "runs": ("extract",), "verif": ("extract",),
    },
    "applicability": {
        "title": "Applicability",
        "explain": ("Applicability asks the model whether <b>your company</b> can execute the "
                    "tender, comparing its requirements against your company profile (User "
                    "Settings). It returns a verdict — <b>can</b>, <b>partial</b> or <b>cannot</b> — "
                    "with a readiness score, the strengths that match and the gaps that don't."),
        "runs": ("applicability", "applicability_verify"),
        "verif": ("applicability", "applicability_verify"),
    },
    "suppliers": {
        "title": "Suppliers",
        "explain": ("Suppliers estimates cost and margin: it matches the equipment required by the "
                    "tender to your vendor catalogue and computes the commercial picture, so you "
                    "can see the likely margin before committing. It runs on tenders judged "
                    "executable by Applicability."),
        "runs": ("suppliers",), "verif": (),
    },
}


def _title(conn, tid):
    row = conn.execute("SELECT normalized_json FROM tenders WHERE id=?", (tid,)).fetchone()
    if not row:
        return ""
    nj = _loose(row["normalized_json"])
    return (nj.get("title") or "") if isinstance(nj, dict) else ""


def _list_rows(conn, stage, only_id):
    where = "AND t.id = ?" if only_id else ""
    args = (only_id,) if only_id else ()
    if stage == "triage":
        q = ("SELECT t.id, t.normalized_json, t.status, v.verdict, v.score FROM tenders t "
             "JOIN verdicts v ON v.tender_id=t.id AND v.stage_name='triage' "
             f"WHERE 1=1 {where} ORDER BY v.score DESC, t.id DESC LIMIT 300")
        head = ["ID", "Bucket", "Score", "Title"]
        rows = []
        for r in conn.execute(q, args).fetchall():
            title = _e((_title(conn, r["id"]))[:80])
            rows.append([_idlink(stage, r["id"], only_id),
                         f'<span class="{_vclass(r["verdict"])}">{_e(r["verdict"] or "-")}</span>',
                         _e(r["score"] if r["score"] is not None else "-"), title])
        return head, rows
    if stage == "extract":
        q = ("SELECT t.id, t.status, e.method, e.model FROM tenders t "
             "JOIN extractions e ON e.tender_id=t.id "
             f"WHERE 1=1 {where} ORDER BY t.id DESC LIMIT 300")
        head = ["ID", "Method", "Status", "Title"]
        rows = [[_idlink(stage, r["id"], only_id), _e(r["method"] or "-"),
                 f'<span class="{_vclass(r["status"])}">{_e(r["status"])}</span>',
                 _e((_title(conn, r["id"]))[:80])] for r in conn.execute(q, args).fetchall()]
        return head, rows
    if stage == "applicability":
        q = ("SELECT t.id, v.verdict, v.score, v.confidence, v.reason FROM tenders t "
             "JOIN verdicts v ON v.tender_id=t.id AND v.stage_name='applicability' "
             f"WHERE 1=1 {where} ORDER BY v.score DESC, t.id DESC LIMIT 300")
        head = ["ID", "Verdict", "Score", "Conf", "Gaps", "Title"]
        rows = []
        for r in conn.execute(q, args).fetchall():
            reason = _loose(r["reason"])
            gaps = len(reason.get("gaps") or []) if isinstance(reason, dict) else 0
            rows.append([_idlink(stage, r["id"], only_id),
                         f'<span class="{_vclass(r["verdict"])}">{_e(r["verdict"] or "-")}</span>',
                         _e(r["score"] if r["score"] is not None else "-"),
                         _e(r["confidence"] if r["confidence"] is not None else "-"),
                         _e(gaps), _e((_title(conn, r["id"]))[:70])])
        return head, rows
    q = ("SELECT s.tender_id id, s.margin, s.matched_count, s.unmatched_count, s.margin_partial "
         "FROM suppliers s JOIN tenders t ON t.id=s.tender_id "
         f"WHERE 1=1 {where} ORDER BY s.id DESC LIMIT 300")
    head = ["ID", "Margin", "Matched", "Unmatched", "Title"]
    rows = []
    for r in conn.execute(q, args).fetchall():
        margin = f"{r['margin']*100:.1f}%" if r["margin"] is not None else "-"
        if r["margin"] is not None and r["margin_partial"]:
            margin += "~"
        rows.append([_idlink(stage, r["id"], only_id), _e(margin),
                     _e(r["matched_count"]), _e(r["unmatched_count"]),
                     _e((_title(conn, r["id"]))[:70])])
    return head, rows


def _idlink(stage, tid, selected):
    sel = ' style="font-weight:700"' if selected == tid else ""
    return f'<a href="/stage/{stage}?id={tid}"{sel}>{tid}</a>'


def _kv(pairs):
    return ('<table class="kv"><tbody>' + "".join(
        f'<tr><td class="k">{_e(k)}</td><td>{v}</td></tr>' for k, v in pairs)
        + '</tbody></table>')


def _stage_result(conn, stage, tid):
    if stage == "triage":
        v = conn.execute("SELECT verdict, score, reason, model FROM verdicts "
                         "WHERE tender_id=? AND stage_name='triage'", (tid,)).fetchone()
        if not v:
            return '<p class="mut">No triage result.</p>'
        return _kv([("Bucket", f'<span class="{_vclass(v["verdict"])}">{_e(v["verdict"])}</span>'),
                    ("Score", _e(v["score"])), ("Model", _e(v["model"] or "rules")),
                    ("Detail", f'<span class=mono>{_e((v["reason"] or "")[:600])}</span>')])
    if stage == "extract":
        e = conn.execute("SELECT fields_json, method, model, cost, sources_json FROM extractions "
                         "WHERE tender_id=?", (tid,)).fetchone()
        if not e:
            return '<p class="mut">No extraction.</p>'
        f = _loose(e["fields_json"])
        f = f if isinstance(f, dict) else {"raw": str(f)}
        pairs = [("Method", _e(e["method"])), ("Model", _e(e["model"] or "-")),
                 ("Cost", f'${_e(round(e["cost"] or 0, 4))}')]
        for key in ("obiect", "valoare_estimata", "termen_livrare"):
            if f.get(key):
                pairs.append((key, _e(str(f[key])[:400])))
        equip = f.get("echipamente") or []
        if isinstance(equip, list) and equip:
            items = "; ".join(str(x.get("denumire") if isinstance(x, dict) else x) for x in equip[:20])
            pairs.append(("echipamente", _e(items[:500])))
        if f.get("raw"):
            pairs.append(("raw output", f'<span class=mono>{_e(str(f["raw"])[:500])}</span>'))
        return _kv(pairs)
    if stage == "applicability":
        v = conn.execute("SELECT verdict, score, confidence, reason, model FROM verdicts "
                         "WHERE tender_id=? AND stage_name='applicability'", (tid,)).fetchone()
        if not v:
            return '<p class="mut">No applicability result.</p>'
        reason = _loose(v["reason"])
        reason = reason if isinstance(reason, dict) else {}
        pairs = [("Verdict", f'<span class="{_vclass(v["verdict"])}">{_e(v["verdict"])}</span>'),
                 ("Readiness", _e(v["score"])), ("Confidence", _e(v["confidence"])),
                 ("Model", _e(v["model"] or "-"))]
        if reason.get("reasoning"):
            pairs.append(("Reasoning", _e(str(reason["reasoning"])[:800])))
        for key in ("matched", "gaps", "required_equipment"):
            val = reason.get(key)
            if val:
                txt = "; ".join(str(x) for x in val) if isinstance(val, list) else str(val)
                pairs.append((key, _e(txt[:500])))
        return _kv(pairs)
    s = conn.execute("SELECT items_json, total_cost, tender_value, currency, margin, "
                     "matched_count, unmatched_count, margin_partial FROM suppliers "
                     "WHERE tender_id=?", (tid,)).fetchone()
    if not s:
        return '<p class="mut">No supplier estimate.</p>'
    margin = f"{s['margin']*100:.1f}%" if s["margin"] is not None else "-"
    if s["margin"] is not None and s["margin_partial"]:
        margin += " (partial)"
    items = _loose(s["items_json"])
    ilist = ""
    if isinstance(items, list) and items:
        ilist = "<br>".join(
            _e(f'{it.get("name","?")} — {it.get("unit_cost","?")} {s["currency"] or ""}')
            for it in items[:30] if isinstance(it, dict))
    return _kv([("Margin", _e(margin)),
                ("Cost", f'{_e(s["total_cost"])} {_e(s["currency"])}'),
                ("Tender value", f'{_e(s["tender_value"])} {_e(s["currency"])}'),
                ("Matched / unmatched", f'{_e(s["matched_count"])} / {_e(s["unmatched_count"])}'),
                ("Items", ilist or '<span class="mut">—</span>')])


def _run_log(conn, conf, tid):
    names = conf["runs"]
    ph = ",".join("?" * len(names))
    rows = conn.execute(
        f"SELECT run_id, status, tokens, cost, error, started_at, finished_at FROM stage_runs "
        f"WHERE tender_id=? AND stage_name IN ({ph}) ORDER BY id DESC LIMIT 40",
        (tid, *names)).fetchall()
    if not rows:
        return '<p class="mut">No run log entries yet for this tender.</p>'
    out = []
    for r in rows:
        dur = ""
        if r["finished_at"] and r["started_at"]:
            dur = f'{r["finished_at"] - r["started_at"]:.1f}s'
        err = _e((r["error"] or "")[:500])
        out.append([_ts(r["started_at"]),
                    f'<span class="{_vclass(r["status"])}">{_e(r["status"])}</span>',
                    _e(r["tokens"]), f'${_e(round(r["cost"] or 0, 4))}', dur,
                    f'<span title="{_e(r["error"] or "")}" style="white-space:pre-wrap">{err}</span>'])
    return _table(["When", "Status", "Tokens", "Cost", "Time", "Error / message"], out)


def _verif_log(conn, conf, tid):
    names = conf["verif"]
    if not names:
        return ""
    ph = ",".join("?" * len(names))
    rows = conn.execute(
        f"SELECT stage, status, issues_json, retries, needs_review FROM verifications "
        f"WHERE tender_id=? AND stage IN ({ph}) ORDER BY id DESC", (tid, *names)).fetchall()
    if not rows:
        return ""
    out = []
    for r in rows:
        ij = _loose(r["issues_json"])
        ij = ij if isinstance(ij, dict) else {}
        out.append([_e(r["stage"]),
                    f'<span class="{_vclass(r["status"])}">{_e(r["status"] or "-")}</span>',
                    _e(len(ij.get("missing", []) or [])), _e(len(ij.get("issues", []) or [])),
                    _e(r["retries"]),
                    '<span class="v-needs_review">YES</span>' if r["needs_review"] else ""])
    return ('<h3 style="margin:16px 0 6px;font-size:14px">Verification</h3>'
            + _table(["Stage", "Status", "Missing", "Issues", "Retries", "Review"], out))


def _steps_log(conn, stage, tid):
    rows = conn.execute(
        "SELECT label, detail FROM stage_events WHERE tender_id=? AND stage=? ORDER BY seq",
        (tid, stage)).fetchall()
    if not rows:
        return ('<p class="mut">No step trace yet — re-run this stage (after deploying) to '
                'capture the step-by-step trace.</p>')
    items = ""
    for r in rows:
        label = _e(r["label"])
        detail = r["detail"] or ""
        if len(detail) > 160 or "\n" in detail:
            items += (f'<li><details class="stepio"><summary><span class="slabel">{label}</span> '
                      f'<span class="mut" style="font-size:11.5px">({len(detail)} chars — expand)'
                      f'</span></summary><pre>{_e(detail)}</pre></details></li>')
        else:
            items += (f'<li><span class="slabel">{label}</span>'
                      f'<span class="sdetail">{_e(detail)}</span></li>')
    return f'<ol class="steps">{items}</ol>'


def _detail(conn, stage, conf, tid, portal=None):
    t = conn.execute("SELECT id, source, external_id, status FROM tenders WHERE id=?",
                     (tid,)).fetchone()
    if not t:
        return f'<div class="err">No tender with ID {_e(tid)}.</div>'
    title = _e(_title(conn, tid))
    surl = source_url(t["source"], t["external_id"], portal)
    src = (f' · <a href="{_e(surl)}" target=_blank>open on source portal ↗</a>' if surl else "")
    head = (f'<div class="row" style="justify-content:space-between;align-items:baseline">'
            f'<div><span style="font-size:17px;font-weight:650">#{tid}</span> '
            f'<span style="font-size:15px">{title}</span></div>'
            f'<a class="mut" href="/stage/{stage}">← back to list</a></div>'
            f'<p class="mut" style="font-size:12.5px;margin:4px 0 12px">'
            f'<span class="{_vclass(t["status"])}">{_e(t["status"])}</span> · '
            f'<span class=mono>{_e(t["external_id"])}</span>{src} · '
            f'<a href="/tender?id={tid}">full detail across all stages →</a></p>')
    return ('<div class="card">' + head
            + '<h3 style="margin:6px 0 6px;font-size:14px">Result</h3>'
            + _stage_result(conn, stage, tid)
            + '<h3 style="margin:16px 0 6px;font-size:14px">Steps — what happened, in order</h3>'
            + _steps_log(conn, stage, tid)
            + '<h3 style="margin:16px 0 6px;font-size:14px">Run log (model calls)</h3>'
            + _run_log(conn, conf, tid)
            + _verif_log(conn, conf, tid)
            + '</div>')


_STYLE = ('<style>.stage-head p{color:var(--mut);font-size:13px;line-height:1.55;margin:6px 0 0;'
          'max-width:88ch}table.kv{border-collapse:collapse;margin:2px 0}table.kv td{padding:3px 14px 3px 0;'
          'vertical-align:top;font-size:13px}table.kv td.k{color:var(--mut);white-space:nowrap;'
          'font-size:12px}'
          'ol.steps{margin:4px 0;padding-left:22px}ol.steps li{margin:5px 0;font-size:13px;line-height:1.5}'
          'ol.steps .slabel{font-weight:600;margin-right:8px}'
          'ol.steps .sdetail{color:var(--mut)}'
          'details.stepio summary{cursor:pointer}'
          'details.stepio pre{white-space:pre-wrap;word-break:break-word;background:var(--panel-2);'
          'border:1px solid var(--line);border-radius:6px;padding:10px;margin:6px 0 0;font-size:12px;'
          'max-height:340px;overflow:auto;font-family:ui-monospace,Menlo,monospace}</style>')


@router.get("/stage/{stage}")
def stage_page(request: Request, stage: str, id: int = 0, q: str = ""):
    conf = STAGES.get(stage)
    if not conf:
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/stage/triage", status_code=303)
    conn = request.state.conn

    sel = id
    if q.strip().isdigit():
        sel = int(q.strip())

    header = (f'<div class="card stage-head"><h3 style="margin:0;font-size:15px">'
              f'{_e(conf["title"])} — how it works</h3><p>{conf["explain"]}</p></div>')

    search = ('<form method=get action="/stage/' + stage + '" class="row" style="margin:0 0 14px">'
              f'<input type=text name=q value="{_e(q)}" placeholder="find a tender by ID…" '
              'style="max-width:220px"><button class="ghost">Search</button>'
              + (f' <a class="mut" href="/stage/{stage}">clear</a>' if (q or id) else "")
              + '</form>')

    detail = ""
    if sel:
        portal = (request.state.store.get("sources.mtender", {}) or {}).get("portal_url_template")
        detail = _detail(conn, stage, conf, sel, portal)

    only = sel if (q.strip().isdigit()) else 0
    head, rows = _list_rows(conn, stage, only)
    count = len(rows)
    listing = (f'<h3 style="margin:16px 0 8px;font-size:14px">Tenders at this stage ({count})</h3>'
               + (_table(head, rows) if rows else '<p class="mut">Nothing here yet — run this '
                  'stage from the Analyze tab.</p>'))

    body = _STYLE + header + search + detail + listing
    return _layout(request, conf["title"], body)
