from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn); ConfigStore(conn).reload()
    return p, conn
def _add(conn, ext, title, verdict="can", score=90, dl_days=20, status="analyzed",
         buyer="STISC", age=1):
    now = time.time() - age*86400
    nj = {"title": title, "buyer": buyer, "value_amount": 1250000, "value_currency": "MDL",
          "cpv": [{"id": "32420000-3", "description": "Network equipment"}], "documents": []}
    if dl_days is not None:
        nj["deadline"] = time.strftime("%Y-%m-%dT%H:%M:%S",
                                       time.gmtime(time.time()+dl_days*86400))
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at) VALUES('mtender',?,?,?,?,'incremental',?,?)",
                 (ext, "h"+ext, json.dumps(nj), status, now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    if verdict:
        conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) VALUES(?,'applicability',?,?,?)",
                     (tid, verdict, score, time.time()))
    conn.commit(); return tid
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def test_dashboard_counts_and_empty_open_work(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d1.db")
    _add(conn, "a1", "Echipament de retea")
    _add(conn, "a2", "Neanalizat", verdict=None, status="new")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    h = _login(p).get("/app").text
    assert "Waiting for your call" in h and "Open work" in h
    assert "Nothing in progress" in h
    assert "1 tenders not scored yet" in h or "not scored yet" in h
def test_dashboard_shows_open_work_and_closing_soon(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d2.db")
    tid = _add(conn, "a1", "Echipament de retea", dl_days=3)
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    c.post(f"/app/qualified/{tid}/save", data={"stage": "in_progress", "back": "/app/qualified"})
    h = c.get("/app").text
    assert "Echipament de retea" in h
    assert "Closing soon" in h and "Nothing in progress" not in h
def test_dashboard_alerts_on_a_deadline_within_two_days(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d3.db")
    tid = _add(conn, "a1", "Urgentul", dl_days=1)
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    c.post(f"/app/qualified/{tid}/save", data={"stage": "in_progress", "back": "/app/qualified"})
    h = c.get("/app").text
    assert "within 2 days" in h and "Urgentul" in h
def test_search_finds_irrelevant_tenders_too(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d4.db")
    _add(conn, "a1", "Echipament de retea", verdict="can")
    _add(conn, "a2", "Curatenie in birouri", verdict="cannot", score=5)
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    everything = c.get("/app/search").text
    assert "Echipament de retea" in everything and "Curatenie in birouri" in everything
    assert "Not our work" in everything
    hit = c.get("/app/search?q=Curatenie").text
    assert "Curatenie in birouri" in hit and "Echipament de retea" not in hit
    miss = c.get("/app/search?q=zzzznothing").text
    assert "Nothing in the base matches" in miss
def test_search_can_decide_straight_from_the_results(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d5.db")
    tid = _add(conn, "a1", "Echipament de retea")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    c.post(f"/app/inbox/{tid}/stage", data={"stage": "qualified", "back": "/app/search"})
    assert "Echipament de retea" in c.get("/app/qualified").text
def test_search_pagination(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d6.db")
    for i in range(45):
        _add(conn, f"a{i}", f"Tender number {i}")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    first = c.get("/app/search").text
    assert "Page 1 of 2" in first and "45 tenders" in first
    second = c.get("/app/search?page=2").text
    assert "Page 2 of 2" in second and "Previous" in second
def test_archive_lists_only_aged_out(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d7.db")
    _add(conn, "a1", "Inca deschis", dl_days=20)
    _add(conn, "a2", "Deadline trecut", dl_days=-5)
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    h = _login(p).get("/app/archive").text
    assert "Deadline trecut" in h and "Inca deschis" not in h
def test_archive_empty_state(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d8.db")
    _add(conn, "a1", "Inca deschis", dl_days=20)
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    assert "archive is empty" in _login(p).get("/app/archive").text
