from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from web.user import lifecycle
NOW = time.time()
CLOSED = {"complete", "cancelled"}
PENDING = {"planning", "planned"}
def _iso(days):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(NOW + days*86400))
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="user")
    conn.commit(); return p, conn
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def _add(conn, ext, title, *, status="active", details=None, deadline_days=None, docs=0):
    nj = {"title": title, "buyer": "STISC", "value_amount": 1000, "value_currency": "MDL",
          "cpv": [], "status": status, "status_details": details,
          "documents": [{"title": f"d{i}.pdf", "url": f"http://x/{i}"} for i in range(docs)]}
    if deadline_days is not None:
        nj["deadline"] = _iso(deadline_days)
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at) VALUES('mtender',?,?,?,'analyzed','incremental',?,?)",
                 (ext, "h"+ext, json.dumps(nj), NOW-3600, NOW))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) VALUES(?,'applicability','can',90,?)", (tid, NOW))
    conn.commit(); return tid
def test_planning_is_pending():
    nj = {"status": "planning", "status_details": None}
    assert lifecycle.state_of(nj, None, CLOSED, PENDING, now=NOW) == lifecycle.PENDING
def test_a_real_deadline_outranks_the_planning_label():
    """If a plan already carries a submission window it is a live tender, not a plan."""
    nj = {"status": "planning"}
    assert lifecycle.state_of(nj, _iso(10), CLOSED, PENDING, now=NOW) == lifecycle.OPEN
def test_a_dead_status_still_wins_over_pending():
    nj = {"status": "planning", "status_details": "cancelled"}
    assert lifecycle.state_of(nj, None, CLOSED, PENDING, now=NOW) == lifecycle.CLOSED
def test_awarded_wins_over_pending():
    nj = {"status": "planning", "awarded": True}
    assert lifecycle.state_of(nj, None, CLOSED, PENDING, now=NOW) == lifecycle.CLOSED
def test_planning_stays_out_of_the_inbox(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"p1.db")
    _add(conn, "p1", "Doar un plan", status="planning")
    _add(conn, "p2", "Tender viu", deadline_days=8, docs=2)
    conn.close()
    c = _login(p)
    inbox = c.get("/app/inbox").text
    assert "Tender viu" in inbox and "Doar un plan" not in inbox
    page = c.get("/app/planning").text
    assert "Doar un plan" in page and "Tender viu" not in page
def test_the_page_has_no_decide_buttons(tmp_path, monkeypatch):
    """A plan must never be buriable by hand: tender_work is permanent and the tender
    would never come back once it goes live."""
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"p2.db")
    _add(conn, "p1", "Doar un plan", status="planning")
    conn.close()
    h = _login(p).get("/app/planning").text
    assert 'value="skipped"' not in h and 'value="qualified"' not in h
    assert "move into" in h and "on their own" in h
def test_a_plan_that_goes_live_walks_into_the_inbox_by_itself(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"p3.db")
    tid = _add(conn, "p1", "Va deveni real", status="planning")
    conn.close()
    c = _login(p)
    assert "Va deveni real" in c.get("/app/planning").text
    assert "Va deveni real" not in c.get("/app/inbox").text
    conn = db.connect(p)
    nj = json.loads(conn.execute("SELECT normalized_json FROM tenders WHERE id=?",
                                 (tid,)).fetchone()[0])
    nj["status"] = "active"
    nj["deadline"] = _iso(12)
    conn.execute("UPDATE tenders SET normalized_json=?, status='updated' WHERE id=?",
                 (json.dumps(nj), tid))
    conn.commit(); conn.close()
    assert "Va deveni real" in c.get("/app/inbox").text, "no manual step must be needed"
    assert "Va deveni real" not in c.get("/app/planning").text
def test_badge_counts_the_waiting_ones(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"p4.db")
    _add(conn, "p1", "Plan unu", status="planning")
    _add(conn, "p2", "Plan doi", status="planned")
    _add(conn, "p3", "Viu", deadline_days=5)
    conn.close()
    from web.user.counts import nav_counts
    conn = db.connect(p); s = ConfigStore(conn); s.reload()
    counts = nav_counts(conn, s, 1)
    assert counts["planning"] == 2 and counts["inbox"] == 1
    conn.close()
    assert 'href="/app/planning"' in _login(p).get("/app").text
def test_the_pending_list_is_configurable(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"p5.db")
    _add(conn, "p1", "Etapa noua", status="active", details="pre-qualification")
    conn.close()
    c = _login(p)
    assert "Etapa noua" in c.get("/app/inbox").text
    conn = db.connect(p); s = ConfigStore(conn)
    s.set("results.pending_statuses", ["planning", "pre-qualification"])
    conn.commit(); conn.close()
    assert "Etapa noua" not in c.get("/app/inbox").text
    assert "Etapa noua" in c.get("/app/planning").text
def test_sweep_never_touches_a_plan(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"p6.db")
    plan = _add(conn, "p1", "Doar un plan", status="planning")
    dead = _add(conn, "p2", "Anulat", status="cancelled")
    conn.close()
    c = _login(p)
    c.post("/app/inbox/sweep")
    from workflows import work
    conn = db.connect(p)
    assert work.stage_of(conn, dead, 1) == "skipped"
    assert work.stage_of(conn, plan, 1) == "inbox", "a plan must stay decidable later"
    conn.close()
    assert "Doar un plan" in c.get("/app/planning").text
