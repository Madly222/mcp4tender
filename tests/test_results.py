from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app


def _setup(tmp_path):
    p = str(tmp_path / "r.db")
    conn = db.connect(p)
    db.init_schema(conn)
    ConfigStore(conn).reload()
    now = time.time()

    def add(ext, nj, status):
        conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                     "status,created_at,updated_at) VALUES('mtender',?,?,?,?,?,?)",
                     (ext, "h", nj, status, now, now))
        return conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]

    good = add("o1", '{"title":"CCTV","documents":[{"title":"c.pdf","url":"http://x"}]}', "analyzed")
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) "
                 "VALUES(?,?,?,?,?)", (good, "applicability", "can", 85, now))
    conn.execute("INSERT INTO suppliers(tender_id,margin,created_at) VALUES(?,?,?)", (good, 0.2, now))
    junk = add("o2", '{"title":"Mobilier"}', "analyzed")
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) "
                 "VALUES(?,?,?,?,?)", (junk, "triage", "out", -3, now))
    pend = add("o3", '{"title":"Canc"}', "triaged")
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) "
                 "VALUES(?,?,?,?,?)", (pend, "triage", "relevant", 3, now))
    conn.commit()
    return p


def test_results_shortlist(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = _setup(tmp_path)
    h = TestClient(create_app(p)).get("/results").text
    assert "CCTV" in h and "Can execute" in h and "20.0%" in h
    assert "Canc" in h and "pending analysis" in h
    assert "Mobilier" not in h                  # rejected junk excluded


def test_results_search_by_id_and_nav(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = _setup(tmp_path)
    c = TestClient(create_app(p))
    assert ">Results<" in c.get("/results").text
    tid = ConfigStore(db.connect(p)) and None
    filtered = c.get("/results?q=999999").text        # non-existent id
    assert "0 tender(s)" in filtered


def test_source_url_helper():
    from web.render import source_url
    assert source_url("mtender", "ocds-b3wdp1-MD-123") == "https://mtender.gov.md/tenders/ocds-b3wdp1-MD-123"
    assert source_url("mtender", "ocds-x", "https://p/{ocid}") == "https://p/ocds-x"
    assert source_url("genericweb", "ocds-x") is None
    assert source_url("mtender", "not-ocds") is None


def test_portal_link_when_no_docs(tmp_path, monkeypatch):
    import time
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "l.db")
    conn = db.connect(p)
    db.init_schema(conn)
    ConfigStore(conn).reload()
    now = time.time()
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                 "status,created_at,updated_at) VALUES('mtender','ocds-b3wdp1-MD-9','h',?,'triaged',?,?)",
                 ('{"title":"Canc","documents":[]}', now, now))
    tid = conn.execute("SELECT id FROM tenders").fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) "
                 "VALUES(?,?,?,?,?)", (tid, "triage", "relevant", 3, now))
    conn.commit()
    conn.close()
    c = TestClient(create_app(p))
    link = "https://mtender.gov.md/tenders/ocds-b3wdp1-MD-9"
    assert link in c.get(f"/tender?id={tid}").text
    assert link in c.get(f"/stage/triage?id={tid}").text
    assert link in c.get("/results").text


def test_three_dates_and_estimated_deadline(tmp_path, monkeypatch):
    import time
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "d.db")
    conn = db.connect(p)
    db.init_schema(conn)
    ConfigStore(conn).reload()
    now = time.time()
    nj = ('{"title":"CCTV","publication_date":"2026-06-01","enquiry_deadline":"2026-06-20",'
          '"deadline":null}')
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                 "status,created_at,updated_at) VALUES('mtender','ocds-x','h',?,'analyzed',?,?)",
                 (nj, now, now))
    tid = conn.execute("SELECT id FROM tenders").fetchone()["id"]
    conn.execute("INSERT INTO extractions(tender_id,fields_json,method,model,cost,created_at) "
                 "VALUES(?,?,?,?,?,?)", (tid, '{"data_depunerii":"15.07.2026"}', "llm", "m", 0, now))
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) "
                 "VALUES(?,?,?,?,?)", (tid, "applicability", "can", 80, now))
    conn.commit()
    conn.close()
    c = TestClient(create_app(p))
    d = c.get(f"/tender?id={tid}").text
    assert "data publicării" in d and "data depunerii" in d and "clarificări" in d
    assert "2026-06-01" in d and "15.07.2026" in d and "AI-estimated" in d
    res = c.get("/results").text
    assert "Published:" in res and "Enquiry:" in res and "AI-estimated" in res


def _add_dated(conn, ext, title, pub, dl, cpv, now):
    import json
    nj = json.dumps({"title": title, "publication_date": pub, "deadline": dl,
                     "cpv": [{"id": cpv, "description": "d"}]})
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                 "status,created_at,updated_at) VALUES('mtender',?,?,?,'analyzed',?,?)",
                 (ext, "h", nj, now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) "
                 "VALUES(?,?,?,?,?)", (tid, "applicability", "can", 80, now))


def _order(txt):
    import re
    return re.findall(r'rtitle">([^<]+)<', txt)


def test_results_sort_by_date_default(tmp_path, monkeypatch):
    import time
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "so.db")
    conn = db.connect(p)
    db.init_schema(conn)
    ConfigStore(conn).reload()
    now = time.time()
    _add_dated(conn, "a", "Alpha", "2026-06-10", "2026-08-01", "32000000-3", now)
    _add_dated(conn, "b", "Beta", "2026-06-20", "2026-07-01", "30100000-0", now)
    _add_dated(conn, "c", "Gamma", "2026-06-01", None, "32000000-3", now)
    conn.commit()
    conn.close()
    c = TestClient(create_app(p))
    assert _order(c.get("/results").text) == ["Beta", "Alpha", "Gamma"]          # deadline asc, none last
    assert _order(c.get("/results?sort=published").text) == ["Beta", "Alpha", "Gamma"]  # newest first


def test_results_group_by_cpv(tmp_path, monkeypatch):
    import re
    import time
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "cp.db")
    conn = db.connect(p)
    db.init_schema(conn)
    ConfigStore(conn).reload()
    now = time.time()
    _add_dated(conn, "a", "Alpha", "2026-06-10", "2026-08-01", "32000000-3", now)
    _add_dated(conn, "b", "Beta", "2026-06-20", "2026-07-01", "30100000-0", now)
    conn.commit()
    conn.close()
    h = TestClient(create_app(p)).get("/results?sort=cpv").text
    headers = re.findall(r'cpv-h">([0-9-]+)', h)
    assert headers == ["30100000-0", "32000000-3"]


def test_source_field_always_present(tmp_path, monkeypatch):
    import time
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "src.db")
    conn = db.connect(p)
    db.init_schema(conn)
    ConfigStore(conn).reload()
    now = time.time()
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                 "status,created_at,updated_at) VALUES('mtender','ocds-b3wdp1-MD-1','h',?,'analyzed',?,?)",
                 ('{"title":"CCTV","documents":[{"title":"c.pdf","url":"http://x/c.pdf"}]}', now, now))
    tid = conn.execute("SELECT id FROM tenders").fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) "
                 "VALUES(?,?,?,?,?)", (tid, "applicability", "can", 80, now))
    conn.commit()
    conn.close()
    c = TestClient(create_app(p))
    link = "https://mtender.gov.md/tenders/ocds-b3wdp1-MD-1"
    d = c.get(f"/tender?id={tid}").text
    assert ">source<" in d and link in d and "c.pdf" in d   # source field + docs both present
    res = c.get("/results").text
    assert "Source:" in res and link in res and "c.pdf" in res
