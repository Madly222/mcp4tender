from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app


def _app(tmp_path):
    p = str(tmp_path / "s.db")
    conn = db.connect(p)
    db.init_schema(conn)
    s = ConfigStore(conn)
    s.seed_defaults("config/defaults")
    s.reload()
    return p, conn


def test_user_settings_renders_fields_not_json(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, _ = _app(tmp_path)
    h = TestClient(create_app(p)).get("/user-settings").text
    assert "User Settings" in h and "Your company" in h
    assert 'name="company"' in h and "SC Rapid Link SRL" in h
    assert 'class="help"' in h                      # per-option ? tooltips
    assert 'name="verticals"' in h and 'name="relevant"' in h
    assert "edit as JSON" not in h                  # no raw JSON editing


def test_user_settings_company_roundtrip(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, _ = _app(tmp_path)
    c = TestClient(create_app(p))
    c.post("/user-settings/company", data={
        "company": "New Co", "country": "MD", "experience_years": "12", "eu_arm": "",
        "verticals": "cctv\ndrones", "services": "supply", "certifications": "ISO 9001",
        "references": "IGPF", "partner_network": "Elbit", "notes": "hi",
        "vendors": "Cisco = networking\nDell = servers"}, follow_redirects=False)
    s = ConfigStore(db.connect(p)); s.reload()
    prof = s.get("capabilities.profile")
    assert prof["company"] == "New Co" and prof["experience_years"] == 12
    assert prof["verticals"] == ["cctv", "drones"]
    assert prof["vendor_partnerships"] == {"Cisco": "networking", "Dell": "servers"}


def test_user_settings_keywords_and_tuning_roundtrip(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, _ = _app(tmp_path)
    c = TestClient(create_app(p))
    c.post("/user-settings/keywords", data={"kw0": "drone", "wt0": "5",
           "kw1": "mobilier", "wt1": "-3", "kw2": "", "wt2": ""}, follow_redirects=False)
    c.post("/user-settings/tuning", data={"relevant": "4", "gray": "1", "value_min": "6000",
           "value_pen": "-2", "max_age": "60", "batch": "25"}, follow_redirects=False)
    s = ConfigStore(db.connect(p)); s.reload()
    assert s.get("triage.keyword_weights") == {"drone": 5, "mobilier": -3}
    assert s.get("triage.bucket_thresholds") == {"relevant": 4, "gray": 1}
    assert s.get("collect.max_age_days") == 60 and s.get("analyze.batch_size") == 25
