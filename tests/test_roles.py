from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.roles import landing_for, may_visit
from web.server import create_app
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn); ConfigStore(conn).reload()
    return p, conn
def _client(p, login, password):
    c = TestClient(create_app(p), follow_redirects=False)
    r = c.post("/login", data={"login": login, "password": password})
    assert r.status_code == 303, r.status_code
    return c, r.headers["location"]
def test_first_account_is_forced_admin(tmp_path):
    p, conn = _fresh(tmp_path,"r1.db")
    row = accounts.create(conn, "rapidlink", "password1", company="SC Rapid Link SRL", role="user")
    assert accounts.role_of(row) == "admin"
    second = accounts.create(conn, "acme", "password1", company="Acme", role="user")
    assert accounts.role_of(second) == "user"
    conn.close()
def test_legacy_accounts_migrate_to_admin(tmp_path):
    p = str(tmp_path/"legacy.db")
    conn = db.connect(p)
    conn.executescript(db.SCHEMA_ACCOUNTS.replace("role TEXT NOT NULL DEFAULT 'user',", ""))
    conn.execute("INSERT INTO accounts(login,password_hash,company,active,created_at)"
                 " VALUES('old','x','Old Co',1,0)")
    conn.commit()
    db.init_schema(conn)
    assert accounts.role_of(accounts.get(conn, "old")) == "admin"
    conn.close()
def test_last_admin_cannot_be_demoted(tmp_path):
    p, conn = _fresh(tmp_path,"r2.db")
    accounts.create(conn, "admin22", "password1", role="admin")
    with pytest.raises(ValueError):
        accounts.set_role(conn, "admin22", "user")
    accounts.create(conn, "second", "password1", role="admin")
    accounts.set_role(conn, "admin22", "user")
    assert accounts.role_of(accounts.get(conn, "admin22")) == "user"
    conn.close()
def test_demoting_kills_live_sessions(tmp_path):
    p, conn = _fresh(tmp_path,"r3.db")
    accounts.create(conn, "admin22", "password1", role="admin")
    row = accounts.create(conn, "rapidlink", "password1", role="admin")
    sid = accounts.new_session(conn, row["id"])
    assert accounts.session_account(conn, sid) is not None
    accounts.set_role(conn, "rapidlink", "user")
    assert accounts.session_account(conn, sid) is None
    conn.close()
def test_user_lands_on_app_and_admin_on_root(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"r4.db")
    accounts.create(conn, "admin22", "password1", role="admin")
    accounts.create(conn, "rapidlink", "password1", company="SC Rapid Link SRL", role="user")
    conn.close()
    _, admin_to = _client(p, "admin22", "password1")
    _, user_to = _client(p, "rapidlink", "password1")
    assert admin_to == "/" and user_to == "/app"
def test_user_is_kept_out_of_admin_pages(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"r5.db")
    accounts.create(conn, "admin22", "password1", role="admin")
    accounts.create(conn, "rapidlink", "password1", company="SC Rapid Link SRL", role="user")
    conn.close()
    c, _ = _client(p, "rapidlink", "password1")
    assert c.get("/", follow_redirects=False).headers["location"] == "/app"
    for path in ("/config", "/sites", "/user-settings", "/analyze", "/results"):
        r = c.get(path)
        assert r.status_code == 403, path
        assert "Not available on your account" in r.text
    assert c.get("/app").status_code == 200
    assert c.get("/static/user/tokens.css").status_code == 200
def test_admin_keeps_full_access(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"r6.db")
    accounts.create(conn, "admin22", "password1", role="admin")
    conn.close()
    c, _ = _client(p, "admin22", "password1")
    for path in ("/", "/config", "/sites", "/results", "/app"):
        assert c.get(path).status_code == 200, path
def test_admin_link_hidden_from_users(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"r7.db")
    accounts.create(conn, "admin22", "password1", role="admin")
    accounts.create(conn, "rapidlink", "password1", company="SC Rapid Link SRL", role="user")
    conn.close()
    cu, _ = _client(p, "rapidlink", "password1")
    ca, _ = _client(p, "admin22", "password1")
    user_page = cu.get("/app").text
    admin_page = ca.get("/app").text
    assert "Engine admin" not in user_page and "Company account" in user_page
    assert "SC Rapid Link SRL" in user_page
    assert "Engine admin" in admin_page and "Administrator" in admin_page
def test_token_mode_keeps_legacy_full_access():
    assert may_visit(None, "/app") and may_visit(None, "/config") and may_visit(None, "/")
    assert landing_for(None) == "/"
def test_user_row_is_confined_to_the_user_zone():
    row = {"role": "user"}
    assert may_visit(row, "/app") and may_visit(row, "/app/inbox")
    assert may_visit(row, "/static/user/base.css") and may_visit(row, "/logout")
    assert not may_visit(row, "/config") and not may_visit(row, "/")
    assert landing_for(row) == "/app"
