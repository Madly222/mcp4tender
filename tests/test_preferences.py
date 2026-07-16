from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest
from engine import accounts, db, user_settings
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    return p, conn
def _login(p, login="rl"):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": login, "password": "password1"}).status_code == 303
    return c
def test_only_look_and_feel_lives_here():
    assert set(user_settings.KEYS) == {"ui.theme"}
    assert "results.new_days" not in user_settings.KEYS
def test_clean_rejects_junk():
    assert user_settings.clean("ui.theme", "light") == "light"
    with pytest.raises(ValueError):
        user_settings.clean("ui.theme", "neon")
    with pytest.raises(ValueError):
        user_settings.clean("results.new_days", 10)
def test_default_is_dark(tmp_path):
    p, conn = _fresh(tmp_path,"t0.db")
    assert user_settings.effective(conn, 1)["ui.theme"] == "dark"
    conn.close()
def test_theme_is_per_account(tmp_path):
    p, conn = _fresh(tmp_path,"t1.db")
    user_settings.set_many(conn, 1, {"ui.theme": "light"})
    assert user_settings.effective(conn, 1)["ui.theme"] == "light"
    assert user_settings.effective(conn, 2)["ui.theme"] == "dark"
    conn.close()
def test_junk_in_the_db_falls_back_to_default(tmp_path):
    p, conn = _fresh(tmp_path,"t2.db")
    conn.execute("INSERT INTO account_settings(account_id,key,value,updated_at)"
                 " VALUES(1,'ui.theme','neon',0)")
    conn.commit()
    assert user_settings.effective(conn, 1)["ui.theme"] == "dark"
    conn.close()
def test_switching_theme_changes_the_html_attribute(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"t3.db")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="user")
    conn.close()
    c = _login(p)
    assert 'data-theme="dark"' in c.get("/app").text
    c.post("/app/preferences", data={"ui.theme": "light"})
    for page in ("/app", "/app/inbox", "/app/settings", "/app/preferences"):
        assert 'data-theme="light"' in c.get(page).text, page
    c.post("/app/preferences", data={"reset": "1"})
    assert 'data-theme="dark"' in c.get("/app").text
def test_admin_pages_follow_the_same_theme(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"t4.db")
    accounts.create(conn, "admin22", "password1", role="admin"); conn.close()
    c = _login(p, "admin22")
    c.post("/app/preferences", data={"ui.theme": "light"})
    assert 'data-theme="light"' in c.get("/").text
    assert 'data-theme="light"' in c.get("/config").text
def test_light_palette_exists_and_overrides_the_dark_one(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"t5.db"); conn.close()
    css = TestClient(create_app(p)).get("/static/tokens.css").text
    assert ':root[data-theme="light"]' in css
    for token in ("--bg:", "--surface:", "--fg:", "--acc:", "--line:", "--topbar-bg:",
                  "--mut:", "--ok:", "--warn:", "--bad:", "--mark-2:"):
        assert css.count(token) >= 2, f"{token} has no light override"
def test_no_hardcoded_dark_left_in_the_shell(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"t6.db"); conn.close()
    base = TestClient(create_app(p)).get("/static/user/base.css").text
    assert "rgba(10,13,18" not in base, "the topbar background must come from --topbar-bg"
    assert "#8a5cff" not in base, "the brand gradient must come from --mark-2"
def test_page_points_at_company_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"t7.db")
    accounts.create(conn, "rl", "password1", role="user"); conn.close()
    h = _login(p).get("/app/preferences").text
    assert "Looking for the engine?" in h and 'href="/app/settings"' in h
    assert "new_days" not in h and "archive_after_days" not in h
    assert "How it looks to you" in h
def test_theme_survives_token_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"t8.db"); conn.close()
    assert 'data-theme="dark"' in TestClient(create_app(p)).get("/").text
