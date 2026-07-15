from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from workflows import work
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn); ConfigStore(conn).reload()
    return p, conn
def _add(conn, ext, title, verdict="can", score=90, dl_days=20):
    now = time.time() - 86400
    nj = {"title": title, "buyer": "STISC", "value_amount": 1250000, "value_currency": "MDL",
          "cpv": [{"id": "32420000-3", "description": "Network equipment"}],
          "deadline": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time()+dl_days*86400)),
          "documents": []}
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at) VALUES('mtender',?,?,?,'analyzed','incremental',?,?)",
                 (ext, "h"+ext, json.dumps(nj), now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) VALUES(?,'applicability',?,?,?)",
                 (tid, verdict, score, time.time()))
    conn.commit(); return tid
def _login(p, login="rl", password="password1"):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": login, "password": password}).status_code == 303
    return c
def test_empty_state_points_at_the_inbox(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"q1.db")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    h = _login(p).get("/app/qualified").text
    assert "Nothing here yet" in h and 'href="/app/inbox"' in h
def test_kept_tender_shows_up_with_kpis(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"q2.db")
    tid = _add(conn, "a1", "Echipament de retea")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    c.post(f"/app/inbox/{tid}/stage", data={"stage": "qualified", "back": "/app/inbox"})
    h = c.get("/app/qualified").text
    assert "Echipament de retea" in h and "Qualified" in h and "9/10" in h
def test_stage_move_and_note_save(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"q3.db")
    tid = _add(conn, "a1", "Echipament de retea")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    c.post(f"/app/inbox/{tid}/stage", data={"stage": "qualified", "back": "/app/inbox"})
    r = c.post(f"/app/qualified/{tid}/save",
               data={"stage": "in_progress", "note": "waiting on the Cisco quote",
                     "back": "/app/qualified"})
    assert r.status_code == 303
    h = c.get("/app/qualified").text
    assert "In progress" in h and "waiting on the Cisco quote" in h
    h2 = c.get("/app/qualified?stage=submitted").text
    assert "Echipament de retea" not in h2
def test_tabs_filter_by_stage(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"q4.db")
    t1 = _add(conn, "a1", "AlphaOne"); t2 = _add(conn, "a2", "BetaTwo")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    c.post(f"/app/qualified/{t1}/save", data={"stage": "submitted", "back": "/app/qualified"})
    c.post(f"/app/qualified/{t2}/save", data={"stage": "skipped", "back": "/app/qualified"})
    openwork = c.get("/app/qualified").text
    assert "AlphaOne" in openwork and "BetaTwo" not in openwork
    skipped = c.get("/app/qualified?stage=skipped").text
    assert "BetaTwo" in skipped and "AlphaOne" not in skipped
def test_kept_tender_survives_a_verdict_change(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"q5.db")
    tid = _add(conn, "a1", "Echipament de retea")
    accounts.create(conn, "rl", "password1", role="admin")
    conn.close()
    c = _login(p)
    c.post(f"/app/qualified/{tid}/save", data={"stage": "in_progress", "back": "/app/qualified"})
    conn = db.connect(p)
    conn.execute("UPDATE verdicts SET verdict='cannot' WHERE tender_id=?", (tid,))
    conn.commit(); conn.close()
    h = c.get("/app/qualified").text
    assert "Echipament de retea" in h
def test_read_only_blocks_the_save(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"q6.db")
    tid = _add(conn, "a1", "Echipament de retea")
    accounts.create(conn, "rl", "password1", role="admin")
    ConfigStore(conn).set("web.read_only", True); conn.commit(); conn.close()
    c = _login(p)
    c.post(f"/app/qualified/{tid}/save", data={"stage": "won", "back": "/app/qualified"})
    assert work.stage_of(db.connect(p), tid, 1) == "inbox"
def test_moving_back_to_inbox_clears_the_row(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"q7.db")
    tid = _add(conn, "a1", "Echipament de retea")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    c.post(f"/app/qualified/{tid}/save", data={"stage": "skipped", "back": "/app/qualified"})
    assert "Echipament de retea" not in c.get("/app/inbox").text
    c.post(f"/app/qualified/{tid}/save", data={"stage": "inbox", "back": "/app/qualified"})
    assert "Echipament de retea" in c.get("/app/inbox").text
