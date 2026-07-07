from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from web.render import _e, _layout, _table
from workflows.analysis import (clear_irrelevant, clear_stage, funnel_counts,
                                requeue_failed, reset_analysis, run_all,
                                run_applicability, run_extract, run_suppliers,
                                run_triage)

router = APIRouter()


def _redir(msg="", err=""):
    from urllib.parse import urlencode
    q = urlencode({k: v for k, v in (("msg", msg), ("err", err)) if v})
    return RedirectResponse("/analyze" + ("?" + q if q else ""), status_code=303)


@router.get("/analyze")
def analyze(request: Request, msg: str = "", err: str = ""):
    conn = request.state.conn
    ro = request.state.readonly
    f = funnel_counts(conn)
    banner = ""
    if msg:
        banner += f'<div class="ok">{_e(msg)}</div>'
    if err:
        banner += f'<div class="err">{_e(err)}</div>'

    stages = [
        ("Collected", f["total"], "all tenders stored"),
        ("New", f["new"], "waiting for triage"),
        ("Triaged", f["triaged"], "scored for relevance"),
        ("Extracted", f["extracted"], "documents read"),
        ("Analyzed", f["analyzed"], "applicability decided"),
        ("Sourced", f["sourced"], "margin computed"),
    ]
    cards = '<div class="row" style="align-items:stretch">'
    for name, val, sub in stages:
        cards += (f'<div class="card" style="flex:1;min-width:120px;text-align:center">'
                  f'<div style="font-size:26px;font-weight:700;color:var(--acc)">{_e(val)}</div>'
                  f'<div style="font-weight:600">{_e(name)}</div>'
                  f'<div class="mut" style="font-size:12px">{_e(sub)}</div></div>')
    cards += "</div>"

    appl = f["applicability"]
    appl_line = ""
    if appl:
        parts = " &nbsp; ".join(
            f'<span class="{_e("v-" + (k or "unknown"))}">{_e(k or "unknown")}: {_e(v)}</span>'
            for k, v in appl.items())
        appl_line = f'<p class="mut">Applicability verdicts: {parts} &nbsp; · dismissed: {_e(f["dismissed"])}</p>'

    def btn(action, label, primary=False):
        cls = "" if primary else "ghost"
        return (f'<form method=post action="/analyze/{action}" style="margin:0">'
                f'<button class="{cls}">{_e(label)}</button></form>')

    def stage_col(action, label, stage, confirm):
        run = (f'<form method=post action="/analyze/{action}" style="margin:0">'
               f'<button class="ghost" style="width:100%">{_e(label)}</button></form>')
        clr = (f'<form method=post action="/analyze/clear-stage" style="margin:0" '
               f'onsubmit="return confirm(\'{confirm}\')">'
               f'<input type=hidden name=stage value="{stage}">'
               f'<button class="ghost danger" style="width:100%;font-size:11px;padding:4px 8px" '
               f'title="delete this stage data and any later stage that depends on it">'
               f'✕ clear</button></form>')
        return ('<div style="display:flex;flex-direction:column;gap:5px;min-width:132px">'
                + run + clr + '</div>')

    controls = ""
    if not ro:
        bsz = 50
        try:
            bsz = int(request.state.store.get("analyze.batch_size", 50) or 50)
        except (TypeError, ValueError):
            bsz = 50
        batch_form = (
            '<form method=post action="/analyze/settings" style="margin:0" class="row">'
            f'<input type=number min=1 max=2000 name=batch_size value="{_e(bsz)}" '
            'style="width:70px" title="how many tenders each step processes per press"> per run'
            '<button class="ghost">set</button></form>')
        controls = (
            '<div class="card"><div class="row" style="align-items:flex-start">'
            + stage_col("triage", "1 · Triage new", "triage",
                        "Clear triage results AND every later stage, moving all tenders back to New?")
            + stage_col("extract", "2 · Extract", "extract",
                        "Clear extractions AND later stages (applicability, suppliers), moving affected "
                        "tenders back to Triaged?")
            + stage_col("applicability", "3 · Applicability", "applicability",
                        "Clear applicability AND suppliers, moving affected tenders back to Extracted?")
            + stage_col("suppliers", "4 · Suppliers", "suppliers",
                        "Clear supplier results, moving affected tenders back to Analyzed?")
            + btn("all", "Run all ▸", primary=True)
            + batch_form
            + '<form method=post action="/analyze/retry-failed" style="margin:0">'
              '<button class="ghost" title="requeue tenders whose extraction/analysis failed">'
              'Retry failed</button></form>'
            + '<form method=post action="/analyze/clear" style="margin:0" '
              'onsubmit="return confirm(\'Permanently remove tenders rejected as cannot/out? '
              'They will not be re-added on future searches.\')">'
              '<button class="ghost danger">Clear rejected</button></form>'
            + '</div><p class="hint">Analysis runs in order: triage filters cheaply, then '
              'extract/applicability/suppliers run heavier LLM steps only on what passed. Each step '
              'processes up to "per run" tenders — press again to continue. The small <b>✕ clear</b> '
              'under a stage wipes that stage so you can re-test it; because later stages build on '
              'earlier ones, clearing a stage also clears everything after it and rolls the affected '
              'tenders back one step. "Run all ▸" runs every stage in sequence, like a full daily '
              'pass.</p></div>')

    rows = [[_e(k), _e(v)] for k, v in sorted(f["by_status"].items())]
    body = (banner + cards + appl_line + controls
            + '<h2>Tenders by status</h2>' + _table(["Status", "Count"], rows))
    return _layout(request, "Analyze", body)


def _limit(request):
    try:
        return max(1, min(2000, int(request.state.store.get("analyze.batch_size", 50) or 50)))
    except (TypeError, ValueError):
        return 50


@router.post("/analyze/settings")
def a_settings(request: Request, batch_size: str = Form("50")):
    if request.state.readonly:
        return _redir(err="read-only mode")
    try:
        n = max(1, min(2000, int(batch_size)))
    except (TypeError, ValueError):
        n = 50
    request.state.store.set("analyze.batch_size", n, actor="web", note="set analyze batch")
    return _redir(msg=f"analysis batch set: {n} per run")


@router.post("/analyze/triage")
def a_triage(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    lim = _limit(request)
    s = run_triage(request.state.store, request.state.conn, limit=lim)
    more = " — press again for more" if s["total"] >= lim else ""
    return _redir(msg=f"triaged {s['done']}/{s['total']} (batch {lim}) buckets={s['buckets']}{more}")


@router.post("/analyze/extract")
def a_extract(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    lim = _limit(request)
    s = run_extract(request.state.store, request.state.conn, limit=lim)
    more = " — press again for more" if s["total"] >= lim else ""
    return _redir(msg=f"extracted {s['done']}/{s['total']} (batch {lim}, failed {s['failed']}){more}")


@router.post("/analyze/applicability")
def a_appl(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    lim = _limit(request)
    s = run_applicability(request.state.store, request.state.conn, limit=lim)
    more = " — press again for more" if s["total"] >= lim else ""
    return _redir(msg=f"applicability {s['done']}/{s['total']} (batch {lim}, failed {s['failed']}){more}")


@router.post("/analyze/suppliers")
def a_suppliers(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    lim = _limit(request)
    s = run_suppliers(request.state.store, request.state.conn, limit=lim)
    more = " — press again for more" if s["total"] >= lim else ""
    return _redir(msg=f"suppliers {s['done']}/{s['total']} (batch {lim}, failed {s['failed']}){more}")


@router.post("/analyze/all")
def a_all(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    lim = _limit(request)
    r = run_all(request.state.store, request.state.conn, limit=lim)
    return _redir(msg=(f"batch {lim} · triage {r['triage']['done']}, extract {r['extract']['done']}, "
                       f"applicability {r['applicability']['done']}, suppliers {r['suppliers']['done']}"))


@router.post("/analyze/clear")
def a_clear(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    n = clear_irrelevant(request.state.conn)
    return _redir(msg=f"cleared {n} rejected tender(s)")


@router.post("/analyze/reset")
def a_reset(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    n = reset_analysis(request.state.conn)
    return _redir(msg=f"cleared analysis for {n} tender(s) — all moved back to New")


@router.post("/analyze/retry-failed")
def a_retry_failed(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    n = requeue_failed(request.state.conn)
    return _redir(msg=f"requeued {n} failed tender(s) — run the steps again to retry them")


@router.post("/analyze/clear-stage")
def a_clear_stage(request: Request, stage: str = Form(...)):
    if request.state.readonly:
        return _redir(err="read-only mode")
    n = clear_stage(request.state.conn, stage)
    scope = {"triage": "triage and all later stages",
             "extract": "extract, applicability and suppliers",
             "applicability": "applicability and suppliers",
             "suppliers": "suppliers"}.get(stage, stage)
    return _redir(msg=f"cleared {scope} — {n} tender(s) rolled back one step")
