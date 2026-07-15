from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from web.user.nav import is_on
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn); ConfigStore(conn).reload()
    return p, conn
def _ago(days): return time.time() - days*86400
def _add(conn, ext, nj, origin="incremental", created_at=None, verdict="can"):
    now = created_at if created_at is not None else time.time()
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at) VALUES('mtender',?,?,?,'analyzed',?,?,?)",
                 (ext,"h",nj,origin,now,now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) VALUES(?,'applicability',?,80,?)", (tid,verdict,time.time()))
    conn.commit(); return tid
def test_static_is_served_and_cached(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"s.db"); conn.close()
    c = TestClient(create_app(p))
    r = c.get("/static/user/tokens.css")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert "--acc:#4f8cff" in r.text
    again = c.get("/static/user/tokens.css", headers={"if-none-match": r.headers["etag"]})
    assert again.status_code == 304
def test_static_rejects_traversal_and_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"s2.db"); conn.close()
    c = TestClient(create_app(p))
    assert c.get("/static/user/nope.css").status_code == 404
    assert c.get("/static/../server.py").status_code == 404
def test_static_needs_no_login(tmp_path, monkeypatch):
    monkeypatch.setenv("TENDERENGINE_WEB_TOKEN", "secret")
    p, conn = _fresh(tmp_path,"s3.db"); conn.close()
    c = TestClient(create_app(p))
    assert c.get("/app").status_code == 401
    assert c.get("/static/user/base.css").status_code == 200
def test_shell_renders_with_nav_and_counts(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"a.db")
    _add(conn,"n1",json.dumps({"title":"FreshOne"}),created_at=_ago(1))
    _add(conn,"h1",json.dumps({"title":"OldOne"}),origin="backfill",created_at=_ago(30))
    conn.close()
    h = TestClient(create_app(p)).get("/app").text
    assert 'class="shell"' in h and 'href="/static/user/tokens.css' in h
    assert "Tender inbox" in h and "Qualified" in h and "Engine admin" in h
    assert "Today at a glance" in h
    assert '<span class="badge num">1</span>' in h
def test_admin_pages_untouched(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"b.db"); conn.close()
    h = TestClient(create_app(p)).get("/results?tab=new").text
    assert 'class="shell"' not in h and "Sort by:" in h
def test_is_on_matches_query():
    assert is_on("/app", "/app", "")
    assert not is_on("/app", "/app/inbox", "")
    assert is_on("/app/qualified?stage=submitted", "/app/qualified", "stage=submitted")
    assert not is_on("/app/qualified?stage=submitted", "/app/qualified", "stage=skipped")
