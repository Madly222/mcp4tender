from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app

DEFAULTS = Path(__file__).resolve().parent.parent / "config" / "defaults"


def _app(tmp_path, name="s.db"):
    p = str(tmp_path / name)
    conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults(DEFAULTS); conn.close()
    return p


def test_sections_render(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    h = TestClient(create_app(_app(tmp_path))).get("/user-settings").text
    assert ">API key<" in h and ">Models<" in h
    assert "spent last 24h" in h and "spent last 30 days" in h
    assert "applicability_gray" in h            # per-stage model row
    assert "stub provider" in h                 # missing-key issue surfaces


def test_key_never_rendered_in_full(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-SUPERSECRETVALUE-9f2a")
    h = TestClient(create_app(_app(tmp_path))).get("/user-settings").text
    assert "SUPERSECRETVALUE" not in h
    assert "9f2a" in h


def test_save_models(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    p = _app(tmp_path)
    c = TestClient(create_app(p))
    c.post("/user-settings/models", data={"model_extract": "claude-sonnet-5"})
    store = ConfigStore(db.connect(p)); store.reload()
    assert store.get("llm.models")["extract"] == "claude-sonnet-5"


def test_reject_non_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    c = TestClient(create_app(_app(tmp_path)))
    r = c.post("/user-settings/apikey", data={"api_key": "hello"}, follow_redirects=False)
    assert "does%20not%20look%20like" in r.headers["location"]


def test_blank_key_keeps_current(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    c = TestClient(create_app(_app(tmp_path)))
    r = c.post("/user-settings/apikey", data={"api_key": ""}, follow_redirects=False)
    assert "unchanged" in r.headers["location"]
