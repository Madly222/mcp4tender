from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from web.render import _e, _layout, _table
from workflows.analysis import (clear_irrelevant, funnel_counts, run_all,
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
            f'<span class="{("v-" + k)}">{_e(k)}: {_e(v)}</span>' for k, v in appl.items())
        appl_line = f'<p class="mut">Applicability verdicts: {parts} &nbsp; · dismissed: {_e(f["dismissed"])}</p>'

    def btn(action, label, primary=False):
        cls = "" if primary else "ghost"
        return (f'<form method=post action="/analyze/{action}" style="margin:0">'
                f'<button class="{cls}">{_e(label)}</button></form>')

    controls = ""
    if not ro:
        controls = (
            '<div class="card"><div class="row">'
            + btn("triage", "1 · Triage new")
            + btn("extract", "2 · Extract")
            + btn("applicability", "3 · Applicability")
            + btn("suppliers", "4 · Suppliers")
            + btn("all", "Run all ▸", primary=True)
            + '<form method=post action="/analyze/clear" style="margin:0" '
              'onsubmit="return confirm(\'Permanently remove tenders rejected as cannot/out? '
              'They will not be re-added on future searches.\')">'
              '<button class="ghost danger">Clear rejected</button></form>'
            + '</div><p class="hint">Searching collects tenders only. Analysis runs here, '
              'on demand, in order: triage filters cheaply, then extract/applicability/suppliers '
              'run the heavier LLM steps only on what passed. "Clear rejected" frees space and '
              'remembers them so they are not collected again.</p></div>')

    rows = [[_e(k), _e(v)] for k, v in sorted(f["by_status"].items())]
    body = (banner + cards + appl_line + controls
            + '<h2>Tenders by status</h2>' + _table(["Status", "Count"], rows))
    return _layout(request, "Analyze", body)


@router.post("/analyze/triage")
def a_triage(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    s = run_triage(request.state.store, request.state.conn)
    return _redir(msg=f"triaged {s['done']}/{s['total']}  buckets={s['buckets']}")


@router.post("/analyze/extract")
def a_extract(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    s = run_extract(request.state.store, request.state.conn)
    return _redir(msg=f"extracted {s['done']}/{s['total']} (failed {s['failed']})")


@router.post("/analyze/applicability")
def a_appl(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    s = run_applicability(request.state.store, request.state.conn)
    return _redir(msg=f"applicability {s['done']}/{s['total']} (failed {s['failed']})")


@router.post("/analyze/suppliers")
def a_suppliers(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    s = run_suppliers(request.state.store, request.state.conn)
    return _redir(msg=f"suppliers {s['done']}/{s['total']} (failed {s['failed']})")


@router.post("/analyze/all")
def a_all(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    r = run_all(request.state.store, request.state.conn)
    return _redir(msg=(f"triage {r['triage']['done']}, extract {r['extract']['done']}, "
                       f"applicability {r['applicability']['done']}, suppliers {r['suppliers']['done']}"))


@router.post("/analyze/clear")
def a_clear(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    n = clear_irrelevant(request.state.conn)
    return _redir(msg=f"cleared {n} rejected tender(s)")
