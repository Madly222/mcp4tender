from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app

def _app(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn); ConfigStore(conn).reload()
    return p, conn

def _add(conn, ext, nj, source="mtender", verdict="can", origin="backfill"):
    now = time.time()
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at)"
                 " VALUES(?,?,?,?,'analyzed',?,?,?)", (source, ext, "h", json.dumps(nj), origin, now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) VALUES(?,?,?,?,?)",
                 (tid, "applicability", verdict, 80, time.time()))
    conn.commit(); return tid

def test_iso_utc_deadline_shown_in_local_time(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _app(tmp_path, "a.db")
    _add(conn, "ocds-1", {"title": "CCTV", "publication_date": "2026-06-01T05:00:00Z",
                          "deadline": "2026-07-13T06:00:00Z",
                          "enquiry_deadline": "2026-06-22T07:00:00Z"})
    conn.close()
    h = TestClient(create_app(p)).get("/results?tab=all").text
    assert "13.07.2026, 09:00" in h        # 06:00Z -> 09:00 Chisinau (summer)
    assert "22.06.2026, 10:00" in h
    assert "01.06.2026" in h               # published: date only, no time
    assert "T06:00:00Z" not in h           # raw ISO no longer leaks

def test_genericweb_published_key_is_read(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _app(tmp_path, "g.db")
    _add(conn, "g-1", {"title": "Retea", "published": "13 iulie 2026", "deadline": "15.07.2026"},
         source="genericweb")
    conn.close()
    h = TestClient(create_app(p)).get("/results?tab=all").text
    assert "13.07.2026" in h and "15.07.2026" in h
    assert "Published:</b> —" not in h

def test_unparseable_date_shown_raw_not_dropped(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _app(tmp_path, "u.db")
    _add(conn, "u-1", {"title": "X", "deadline": "in curand"}, source="genericweb")
    conn.close()
    h = TestClient(create_app(p)).get("/results?tab=all").text
    assert "in curand" in h

def test_missing_dates_render_dash(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _app(tmp_path, "m.db")
    _add(conn, "m-1", {"title": "NoDates"})
    conn.close()
    h = TestClient(create_app(p)).get("/results?tab=all").text
    assert "NoDates" in h

def test_tender_page_humanizes(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _app(tmp_path, "t.db")
    tid = _add(conn, "ocds-b3wdp1-MD-9", {"title": "CCTV", "publication_date": "2026-06-01T05:00:00Z",
                                          "deadline": "2026-07-13T06:00:00Z"})
    conn.close()
    h = TestClient(create_app(p)).get(f"/tender?id={tid}").text
    assert "13.07.2026, 09:00" in h and "T06:00:00Z" not in h

def test_sort_published_handles_month_names(tmp_path, monkeypatch):
    import re
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _app(tmp_path, "s.db")
    _add(conn, "s1", {"title": "Older", "published": "1 iunie 2026"}, source="genericweb")
    _add(conn, "s2", {"title": "Newer", "published": "13 iulie 2026"}, source="genericweb")
    conn.close()
    h = TestClient(create_app(p)).get("/results?tab=all&sort=published").text
    order = re.findall(r'rtitle">([^<]+)<', h)
    assert order == ["Newer", "Older"]     # published sorts newest first

def test_estimated_deadline_humanized(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _app(tmp_path, "e.db")
    tid = _add(conn, "e-1", {"title": "Est"})
    conn.execute("INSERT INTO extractions(tender_id,fields_json,method,model,cost,created_at)"
                 " VALUES(?,?,?,?,?,?)", (tid, '{"data_depunerii":"15.07.2026, ora 10:00"}', "llm", "m", 0, time.time()))
    conn.commit(); conn.close()
    h = TestClient(create_app(p)).get("/results?tab=all").text
    assert "15.07.2026, 10:00" in h and "AI-estimated" in h

def test_archive_uses_parsed_month_name_deadline(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _app(tmp_path, "ar.db")
    _add(conn, "ar-1", {"title": "PastRo", "deadline": "1 ianuarie 2020"}, source="genericweb")
    conn.close()
    c = TestClient(create_app(p))
    assert "PastRo" in c.get("/results?tab=archive").text     # month name now parsed -> archived
    assert "PastRo" not in c.get("/results?tab=general").text
