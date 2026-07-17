from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from web.user import dictforms
from web.user.forms import HANDLED
from web.user.settings_meta import section_of, vtype_of
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="user")
    conn.commit(); return p, conn
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def _store(p):
    s = ConfigStore(db.connect(p)); s.reload(); return s
def test_no_raw_json_is_left_anywhere(tmp_path):
    p, conn = _fresh(tmp_path,"d0.db")
    s = ConfigStore(conn); s.reload()
    handled = {k for v in HANDLED.values() for k in v} | set(dictforms.SPECS)
    left = sorted(k for k, v in s.all().items()
                  if section_of(k) and k not in handled and vtype_of(v) == "json")
    assert left == [], f"still a JSON textarea: {left}"
    conn.close()
def test_every_spec_key_belongs_to_a_section():
    for key in dictforms.SPECS:
        assert section_of(key) is not None, key
def test_cpv_weights_render_as_rows_not_json(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d1.db"); conn.close()
    h = _login(p).get("/app/settings/relevance").text
    assert "CPV weights" in h and 'name="k0"' in h and 'name="v0"' in h
    assert "Score cut-offs" in h and 'name="f_relevant"' in h
    assert "Value band" in h and 'name="f_weight_below_min"' in h
    assert "Tenders below this value are penalised" in h
def test_saving_pairs(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d2.db"); conn.close()
    r = _login(p).post("/app/settings/kv/save", data={
        "key": "triage.cpv_weights", "k0": "32", "v0": "3", "k1": "45", "v1": "-2",
        "k2": "", "v2": "9"})
    assert "saved=" in r.headers["location"]
    assert _store(p).get("triage.cpv_weights") == {"32": 3, "45": -2}
def test_empty_pairs_are_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d3.db"); conn.close()
    before = _store(p).get("triage.cpv_weights")
    r = _login(p).post("/app/settings/kv/save", data={"key": "triage.cpv_weights",
                                                      "k0": "", "v0": ""})
    assert "err=" in r.headers["location"]
    assert _store(p).get("triage.cpv_weights") == before
def test_fields_keep_their_types(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d4.db"); conn.close()
    r = _login(p).post("/app/settings/kv/save", data={
        "key": "sources.mtender", "f_enabled": "on", "f_timeout": "45",
        "f_list_url": "https://example.md/t", "f_page_limit": "5",
        "f_max_records_per_run": "80", "f_backfill_days": "20",
        "f_record_url_template": "https://x/{ocid}", "f_portal_url_template": "https://y/{ocid}"})
    assert "saved=" in r.headers["location"]
    v = _store(p).get("sources.mtender")
    assert v["enabled"] is True and v["timeout"] == 45 and isinstance(v["timeout"], int)
    assert v["list_url"] == "https://example.md/t"
def test_unticked_field_switch_means_off(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d5.db"); conn.close()
    c = _login(p)
    c.post("/app/settings/kv/save", data={"key": "sources.mtender", "f_enabled": "on"})
    assert _store(p).get("sources.mtender")["enabled"] is True
    c.post("/app/settings/kv/save", data={"key": "sources.mtender"})
    assert _store(p).get("sources.mtender")["enabled"] is False
def test_fields_never_invent_new_subkeys(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d6.db"); conn.close()
    before = set(_store(p).get("sources.mtender"))
    _login(p).post("/app/settings/kv/save", data={"key": "sources.mtender", "f_evil": "x"})
    assert set(_store(p).get("sources.mtender")) == before
def test_pricing_table(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d7.db"); conn.close()
    c = _login(p)
    h = c.get("/app/settings/ai").text
    assert "Model prices" in h and 'name="c0_in"' in h and 'name="c0_out"' in h
    assert "Model per stage" in h
    r = c.post("/app/settings/kv/save", data={
        "key": "llm.pricing", "k0": "claude-sonnet-5", "c0_in": "3", "c0_out": "15",
        "k1": "", "c1_in": "9", "c1_out": "9"})
    assert "saved=" in r.headers["location"]
    assert _store(p).get("llm.pricing") == {"claude-sonnet-5": {"in": 3, "out": 15}}
def test_unknown_key_is_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d8.db"); conn.close()
    r = _login(p).post("/app/settings/kv/save", data={"key": "web.port", "k0": "x", "v0": "1"})
    assert r.headers["location"] == "/app/settings"
def test_read_only_blocks_dict_forms(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d9.db")
    ConfigStore(conn).set("web.read_only", True); conn.commit(); conn.close()
    before = _store(p).get("triage.cpv_weights")
    r = _login(p).post("/app/settings/kv/save", data={"key": "triage.cpv_weights",
                                                      "k0": "99", "v0": "9"})
    assert "err=" in r.headers["location"]
    assert _store(p).get("triage.cpv_weights") == before
