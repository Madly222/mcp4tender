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
def _add(conn, ext="ocds-b3wdp1-MD-1749563214", title="Echipament de retea", verdict="can", score=90,
         reason="Rapid Link is a Cisco partner and has done this exact work for STISC.",
         docs=True, extraction=True, costing=True):
    nj = {"title": title, "buyer": "Serviciul Tehnologia Informatiei", "value_amount": 1250000,
          "value_currency": "MDL", "publication_date": "2026-07-01",
          "enquiry_deadline": "2026-07-10T16:00:00",
          "deadline": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time()+20*86400)),
          "cpv": [{"id": "32420000-3", "description": "Network equipment"},
                  {"id": "72700000-7", "description": "Network services"}],
          "documents": [{"title": "Caiet de sarcini.pdf", "url": "http://x/1.pdf"}] if docs else []}
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at) VALUES('mtender',?,?,?,'analyzed','incremental',?,?)",
                 (ext, "h"+ext, json.dumps(nj), time.time()-86400, time.time()))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    if verdict:
        conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,reason,model,created_at) VALUES(?,'applicability',?,?,?,'claude-sonnet',?)",
                     (tid, verdict, score, reason, time.time()))
    if extraction:
        fields = {"obiect": "Switch-uri si routere pentru centrul de date",
                  "cerinte_tehnice": ["48 porturi 1G", "Garantie 36 luni"],
                  "echipamente": [{"denumire": "Switch acces", "model": "C9200-48P",
                                   "cantitate": 12}],
                  "criterii_calificare": ["Certificat ISO 9001"], "valoare_estimata": None}
        conn.execute("INSERT INTO extractions(tender_id,fields_json,model,method,created_at) VALUES(?,?,'haiku','pdf',?)",
                     (tid, json.dumps(fields), time.time()))
    if costing:
        items = [{"requirement": "Switch acces 48 porturi", "supplier": "Cisco",
                  "model": "C9200-48P", "quantity": 12, "line_cost": 820000,
                  "line_cost_converted": 820000, "spec_fit": "full"},
                 {"requirement": "Montaj", "supplier": None, "quantity": 1,
                  "spec_fit": "none"}]
        conn.execute("INSERT INTO suppliers(tender_id,items_json,total_cost,tender_value,currency,margin,matched_count,unmatched_count,margin_partial,created_at) VALUES(?,?,?,?,'MDL',?,1,1,1,?)",
                     (tid, json.dumps(items), 820000, 1250000, 0.18, time.time()))
    conn.commit(); return tid
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def test_detail_shows_everything(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"t1.db")
    tid = _add(conn)
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    h = _login(p).get(f"/app/tender/{tid}").text
    assert "Cisco partner and has done this exact work" in h
    assert "Full fit" in h and "9/10" in h and "claude-sonnet" in h
    assert "Switch-uri si routere" in h and "48 porturi 1G" in h and "C9200-48P" in h
    assert "Certificat ISO 9001" in h
    assert "Margin 18.0%" in h and "partial, unmatched items" in h
    assert "no supplier matched" in h
    assert "Caiet de sarcini.pdf" in h
    assert "32420000-3" in h and "72700000-7" in h
    assert "1 250 000 MDL" in h
def test_detail_handles_a_bare_tender(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"t2.db")
    tid = _add(conn, verdict=None, docs=False, extraction=False, costing=False)
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    h = _login(p).get(f"/app/tender/{tid}").text
    assert "Not analysed yet" in h
    assert "No attached documents" in h
    assert "have not been read yet" in h
    assert "Costing" not in h
def test_detail_404_on_unknown(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"t3.db")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    assert _login(p).get("/app/tender/9999").status_code == 404
def test_decision_saves_from_the_detail_page(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"t4.db")
    tid = _add(conn)
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    r = c.post(f"/app/tender/{tid}/save",
               data={"stage": "in_progress", "note": "quote requested", "back": ""})
    assert r.status_code == 303 and r.headers["location"] == f"/app/tender/{tid}"
    h = c.get(f"/app/tender/{tid}").text
    assert "quote requested" in h and "In progress" in h
def test_lists_link_to_the_detail_page(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"t5.db")
    tid = _add(conn)
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    for page in ("/app/inbox", "/app/search"):
        h = c.get(page).text
        assert f'href="/app/tender/{tid}"' in h, page
        assert ">Link</a>" in h, page
def test_read_only_blocks_the_detail_save(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"t6.db")
    tid = _add(conn)
    accounts.create(conn, "rl", "password1", role="admin")
    ConfigStore(conn).set("web.read_only", True); conn.commit(); conn.close()
    c = _login(p)
    c.post(f"/app/tender/{tid}/save", data={"stage": "won", "note": "x", "back": ""})
    assert work.stage_of(db.connect(p), tid, 1) == "inbox"
