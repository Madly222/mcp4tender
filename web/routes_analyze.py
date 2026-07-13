from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from web.render import _e, _layout, _table
from workflows.analysis import (SCOPES, clear_irrelevant, clear_stage, funnel_counts,
                                requeue_failed, reset_analysis, run_all,
                                run_applicability, run_extract, run_suppliers,
                                run_triage, segment_counts)

router = APIRouter()

_SCOPE_LABELS = [
    ("not_new", "All except New"),
    ("all", "Everything"),
    ("new", "New only"),
    ("history", "History only"),
    ("archive", "Archive only"),
]


def _clean_scope(scope):
    return scope if scope in SCOPES else "not_new"


def _redir(msg="", err="", scope="not_new"):
    from urllib.parse import urlencode
    params = {k: v for k, v in (("msg", msg), ("err", err)) if v}
    params["scope"] = _clean_scope(scope)
    return RedirectResponse("/analyze?" + urlencode(params), status_code=303)


@router.get("/analyze")
def analyze(request: Request, msg: str = "", err: str = "", scope: str = "not_new"):
    conn = request.state.conn
    store = request.state.store
    ro = request.state.readonly
    scope = _clean_scope(scope)
    f = funnel_counts(conn)
    banner = ""
    if msg:
        banner += f'<div class="ok">{_e(msg)}</div>'
    if err:
        banner += f'<div class="err">{_e(err)}</div>'

    sc = segment_counts(conn, store)
    scope_help = {
        "not_new": "operations skip New tenders - safe for testing on old data",
        "all": "operations touch every tender, including New",
        "new": "operations touch only New tenders",
        "history": "operations touch only the general/history tenders",
        "archive": "operations touch only archived tenders",
    }
    pills = "".join(
        f'<a class="spill{" on" if scope == k else ""}" href="/analyze?scope={k}">{_e(lbl)}</a>'
        for k, lbl in _SCOPE_LABELS)
    seg_new = sc["new"]
    seg_hist = sc["history"]
    seg_arch = sc["archive"]
    scope_txt = _e(scope_help[scope])
    scope_bar = (
        '<style>.spill{padding:4px 12px;border-radius:999px;background:var(--chip);color:var(--fg);'
        'box-shadow:inset 0 0 0 1px var(--line);text-decoration:none;font-size:12.5px;margin-right:6px}'
        '.spill.on{background:var(--acc,#3b82f6);color:#fff;box-shadow:none}</style>'
        '<div class="card" style="margin-bottom:12px"><div class="row" style="align-items:center">'
        f'<b>Operate on:</b> {pills}</div>'
        '<p class="hint">Runs and clears apply to this set only. Currently: '
        f'<b>{scope_txt}</b>. Segments &mdash; New {seg_new}, '
        f'History {seg_hist}, Archive {seg_arch}.</p></div>')
    sh = f'<input type=hidden name=scope value="{scope}">'

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
        return (f'<form method=post action="/analyze/{action}" style="margin:0">{sh}'
                f'<button class="{cls}">{_e(label)}</button></form>')

    def stage_col(action, label, stage, confirm):
        run = (f'<form method=post action="/analyze/{action}" style="margin:0">{sh}'
               f'<button class="ghost" style="width:100%">{_e(label)}</button></form>')
        clr = (f'<form method=post action="/analyze/clear-stage" style="margin:0" '
               f'onsubmit="return confirm(\'{confirm}\')">{sh}'
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
    body = (banner + cards + appl_line + scope_bar + controls
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


def _sc(scope):
    return _clean_scope(scope)


@router.post("/analyze/triage")
def a_triage(request: Request, scope: str = Form("all")):
    if request.state.readonly:
        return _redir(err="read-only mode", scope=scope)
    lim = _limit(request)
    s = run_triage(request.state.store, request.state.conn, limit=lim, scope=_sc(scope))
    more = " - press again for more" if s["total"] >= lim else ""
    done, total, buckets = s["done"], s["total"], s["buckets"]
    return _redir(msg=f"triaged {done}/{total} (batch {lim}) buckets={buckets}{more}", scope=scope)


@router.post("/analyze/extract")
def a_extract(request: Request, scope: str = Form("all")):
    if request.state.readonly:
        return _redir(err="read-only mode", scope=scope)
    lim = _limit(request)
    s = run_extract(request.state.store, request.state.conn, limit=lim, scope=_sc(scope))
    more = " - press again for more" if s["total"] >= lim else ""
    done, total, failed = s["done"], s["total"], s["failed"]
    return _redir(msg=f"extracted {done}/{total} (batch {lim}, failed {failed}){more}", scope=scope)


@router.post("/analyze/applicability")
def a_appl(request: Request, scope: str = Form("all")):
    if request.state.readonly:
        return _redir(err="read-only mode", scope=scope)
    lim = _limit(request)
    s = run_applicability(request.state.store, request.state.conn, limit=lim, scope=_sc(scope))
    more = " - press again for more" if s["total"] >= lim else ""
    done, total, failed = s["done"], s["total"], s["failed"]
    return _redir(msg=f"applicability {done}/{total} (batch {lim}, failed {failed}){more}",
                  scope=scope)


@router.post("/analyze/suppliers")
def a_suppliers(request: Request, scope: str = Form("all")):
    if request.state.readonly:
        return _redir(err="read-only mode", scope=scope)
    lim = _limit(request)
    s = run_suppliers(request.state.store, request.state.conn, limit=lim, scope=_sc(scope))
    more = " - press again for more" if s["total"] >= lim else ""
    done, total, failed = s["done"], s["total"], s["failed"]
    return _redir(msg=f"suppliers {done}/{total} (batch {lim}, failed {failed}){more}", scope=scope)


@router.post("/analyze/all")
def a_all(request: Request, scope: str = Form("all")):
    if request.state.readonly:
        return _redir(err="read-only mode", scope=scope)
    lim = _limit(request)
    r = run_all(request.state.store, request.state.conn, limit=lim, scope=_sc(scope))
    t, e = r["triage"]["done"], r["extract"]["done"]
    a, sp = r["applicability"]["done"], r["suppliers"]["done"]
    return _redir(msg=(f"batch {lim} - triage {t}, extract {e}, "
                       f"applicability {a}, suppliers {sp}"), scope=scope)


@router.post("/analyze/clear")
def a_clear(request: Request, scope: str = Form("all")):
    if request.state.readonly:
        return _redir(err="read-only mode", scope=scope)
    n = clear_irrelevant(request.state.conn, store=request.state.store, scope=_sc(scope))
    return _redir(msg=f"cleared {n} rejected tender(s)", scope=scope)


@router.post("/analyze/reset")
def a_reset(request: Request, scope: str = Form("all")):
    if request.state.readonly:
        return _redir(err="read-only mode", scope=scope)
    n = reset_analysis(request.state.conn, store=request.state.store, scope=_sc(scope))
    return _redir(msg=f"cleared analysis for {n} tender(s) - moved back to New", scope=scope)


@router.post("/analyze/retry-failed")
def a_retry_failed(request: Request, scope: str = Form("all")):
    if request.state.readonly:
        return _redir(err="read-only mode", scope=scope)
    n = requeue_failed(request.state.conn, store=request.state.store, scope=_sc(scope))
    return _redir(msg=f"requeued {n} failed tender(s) - run the steps again to retry them",
                  scope=scope)


@router.post("/analyze/clear-stage")
def a_clear_stage(request: Request, stage: str = Form(...), scope: str = Form("all")):
    if request.state.readonly:
        return _redir(err="read-only mode", scope=scope)
    n = clear_stage(request.state.conn, stage, store=request.state.store, scope=_sc(scope))
    desc = {"triage": "triage and all later stages",
            "extract": "extract, applicability and suppliers",
            "applicability": "applicability and suppliers",
            "suppliers": "suppliers"}.get(stage, stage)
    return _redir(msg=f"cleared {desc} - {n} tender(s) rolled back one step", scope=scope)
