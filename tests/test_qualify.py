from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
import workflows  # noqa: F401
from workflows import qualify, work

DEFAULTS = str(Path(__file__).resolve().parent.parent / "config" / "defaults")


def _fresh(tmp_path, name):
    p = str(tmp_path / name)
    conn = db.connect(p)
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.seed_defaults(DEFAULTS)
    store.reload()
    store.set("llm.provider", "stub")
    return p, conn, store


def _add(conn, ext, title="Retea de calculatoare"):
    now = time.time()
    nj = {"title": title, "buyer": "STISC", "value_amount": 500000,
          "value_currency": "MDL",
          "cpv": [{"id": "32420000-3", "description": "Network equipment"}],
          "deadline": time.strftime("%Y-%m-%d", time.gmtime(now + 20 * 86400))}
    conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "origin, created_at, updated_at) VALUES('mtender',?,?,?,'new','incremental',?,?)",
        (ext, "h" + ext, json.dumps(nj), now, now))
    conn.commit()
    return conn.execute("SELECT id FROM tenders WHERE external_id=?",
                        (ext,)).fetchone()["id"]


def test_run_qualification_walks_all_stages(tmp_path):
    p, conn, store = _fresh(tmp_path, "q1.db")
    tid = _add(conn, "a1")
    out = qualify.run_qualification(p, tid, 0)
    assert out == "done"
    run = qualify.status_of(conn, tid, 0)
    assert run["status"] == "done" and run["finished_at"]
    assert conn.execute("SELECT COUNT(*) FROM verdicts WHERE tender_id=? AND "
                        "stage_name='applicability'", (tid,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM extractions WHERE tender_id=?",
                        (tid,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM stage_events WHERE tender_id=? AND "
                        "stage='suppliers'", (tid,)).fetchone()[0] > 0
    assert conn.execute("SELECT status FROM tenders WHERE id=?",
                        (tid,)).fetchone()["status"] == "sourced"
    conn.close()


def test_rerun_overwrites_not_duplicates(tmp_path):
    p, conn, store = _fresh(tmp_path, "q2.db")
    tid = _add(conn, "a1")
    qualify.run_qualification(p, tid, 0)
    qualify.run_qualification(p, tid, 0)
    assert conn.execute("SELECT COUNT(*) FROM verdicts WHERE tender_id=? AND "
                        "stage_name='applicability'", (tid,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM extractions WHERE tender_id=?",
                        (tid,)).fetchone()[0] == 1
    conn.close()


def test_is_running_guard_and_staleness(tmp_path):
    p, conn, store = _fresh(tmp_path, "q3.db")
    tid = _add(conn, "a1")
    qualify._begin(conn, tid, 0)
    assert qualify.is_running(conn, tid, 0) is True
    assert qualify.is_running(conn, tid, 0,
                              now=time.time() + qualify.STALE_AFTER + 1) is False
    conn.close()


def _login(p, conn):
    accounts.create(conn, "rapid", "password123", company="Rapid Link")
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rapid",
                                  "password": "password123"}).status_code == 303
    return c


def test_keep_in_inbox_starts_qualification(tmp_path, monkeypatch):
    p, conn, store = _fresh(tmp_path, "q4.db")
    tid = _add(conn, "a1")
    started = []
    monkeypatch.setattr(qualify, "start_qualification",
                        lambda dbp, t, a, runner=None, background=True, begun=False:
                        started.append((dbp, t, a)))
    c = _login(p, conn)
    r = c.post(f"/app/inbox/{tid}/stage", data={"stage": "qualified", "back": "/app/inbox"})
    assert r.status_code == 303
    assert started == [(p, tid, 1)]
    assert qualify.status_of(conn, tid, 1)["status"] == "running"


def test_skip_does_not_start_qualification(tmp_path, monkeypatch):
    p, conn, store = _fresh(tmp_path, "q5.db")
    tid = _add(conn, "a1")
    started = []
    monkeypatch.setattr(qualify, "start_qualification",
                        lambda *a, **k: started.append(a))
    c = _login(p, conn)
    c.post(f"/app/inbox/{tid}/stage", data={"stage": "skipped", "back": "/app/inbox"})
    assert started == []


def test_double_click_starts_only_once(tmp_path, monkeypatch):
    p, conn, store = _fresh(tmp_path, "q6.db")
    tid = _add(conn, "a1")
    started = []
    monkeypatch.setattr(qualify, "start_qualification",
                        lambda dbp, t, a, runner=None, background=True, begun=False:
                        started.append(t))
    c = _login(p, conn)
    c.post(f"/app/inbox/{tid}/stage", data={"stage": "qualified", "back": "/app/inbox"})
    c.post(f"/app/inbox/{tid}/stage", data={"stage": "qualified", "back": "/app/inbox"})
    assert started == [tid]


def test_requalify_route_and_page_strip(tmp_path, monkeypatch):
    p, conn, store = _fresh(tmp_path, "q7.db")
    tid = _add(conn, "a1")
    monkeypatch.setattr(
        qualify, "start_qualification",
        lambda dbp, t, a, runner=None, background=True, begun=False:
        qualify.run_qualification(dbp, t, a, begun))
    c = _login(p, conn)
    r = c.post(f"/app/tender/{tid}/requalify")
    assert r.status_code == 303
    page = c.get(f"/app/tender/{tid}").text
    assert "Analysed" in page and "Re-analyse" in page
    assert qualify.status_of(conn, tid, 1)["status"] == "done"


def test_running_page_shows_progress_and_refresh(tmp_path):
    p, conn, store = _fresh(tmp_path, "q8.db")
    tid = _add(conn, "a1")
    c = _login(p, conn)
    conn.execute("INSERT INTO qualify_runs(tender_id, account_id, status, step, started_at) "
                 "VALUES(?,?,?,?,?)", (tid, 1, "running", "extract", time.time()))
    conn.commit()
    page = c.get(f"/app/tender/{tid}").text
    assert "Analysing" in page
    assert "Reading the documents" in page
    assert 'http-equiv="refresh"' in page


def test_failed_page_offers_rerun(tmp_path):
    p, conn, store = _fresh(tmp_path, "q9.db")
    tid = _add(conn, "a1")
    c = _login(p, conn)
    conn.execute("INSERT INTO qualify_runs(tender_id, account_id, status, step, error, "
                 "started_at, finished_at) VALUES(?,?,?,?,?,?,?)",
                 (tid, 1, "failed", "extract", "the extract stage failed",
                  time.time(), time.time()))
    conn.commit()
    page = c.get(f"/app/tender/{tid}").text
    assert "Analysis failed" in page and "Re-analyse" in page
    assert 'http-equiv="refresh"' not in page
