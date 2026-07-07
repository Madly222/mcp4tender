from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app


def _app(tmp_path):
    p = str(tmp_path / "s.db")
    conn = db.connect(p)
    db.init_schema(conn)
    ConfigStore(conn).reload()
    now = time.time()
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                 "status,created_at,updated_at) VALUES('mtender','ocds-x','h',?,'analyzed',?,?)",
                 ('{"title":"TELECOM"}', now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id='ocds-x'").fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) "
                 "VALUES(?,?,?,?,?)", (tid, "applicability", "can", 80, now))
    conn.execute("INSERT INTO stage_runs(run_id,tender_id,stage_name,status,tokens,cost,"
                 "started_at,finished_at) VALUES(?,?,?,?,?,?,?,?)",
                 ("r1", tid, "applicability", "done", 1200, 0.01, now, now + 2))
    conn.commit()
    return p, tid


def test_stage_pages_render(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, _ = _app(tmp_path)
    c = TestClient(create_app(p))
    for stage in ("triage", "extract", "applicability", "suppliers"):
        r = c.get(f"/stage/{stage}")
        assert r.status_code == 200 and "how it works" in r.text


def test_stage_detail_and_search_by_id(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, tid = _app(tmp_path)
    c = TestClient(create_app(p))
    d = c.get(f"/stage/applicability?id={tid}").text
    assert "TELECOM" in d and "Run log" in d and "1200" in d
    s = c.get(f"/stage/applicability?q={tid}").text
    assert f"#{tid}" in s


def test_removed_tabs_gone(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, _ = _app(tmp_path)
    c = TestClient(create_app(p))
    for path in ("/stages", "/coverage", "/runs", "/verifications", "/audit"):
        assert c.get(path, follow_redirects=False).status_code == 404
    nav = c.get("/tenders").text
    assert ">Extract<" in nav and ">Coverage<" not in nav


def test_stage_step_trace_captured_and_rendered(tmp_path, monkeypatch):
    import json
    from engine.config_store import ConfigStore
    from engine.runner import run_pipeline
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "st.db")
    conn = db.connect(p)
    db.init_schema(conn)
    s = ConfigStore(conn)
    s.seed_defaults("config/defaults")
    s.reload()
    now = time.time()
    nj = {"title": "Canc", "value_amount": 2316.66,
          "cpv": [{"id": "30100000-0", "description": "birou"}], "documents": []}
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                 "status,created_at,updated_at) VALUES('mtender','o46','h',?,'triaged',?,?)",
                 (json.dumps(nj), now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id='o46'").fetchone()["id"]
    run_pipeline("pipeline.tender_extract", s, conn,
                 initial_payload={"tender": nj, "tender_id": tid}, tender_id=tid)
    steps = conn.execute("SELECT label FROM stage_events WHERE tender_id=? AND stage='extract' "
                         "ORDER BY seq", (tid,)).fetchall()
    labels = [r["label"] for r in steps]
    assert "Select documents" in labels and "Build fields from metadata" in labels
    conn.close()
    h = TestClient(create_app(p)).get(f"/stage/extract?id={tid}").text
    assert "Steps — what happened" in h and "falling back to the tender" in h
