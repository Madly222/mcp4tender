from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from web.user.settings_meta import ADMIN_ONLY, SECTIONS, parse, section_of, vtype_of
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    return p, conn
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def test_vtype_puts_bool_before_int():
    assert vtype_of(True) == "bool"
    assert vtype_of(1) == "int"
    assert vtype_of(1.5) == "float"
    assert vtype_of("x") == "str"
    assert vtype_of(["a", "b"]) == "list_str"
    assert vtype_of({"a": 1}) == "json"
    assert vtype_of([1, 2]) == "json"
def test_parse_roundtrips():
    assert parse("bool", None) is False
    assert parse("bool", "on") is True
    assert parse("int", " 7 ") == 7
    assert parse("list_str", "a, b ,c") == ["a", "b", "c"]
    assert parse("json", '{"a":1}') == {"a": 1}
    with pytest.raises(Exception):
        parse("int", "abc")
    with pytest.raises(Exception):
        parse("json", "{oops")
def test_web_keys_are_never_offered_to_a_company():
    assert "web" in ADMIN_ONLY
    for key in ("web.port", "web.host", "web.token", "web.read_only", "web.run_scheduler"):
        assert section_of(key) is None, key
def test_every_section_prefix_is_unique():
    seen = set()
    for _sid, _l, _i, _b, prefixes in SECTIONS:
        for p in prefixes:
            assert p not in seen, p
            seen.add(p)
def test_hub_lists_sections_and_explains_the_gap(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"s1.db")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="user")
    conn.close()
    h = _login(p).get("/app/settings").text
    for label in ("Company profile", "What counts as relevant", "Suppliers and margins",
                  "Where we look", "When we look", "AI models and cost", "Engine internals"):
        assert label in h, label
    assert "Not here on purpose" in h and "cut off the branch" in h
def test_a_user_role_can_reach_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"s2.db")
    accounts.create(conn, "admin22", "password1", role="admin")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="user")
    conn.close()
    c = _login(p)
    assert c.get("/app/settings").status_code == 200
    assert c.get("/app/settings/company").status_code == 200
    assert c.get("/config").status_code == 403
def test_section_shows_keys_with_descriptions(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"s3.db")
    accounts.create(conn, "rl", "password1", role="user"); conn.close()
    h = _login(p).get("/app/settings/relevance").text
    assert "triage.cpv_weights" in h and "triage.value_band" in h
    assert "Score added per CPV code prefix" in h
    assert "capabilities.profile" not in h
    assert "triage.keyword_weights" not in h, "the friendly form owns this key now"
    assert "Everything else here" in h
def test_saving_a_scalar_and_a_json_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"s4.db")
    accounts.create(conn, "rl", "password1", role="user"); conn.close()
    c = _login(p)
    r = c.post("/app/settings/save", data={"key": "results.new_days", "vtype": "int",
                                           "v": "12", "back": "/app/settings/lists"})
    assert r.status_code == 303 and "saved=" in r.headers["location"]
    r = c.post("/app/settings/save",
               data={"key": "triage.keyword_weights", "vtype": "json",
                     "v": '{"cisco": 5}', "back": "/app/settings/relevance"})
    assert "saved=" in r.headers["location"]
    conn = db.connect(p); s = ConfigStore(conn); s.reload()
    assert s.get("results.new_days") == 12
    assert s.get("triage.keyword_weights") == {"cisco": 5}
def test_bad_json_is_refused_and_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"s5.db")
    before = ConfigStore(conn); before.reload()
    original = before.get("triage.keyword_weights")
    accounts.create(conn, "rl", "password1", role="user"); conn.close()
    c = _login(p)
    r = c.post("/app/settings/save", data={"key": "triage.keyword_weights", "vtype": "json",
                                           "v": "{oops", "back": "/app/settings/relevance"})
    assert "err=" in r.headers["location"]
    conn = db.connect(p); s = ConfigStore(conn); s.reload()
    assert s.get("triage.keyword_weights") == original
def test_saving_a_web_key_through_the_user_zone_is_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"s6.db")
    accounts.create(conn, "rl", "password1", role="user"); conn.close()
    c = _login(p)
    r = c.post("/app/settings/save", data={"key": "web.port", "vtype": "int", "v": "9999",
                                           "back": "/app/settings/engine"})
    assert r.headers["location"] == "/app/settings"
    conn = db.connect(p); s = ConfigStore(conn); s.reload()
    assert s.get("web.port") != 9999
def test_read_only_blocks_settings_save(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"s7.db")
    accounts.create(conn, "rl", "password1", role="user")
    ConfigStore(conn).set("web.read_only", True); conn.commit(); conn.close()
    c = _login(p)
    r = c.post("/app/settings/save", data={"key": "results.new_days", "vtype": "int",
                                           "v": "12", "back": "/app/settings/lists"})
    assert "err=" in r.headers["location"]
    conn = db.connect(p); s = ConfigStore(conn); s.reload()
    assert s.get("results.new_days") != 12
def test_save_keeps_the_version_history(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"s8.db")
    accounts.create(conn, "rl", "password1", role="user"); conn.close()
    c = _login(p)
    c.post("/app/settings/save", data={"key": "results.new_days", "vtype": "int",
                                       "v": "11", "back": "/app/settings/lists"})
    conn = db.connect(p)
    rows = conn.execute("SELECT actor, version, active FROM configs WHERE key='results.new_days' ORDER BY version").fetchall()
    assert len(rows) >= 2, "seed + edit should both be kept"
    assert rows[-1]["actor"] == "app" and rows[-1]["active"] == 1
    assert rows[0]["active"] == 0, "the seeded version must survive for rollback"
