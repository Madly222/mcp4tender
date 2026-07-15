from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from workflows import work
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn); ConfigStore(conn).reload()
    return p, conn
def _add(conn, ext, title, days_old=1, verdict="can", score=90, buyer="STISC", amount=1250000):
    now = time.time() - days_old*86400
    nj = {"title": title, "buyer": buyer, "value_amount": amount, "value_currency": "MDL",
          "cpv": [{"id": "32420000-3", "description": "Network equipment"}],
          "deadline": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time()+20*86400)),
          "documents": [{"title": "Caiet de sarcini.pdf", "url": "http://x/1.pdf"},
                        {"title": "Anunt.pdf", "url": "http://x/2.pdf"},
                        {"title": "Contract.docx", "url": "http://x/3.pdf"}]}
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at) VALUES('mtender',?,?,?,'analyzed','incremental',?,?)",
                 (ext, "h"+ext, json.dumps(nj), now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    if verdict:
        conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) VALUES(?,'applicability',?,?,?)",
                     (tid, verdict, score, time.time()))
    conn.commit(); return tid
def _login(p, login, password):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": login, "password": password}).status_code == 303
    return c
def test_stage_roundtrip_and_default(tmp_path):
    p, conn = _fresh(tmp_path,"w1.db")
    tid = _add(conn, "a1", "Retea")
    assert work.stage_of(conn, tid, 1) == "inbox"
    work.set_stage(conn, tid, 1, "qualified")
    assert work.stage_of(conn, tid, 1) == "qualified"
    work.set_stage(conn, tid, 1, "in_progress", note="waiting on quote")
    assert work.stages_for(conn, [tid], 1)[tid]["note"] == "waiting on quote"
    work.set_stage(conn, tid, 1, "submitted")
    assert work.stages_for(conn, [tid], 1)[tid]["note"] == "waiting on quote"
    work.set_stage(conn, tid, 1, "inbox")
    assert work.stage_of(conn, tid, 1) == "inbox" and work.decided_ids(conn, 1) == set()
    conn.close()
def test_stage_is_per_account(tmp_path):
    p, conn = _fresh(tmp_path,"w2.db")
    tid = _add(conn, "a1", "Retea")
    work.set_stage(conn, tid, 1, "qualified")
    work.set_stage(conn, tid, 2, "skipped")
    assert work.stage_of(conn, tid, 1) == "qualified"
    assert work.stage_of(conn, tid, 2) == "skipped"
    assert work.counts(conn, 1)["qualified"] == 1 and work.counts(conn, 1)["skipped"] == 0
    assert work.counts(conn, 2)["skipped"] == 1
    conn.close()
def test_bad_stage_rejected(tmp_path):
    p, conn = _fresh(tmp_path,"w3.db")
    tid = _add(conn, "a1", "Retea")
    with pytest.raises(ValueError):
        work.set_stage(conn, tid, 1, "whatever")
    conn.close()
def test_inbox_lists_new_and_renders_data(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"w4.db")
    _add(conn, "a1", "Echipament de retea")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="admin")
    conn.close()
    h = _login(p, "rl", "password1").get("/app/inbox").text
    assert "Echipament de retea" in h and "STISC" in h
    assert "1 250 000" in h and "MDL" in h
    assert "9/10" in h and "Full fit" in h
    assert "3 documents" in h and "Caiet de sarcini.pdf" in h and "+1" in h
    assert "32420000-3" in h
def test_keep_moves_out_of_inbox(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"w5.db")
    tid = _add(conn, "a1", "Echipament de retea")
    accounts.create(conn, "rl", "password1", role="admin")
    conn.close()
    c = _login(p, "rl", "password1")
    r = c.post(f"/app/inbox/{tid}/stage", data={"stage": "qualified", "back": "/app/inbox"})
    assert r.status_code == 303
    h = c.get("/app/inbox").text
    assert "Echipament de retea" not in h and "Inbox is clear" in h
def test_read_only_blocks_the_decision(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"w6.db")
    tid = _add(conn, "a1", "Echipament de retea")
    accounts.create(conn, "rl", "password1", role="admin")
    ConfigStore(conn).set("web.read_only", True); conn.commit(); conn.close()
    c = _login(p, "rl", "password1")
    c.post(f"/app/inbox/{tid}/stage", data={"stage": "skipped", "back": "/app/inbox"})
    assert "Echipament de retea" in c.get("/app/inbox").text
def test_inbox_filters(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"w7.db")
    _add(conn, "a1", "Echipament de retea", verdict="can", score=90)
    _add(conn, "a2", "Servicii de curatenie", verdict="partial", score=50, buyer="CNAS")
    accounts.create(conn, "rl", "password1", role="admin")
    conn.close()
    c = _login(p, "rl", "password1")
    both = c.get("/app/inbox").text
    assert "Echipament de retea" in both and "Servicii de curatenie" in both
    only_can = c.get("/app/inbox?match=can").text
    assert "Echipament de retea" in only_can and "Servicii de curatenie" not in only_can
    by_buyer = c.get("/app/inbox?q=CNAS").text
    assert "Servicii de curatenie" in by_buyer and "Echipament de retea" not in by_buyer
def test_nav_badge_drops_after_a_decision(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"w8.db")
    t1 = _add(conn, "a1", "One"); _add(conn, "a2", "Two")
    accounts.create(conn, "rl", "password1", role="admin")
    conn.close()
    c = _login(p, "rl", "password1")
    assert '<span class="badge num">2</span>' in c.get("/app").text
    c.post(f"/app/inbox/{t1}/stage", data={"stage": "skipped", "back": "/app/inbox"})
    h = c.get("/app").text
    assert '<span class="badge num">1</span>' in h
    assert '<span class="n num">1</span>' in h
