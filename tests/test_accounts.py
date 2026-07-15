from __future__ import annotations
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app

DEFAULTS = Path(__file__).resolve().parent.parent / "config" / "defaults"

PW = "correct horse battery"


def _db(tmp_path, name="a.db"):
    conn = db.connect(str(tmp_path / name))
    db.init_schema(conn)
    s = ConfigStore(conn)
    s.reload()
    s.seed_defaults(DEFAULTS)
    return conn


def _app(tmp_path, name="w.db"):
    p = str(tmp_path / name)
    conn = db.connect(p)
    db.init_schema(conn)
    s = ConfigStore(conn)
    s.reload()
    s.seed_defaults(DEFAULTS)
    conn.close()
    return p


# ---------------------------------------------------------------- passwords

def test_hash_is_not_plaintext_and_salted():
    a = accounts.hash_password(PW)
    b = accounts.hash_password(PW)
    assert PW not in a
    assert a != b                      # different salt each time
    assert accounts.verify_password(PW, a)
    assert accounts.verify_password(PW, b)


def test_verify_rejects_wrong_and_garbage():
    h = accounts.hash_password(PW)
    assert not accounts.verify_password("wrong", h)
    assert not accounts.verify_password(PW, "not-a-hash")
    assert not accounts.verify_password(PW, "")


# ---------------------------------------------------------------- accounts

def test_create_and_get(tmp_path):
    conn = _db(tmp_path)
    accounts.create(conn, "RapidLink", PW, company="SC Rapid Link SRL")
    row = accounts.get(conn, "rapidlink")
    assert row["login"] == "rapidlink"          # normalised
    assert row["company"] == "SC Rapid Link SRL"
    assert row["active"] == 1
    assert PW not in row["password_hash"]
    assert accounts.count(conn) == 1


def test_login_is_case_insensitive(tmp_path):
    conn = _db(tmp_path)
    accounts.create(conn, "rapidlink", PW)
    assert accounts.authenticate(conn, "RapidLink", PW)
    assert accounts.authenticate(conn, "  RAPIDLINK ", PW)


def test_duplicate_and_short_password_rejected(tmp_path):
    conn = _db(tmp_path)
    accounts.create(conn, "a1", PW)
    for bad in (lambda: accounts.create(conn, "a1", PW),
                lambda: accounts.create(conn, "a2", "short"),
                lambda: accounts.create(conn, "", PW)):
        try:
            bad()
            assert False, "should have raised"
        except ValueError:
            pass


def test_authenticate(tmp_path):
    conn = _db(tmp_path)
    accounts.create(conn, "a1", PW)
    assert accounts.authenticate(conn, "a1", PW)
    assert accounts.authenticate(conn, "a1", "nope") is None
    assert accounts.authenticate(conn, "ghost", PW) is None


def test_disabled_account_cannot_authenticate(tmp_path):
    conn = _db(tmp_path)
    accounts.create(conn, "a1", PW)
    accounts.set_active(conn, "a1", False)
    assert accounts.authenticate(conn, "a1", PW) is None


def test_delete(tmp_path):
    conn = _db(tmp_path)
    accounts.create(conn, "a1", PW)
    accounts.delete(conn, "a1")
    assert accounts.count(conn) == 0


# ---------------------------------------------------------------- sessions

def test_session_roundtrip(tmp_path):
    conn = _db(tmp_path)
    a = accounts.create(conn, "a1", PW)
    sid = accounts.new_session(conn, a["id"])
    assert accounts.session_account(conn, sid)["login"] == "a1"
    accounts.end_session(conn, sid)
    assert accounts.session_account(conn, sid) is None
    assert accounts.session_account(conn, "bogus") is None
    assert accounts.session_account(conn, None) is None


def test_expired_session_rejected(tmp_path):
    conn = _db(tmp_path)
    a = accounts.create(conn, "a1", PW)
    sid = accounts.new_session(conn, a["id"], days=-1)
    assert accounts.session_account(conn, sid) is None


def test_password_change_signs_out_sessions(tmp_path):
    conn = _db(tmp_path)
    a = accounts.create(conn, "a1", PW)
    sid = accounts.new_session(conn, a["id"])
    accounts.set_password(conn, "a1", "a brand new password")
    assert accounts.session_account(conn, sid) is None
    assert accounts.authenticate(conn, "a1", "a brand new password")


def test_disabling_signs_out_sessions(tmp_path):
    conn = _db(tmp_path)
    a = accounts.create(conn, "a1", PW)
    sid = accounts.new_session(conn, a["id"])
    accounts.set_active(conn, "a1", False)
    assert accounts.session_account(conn, sid) is None


# ---------------------------------------------------------------- throttling

def test_lockout_after_repeated_failures(tmp_path):
    conn = _db(tmp_path)
    ip = "1.2.3.4"
    assert not accounts.is_locked(conn, ip)
    for _ in range(accounts.MAX_FAILS):
        accounts.record_attempt(conn, ip, False)
    assert accounts.is_locked(conn, ip)
    assert not accounts.is_locked(conn, "5.6.7.8")     # per-IP, not global


def test_success_clears_failures(tmp_path):
    conn = _db(tmp_path)
    ip = "1.2.3.4"
    for _ in range(3):
        accounts.record_attempt(conn, ip, False)
    accounts.record_attempt(conn, ip, True)
    assert accounts.failures(conn, ip) == 0


def test_old_failures_fall_out_of_window(tmp_path):
    conn = _db(tmp_path)
    conn.execute("INSERT INTO login_attempts(ip,at) VALUES('1.2.3.4',?)",
                 (time.time() - accounts.LOCK_WINDOW - 60,))
    conn.commit()
    assert accounts.failures(conn, "1.2.3.4") == 0


# ---------------------------------------------------------------- web flow

def test_token_mode_when_no_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("TENDERENGINE_WEB_TOKEN", "secret123")
    c = TestClient(create_app(_app(tmp_path)))
    r = c.get("/")
    assert r.status_code == 401
    assert "protected by token" in r.text
    assert "name=login" not in r.text


def test_accounts_mode_shows_login_and_password(tmp_path, monkeypatch):
    monkeypatch.setenv("TENDERENGINE_WEB_TOKEN", "secret123")
    p = _app(tmp_path)
    conn = db.connect(p)
    accounts.create(conn, "a1", PW, company="Acme")
    conn.close()
    r = TestClient(create_app(p)).get("/")
    assert r.status_code == 401
    assert "name=login" in r.text and "name=password" in r.text
    # explicit type=text: the CSS selector is input[type=text], an input with no
    # type attribute goes unstyled and looks different from the password box
    assert "type=text name=login" in r.text
    assert "protected by token" not in r.text


def test_accounts_mode_ignores_token(tmp_path, monkeypatch):
    """Once accounts exist the old token must not open the door."""
    monkeypatch.setenv("TENDERENGINE_WEB_TOKEN", "secret123")
    p = _app(tmp_path)
    conn = db.connect(p)
    accounts.create(conn, "a1", PW)
    conn.close()
    c = TestClient(create_app(p))
    assert c.get("/?token=secret123").status_code == 401
    r = c.post("/login", data={"token": "secret123"}, follow_redirects=False)
    assert r.status_code == 401


def test_login_success_sets_session_and_grants_access(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = _app(tmp_path)
    conn = db.connect(p)
    accounts.create(conn, "a1", PW, company="Acme")
    conn.close()
    c = TestClient(create_app(p))
    r = c.post("/login", data={"login": "a1", "password": PW}, follow_redirects=False)
    assert r.status_code == 303
    assert "te_session" in r.cookies
    assert c.get("/").status_code == 200          # cookie carried by the client


def test_login_failure(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = _app(tmp_path)
    conn = db.connect(p)
    accounts.create(conn, "a1", PW)
    conn.close()
    c = TestClient(create_app(p))
    r = c.post("/login", data={"login": "a1", "password": "wrong"}, follow_redirects=False)
    assert r.status_code == 401
    assert "Wrong login or password" in r.text
    assert "te_session" not in r.cookies


def test_web_lockout(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = _app(tmp_path)
    conn = db.connect(p)
    accounts.create(conn, "a1", PW)
    conn.close()
    c = TestClient(create_app(p))
    for _ in range(accounts.MAX_FAILS):
        c.post("/login", data={"login": "a1", "password": "wrong"}, follow_redirects=False)
    r = c.post("/login", data={"login": "a1", "password": PW}, follow_redirects=False)
    assert r.status_code == 401
    assert "Too many failed attempts" in r.text      # right password, still locked


def test_logout(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = _app(tmp_path)
    conn = db.connect(p)
    accounts.create(conn, "a1", PW)
    conn.close()
    c = TestClient(create_app(p))
    c.post("/login", data={"login": "a1", "password": PW}, follow_redirects=False)
    assert c.get("/").status_code == 200
    c.get("/logout", follow_redirects=False)
    assert c.get("/").status_code == 401


def test_signed_in_company_shown_in_header(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = _app(tmp_path)
    conn = db.connect(p)
    accounts.create(conn, "a1", PW, company="SC Rapid Link SRL")
    conn.close()
    c = TestClient(create_app(p))
    c.post("/login", data={"login": "a1", "password": PW}, follow_redirects=False)
    h = c.get("/").text
    assert "SC Rapid Link SRL" in h and "/logout" in h
