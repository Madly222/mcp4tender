from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="user")
    conn.commit()
    return p, conn
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def _store(p):
    s = ConfigStore(db.connect(p)); s.reload(); return s
def test_company_form_replaces_the_raw_json(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"f1.db"); conn.close()
    h = _login(p).get("/app/settings/company").text
    assert "Your company" in h and 'name="verticals"' in h and 'name="vendors"' in h
    assert "capabilities.profile" not in h
def test_company_save_roundtrips_every_field(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"f2.db"); conn.close()
    c = _login(p)
    r = c.post("/app/settings/company/save", data={
        "company": "SC Rapid Link SRL", "country": "Moldova", "experience_years": "18",
        "eu_arm": "VAPEKS RO SRL", "verticals": "networks\nvideo surveillance",
        "services": "integration\nmaintenance", "certifications": "ISO 9001\nISO 27001",
        "references": "STISC", "vendors": "Cisco = Premier\nFortinet = Advocate",
        "partner_network": "DERMALOG", "notes": "B2G only"})
    assert r.status_code == 303 and "saved=" in r.headers["location"]
    prof = _store(p).get("capabilities.profile")
    assert prof["company"] == "SC Rapid Link SRL" and prof["experience_years"] == 18
    assert prof["verticals"] == ["networks", "video surveillance"]
    assert prof["certifications"] == ["ISO 9001", "ISO 27001"]
    assert prof["vendor_partnerships"] == {"Cisco": "Premier", "Fortinet": "Advocate"}
    assert prof["notes"] == "B2G only"
def test_keywords_form_shows_weights_and_saves(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"f3.db"); conn.close()
    c = _login(p)
    h = c.get("/app/settings/relevance").text
    assert "Search keywords" in h and 'name="kw0"' in h
    assert "triage.keyword_weights" not in h
    assert "triage.cpv_weights" in h
    r = c.post("/app/settings/keywords/save", data={
        "kw0": "Cisco", "wt0": "5", "kw1": "curatenie", "wt1": "-4",
        "kw2": "", "wt2": "", "kw3": "fortinet", "wt3": "3.5"})
    assert "saved=" in r.headers["location"]
    kw = _store(p).get("triage.keyword_weights")
    assert kw == {"cisco": 5, "curatenie": -4, "fortinet": 3.5}
def test_empty_keyword_save_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"f4.db"); conn.close()
    before = _store(p).get("triage.keyword_weights")
    r = _login(p).post("/app/settings/keywords/save", data={"kw0": "", "wt0": ""})
    assert "err=" in r.headers["location"]
    assert _store(p).get("triage.keyword_weights") == before
def test_apikey_form_never_leaks_the_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-SUPERSECRETVALUE-9f2a")
    p, conn = _fresh(tmp_path,"f5.db"); conn.close()
    h = _login(p).get("/app/settings/ai").text
    assert "SUPERSECRETVALUE" not in h
    assert "Your Anthropic API key" in h and ">set</span>" in h
    assert 'type="password"' in h
def test_apikey_missing_is_shown(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("TENDERENGINE_HOME", str(tmp_path))
    p, conn = _fresh(tmp_path,"f6.db"); conn.close()
    h = _login(p).get("/app/settings/ai").text
    assert ">missing</span>" in h
def test_apikey_rejects_junk(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    monkeypatch.setenv("TENDERENGINE_HOME", str(tmp_path))
    p, conn = _fresh(tmp_path,"f7.db"); conn.close()
    r = _login(p).post("/app/settings/apikey/save", data={"api_key": "hello"})
    assert "err=" in r.headers["location"]
    assert "does+not+look+like" in r.headers["location"] or "does%20not%20look" in r.headers["location"]
def test_apikey_test_persists_the_result(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    monkeypatch.setenv("TENDERENGINE_HOME", str(tmp_path))
    from engine import health
    monkeypatch.setattr(health, "check_api_key",
                        lambda **k: {"status": "fail", "code": "auth",
                                     "detail": "The API key is rejected.", "raw": "401"})
    p, conn = _fresh(tmp_path,"f8.db"); conn.close()
    c = _login(p)
    r = c.post("/app/settings/apikey/test", data={"api_key": ""})
    assert "err=" in r.headers["location"]
    chk = _store(p).get("llm.last_key_check")
    assert chk["status"] == "fail" and chk["code"] == "auth"
    assert "Last test failed" in c.get("/app/settings/ai").text
def test_read_only_blocks_the_friendly_forms(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"f9.db")
    ConfigStore(conn).set("web.read_only", True); conn.commit(); conn.close()
    c = _login(p)
    before = _store(p).get("capabilities.profile")
    r = c.post("/app/settings/company/save", data={"company": "Hacked"})
    assert "err=" in r.headers["location"]
    assert _store(p).get("capabilities.profile") == before
