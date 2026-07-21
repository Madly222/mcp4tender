from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
def _app(tmp_path, name, gw_on=True):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    s.set("sources.genericweb", dict(s.get("sources.genericweb", {}), enabled=gw_on))
    s.set("sites.tenders", [{"id": "ach", "label": "achizitii",
                             "url": "https://achizitii.md/ro/", "enabled": True}])
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="user")
    conn.commit(); conn.close()
    return p
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def _stub_page(monkeypatch, text="tenders here", rendered=False):
    import workflows.collectors.genericweb_analyze as an
    monkeypatch.setattr(an._gw, "_page_text", lambda *a, **k: (text, rendered))
    return an
def test_a_failing_llm_gives_a_clean_error_not_a_500(tmp_path, monkeypatch):
    """The exact bug: page fetch works, the model call throws. Must redirect, not 500."""
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    an = _stub_page(monkeypatch)
    class Boom:
        def __init__(self, *a, **k): pass
        def complete(self, *a, **k): raise RuntimeError("401 invalid x-api-key")
    monkeypatch.setattr(an, "LLMGateway", Boom)
    p = _app(tmp_path, "sa1.db")
    r = _login(p).post("/app/settings/sites/analyze", data={"id": "ach"})
    assert r.status_code == 303
    assert "AI+analysis+failed" in r.headers["location"]
    assert "API+key" in r.headers["location"]
def test_analyze_renders_in_the_user_shell_on_success(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    an = _stub_page(monkeypatch, text="a page listing multiple tender notices " * 20)
    class OK:
        def __init__(self, *a, **k): pass
        def complete(self, *a, **k):
            return {"text": '{"page_type":"listing","has_tenders":true,"tender_count":7,'
                            '"needs_login":false,"recommendation":"crawl this page",'
                            '"follow":[{"label":"Achizitii mici","url":"/ro/small"}]}'}
    monkeypatch.setattr(an, "LLMGateway", OK)
    p = _app(tmp_path, "sa2.db")
    h = _login(p).post("/app/settings/sites/analyze", data={"id": "ach"},
                       follow_redirects=True).text
    assert "Site analysis" in h and "Page type" in h
    assert "listing" in h and "crawl this page" in h
    assert "Achizitii mici" in h
    assert 'href="/static/tokens.css' in h, "must be the user shell, not the admin layout"
    assert "/app/settings/sites/analyze" in h and "/sites/analyze" not in h.replace("/app/settings/sites/analyze", "")
def test_analyze_off_when_genericweb_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = _app(tmp_path, "sa3.db", gw_on=False)
    r = _login(p).post("/app/settings/sites/analyze", data={"id": "ach"})
    assert r.status_code == 303 and "off" in r.headers["location"]
def test_a_fetch_failure_is_reported(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    import workflows.collectors.genericweb_analyze as an
    def boom(*a, **k):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(an._gw, "_page_text", boom)
    p = _app(tmp_path, "sa4.db")
    r = _login(p).post("/app/settings/sites/analyze", data={"id": "ach"})
    assert r.status_code == 303 and "connection+refused" in r.headers["location"]
def test_preview_also_survives_a_bad_page(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    import workflows.collectors.genericweb_analyze as an
    monkeypatch.setattr(an, "preview_site", lambda *a, **k: {"error": "timeout"})
    p = _app(tmp_path, "sa5.db")
    r = _login(p).post("/app/settings/sites/preview", data={"id": "ach"})
    assert r.status_code == 303 and "fetch+failed" in r.headers["location"]
