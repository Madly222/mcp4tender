from __future__ import annotations

import threading
import time

from engine import db
from engine.config_store import ConfigStore
from engine.orchestrator import process_selected_tenders

STEPS = (("triage", "pipeline.tender_triage", "triaged"),
         ("extract", "pipeline.tender_extract", "extracted"),
         ("applicability", "pipeline.tender_applicability", "analyzed"),
         ("suppliers", "pipeline.tender_suppliers", "sourced"))

STEP_LABELS = {"triage": "Scoring relevance", "extract": "Reading the documents",
               "applicability": "Judging fit against the company profile",
               "suppliers": "Matching the catalog and costing"}

STALE_AFTER = 1800


def status_of(conn, tender_id, acct_id):
    row = conn.execute(
        "SELECT status, step, error, started_at, finished_at FROM qualify_runs "
        "WHERE tender_id=? AND account_id=?", (tender_id, acct_id)).fetchone()
    return dict(row) if row else None


def is_running(conn, tender_id, acct_id, now=None):
    run = status_of(conn, tender_id, acct_id)
    if not run or run["status"] != "running":
        return False
    return ((now or time.time()) - (run["started_at"] or 0)) < STALE_AFTER


def _begin(conn, tender_id, acct_id):
    conn.execute("DELETE FROM qualify_runs WHERE tender_id=? AND account_id=?",
                 (tender_id, acct_id))
    conn.execute(
        "INSERT INTO qualify_runs(tender_id, account_id, status, step, started_at) "
        "VALUES(?,?,?,?,?)", (tender_id, acct_id, "running", "triage", time.time()))
    conn.commit()


def _mark(conn, tender_id, acct_id, status, step=None, error=None, finished=None):
    conn.execute(
        "UPDATE qualify_runs SET status=?, step=COALESCE(?, step), error=?, finished_at=? "
        "WHERE tender_id=? AND account_id=?",
        (status, step, error, finished, tender_id, acct_id))
    conn.commit()


def run_qualification(db_path, tender_id, acct_id, begun=False):
    conn = db.connect(db_path)
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    if not begun:
        _begin(conn, tender_id, acct_id)
    try:
        for step, pipeline, next_status in STEPS:
            _mark(conn, tender_id, acct_id, "running", step=step)
            res = process_selected_tenders(pipeline, store, conn, [tender_id],
                                           next_status=next_status)
            if res["failed"]:
                _mark(conn, tender_id, acct_id, "failed", step=step,
                      error=f"the {step} stage failed — see the tender's run log",
                      finished=time.time())
                return "failed"
        _mark(conn, tender_id, acct_id, "done", finished=time.time())
        return "done"
    except Exception as exc:
        _mark(conn, tender_id, acct_id, "failed", error=str(exc)[:400],
              finished=time.time())
        return "failed"
    finally:
        conn.close()


def start_qualification(db_path, tender_id, acct_id, runner=None, background=True,
                        begun=False):
    target = runner or run_qualification
    if not background:
        return target(db_path, tender_id, acct_id, begun)
    t = threading.Thread(target=target, args=(db_path, tender_id, acct_id, begun),
                         daemon=True)
    t.start()
    return t


def _account_id(request):
    acct = getattr(request.state, "account", None)
    return acct["id"] if acct is not None else 0


def maybe_start(request, tender_id, stage):
    if stage != "qualified":
        return False
    conn = request.state.conn
    acct = _account_id(request)
    if is_running(conn, tender_id, acct):
        return False
    _begin(conn, tender_id, acct)
    start_qualification(request.state.db_path, tender_id, acct, begun=True)
    return True
