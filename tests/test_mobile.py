from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn); ConfigStore(conn).reload()
    return p, conn
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def test_every_user_page_ships_the_drawer(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"m1.db")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="admin")
    conn.close()
    c = _login(p)
    for path in ("/app", "/app/inbox", "/app/qualified", "/app/search", "/app/archive",
                 "/app/preferences"):
        h = c.get(path).text
        assert '<input type="checkbox" id="navtoggle"' in h, path
        assert 'for="navtoggle" class="nav-btn"' in h, path
        assert 'for="navtoggle" class="nav-scrim"' in h, path
def test_the_drawer_needs_no_javascript(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"m2.db")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    for path in ("/app", "/app/inbox", "/app/preferences"):
        h = c.get(path).text
        assert "<script" not in h.lower(), path
        assert "onclick" not in h.lower(), path
def test_viewport_meta_is_present(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"m3.db")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    h = _login(p).get("/app").text
    assert "width=device-width,initial-scale=1" in h
def test_css_carries_the_responsive_rules(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"m4.db"); conn.close()
    c = TestClient(create_app(p))
    base = c.get("/static/user/base.css").text
    assert ".nav-toggle:checked+.shell aside{transform:none}" in base
    assert "@media(max-width:900px)" in base
    assert "aside{display:none}" not in base
    comp = c.get("/static/user/components.css").text
    assert "@media(max-width:760px)" in comp
    assert "thead{display:none}" in comp
