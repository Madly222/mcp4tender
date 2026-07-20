from __future__ import annotations
import datetime as dt
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from workflows.segments import classify_segment, partition
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="user")
    conn.commit(); return p, conn
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def _add(conn, ext, title, *, found_days_ago, deadline_days):
    now = time.time()
    nj = {"title": title, "buyer": "ANRCETI", "value_amount": 1432500, "value_currency": "MDL",
          "cpv": [], "documents": [], "status": "active",
          "deadline": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now + deadline_days*86400))}
    found = now - found_days_ago*86400
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at) VALUES('mtender',?,?,?,'analyzed','incremental',?,?)",
                 (ext, "h"+ext, json.dumps(nj), found, found))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) VALUES(?,'applicability','can',90,?)", (tid, now))
    conn.commit(); return tid
def test_an_old_undecided_tender_is_still_new_by_default():
    """The core regression: found 30 days ago, deadline still ahead, nobody touched it.
    It must NOT age out of the inbox."""
    seg = classify_segment("incremental", time.time()-30*86400, None,
                           dt.date.today()+dt.timedelta(days=1), new_days=0)
    assert seg == "new"
def test_an_optional_cap_still_works_when_set():
    old = classify_segment("incremental", time.time()-30*86400, None,
                           dt.date.today()+dt.timedelta(days=5), new_days=7)
    assert old == "history", "a positive new_days is still honoured as an opt-in cap"
def test_a_past_deadline_still_archives():
    seg = classify_segment("incremental", time.time(), None,
                           dt.date.today()-dt.timedelta(days=1), new_days=0)
    assert seg == "archive"
def test_the_screenshot_tender_stays_in_the_inbox(tmp_path, monkeypatch):
    """Analizor de spectru: found ~a week ago, deadline tomorrow, Not scored, untouched."""
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"i1.db")
    _add(conn, "ocds-b3wdp1-MD-1781526952851", "Analizor de spectru",
         found_days_ago=8, deadline_days=1)
    conn.close()
    assert "Analizor de spectru" in _login(p).get("/app/inbox").text
def test_it_survives_repeated_visits_over_time(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"i2.db")
    _add(conn, "x1", "Nu dispare", found_days_ago=20, deadline_days=10)
    conn.close()
    c = _login(p)
    for _ in range(3):
        assert "Nu dispare" in c.get("/app/inbox").text
def test_default_new_days_is_zero(tmp_path):
    p, conn = _fresh(tmp_path,"i3.db")
    s = ConfigStore(conn); s.reload()
    assert int(s.get("results.new_days", -1)) == 0
    conn.close()
def test_only_the_user_removes_a_tender(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"i4.db")
    tid = _add(conn, "x2", "Decid eu", found_days_ago=40, deadline_days=15)
    conn.close()
    c = _login(p)
    assert "Decid eu" in c.get("/app/inbox").text
    c.post(f"/app/tender/{tid}/save", data={"stage": "skipped", "note": "", "back": ""})
    assert "Decid eu" not in c.get("/app/inbox").text
