from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from workflows import analysis
import workflows  # noqa: F401
def _db(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    store = ConfigStore(conn); store.reload()
    store.seed_defaults(Path(__file__).resolve().parent.parent/"config"/"defaults")
    return p, conn, store
def _add(conn, ext, origin, status, created_ago=1, nj='{"title":"x"}', verdict=None, stage="applicability"):
    now = time.time() - created_ago*86400
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at) VALUES('mtender',?,?,?,?,?,?,?)", (ext,"h",nj,status,origin,now,now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    if verdict:
        conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) VALUES(?,?,?,?,?)", (tid,stage,verdict,80,time.time()))
    conn.commit(); return tid
def _status(conn, tid): return conn.execute("SELECT status FROM tenders WHERE id=?", (tid,)).fetchone()["status"]
def test_reset_not_new_protects_new(tmp_path):
    p, conn, store = _db(tmp_path,"r.db")
    nid=_add(conn,"new1","incremental","analyzed",verdict="can"); hid=_add(conn,"hist1","backfill","analyzed",created_ago=30,verdict="can")
    assert analysis.reset_analysis(conn, store=store, scope="not_new")==1
    assert _status(conn,nid)=="analyzed" and _status(conn,hid)=="new"
def test_reset_all_still_resets_everything(tmp_path):
    p, conn, store = _db(tmp_path,"r2.db")
    nid=_add(conn,"new1","incremental","analyzed",verdict="can"); hid=_add(conn,"hist1","backfill","analyzed",created_ago=30,verdict="can")
    assert analysis.reset_analysis(conn, store=store, scope="all")==2
    assert _status(conn,nid)=="new" and _status(conn,hid)=="new"
def test_clear_stage_scoped(tmp_path):
    p, conn, store = _db(tmp_path,"c.db")
    nid=_add(conn,"new1","incremental","sourced",verdict="can"); hid=_add(conn,"hist1","backfill","sourced",created_ago=30,verdict="can")
    assert analysis.clear_stage(conn,"applicability",store=store,scope="not_new")==1
    assert _status(conn,nid)=="sourced" and _status(conn,hid)=="extracted"
def test_run_triage_scoped_skips_new(tmp_path):
    p, conn, store = _db(tmp_path,"t.db")
    nid=_add(conn,"new1","incremental","new"); hid=_add(conn,"hist1","backfill","new",created_ago=30)
    s = analysis.run_triage(store, conn, scope="not_new")
    assert s["total"]==1 and _status(conn,nid)=="new" and _status(conn,hid)=="triaged"
def test_analyze_page_has_scope_selector(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn, store = _db(tmp_path,"w.db"); conn.close()
    h = TestClient(create_app(p)).get("/analyze").text
    assert "Operate on" in h and "All except New" in h
def test_analyze_reset_post_protects_new(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn, store = _db(tmp_path,"wp.db")
    nid=_add(conn,"new1","incremental","analyzed",verdict="can"); hid=_add(conn,"hist1","backfill","analyzed",created_ago=30,verdict="can")
    conn.close()
    TestClient(create_app(p)).post("/analyze/reset", data={"scope":"not_new"})
    conn2 = db.connect(p)
    assert _status(conn2,nid)=="analyzed" and _status(conn2,hid)=="new"
