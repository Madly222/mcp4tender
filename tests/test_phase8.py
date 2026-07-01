from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from engine import db
from engine.config_store import ConfigStore
from web.server import create_app


def _seed(path):
    conn = db.connect(path)
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("web.token", "")
    store.set("web.read_only", False)
    store.set("web.digest_limit", 50)
    store.set("supervisor.rank_weights", {"score": 0.6, "margin": 0.4})
    store.set("supervisor.digest_verdicts", ["can", "partial"])
    store.set("greeting.text", "salut")
    now = time.time()
    nj = json.dumps({"title": "Analizor de spectru", "buyer": "ARCOM",
                     "value_amount": 1000000, "value_currency": "MDL",
                     "documents": []}, ensure_ascii=False)
    conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES('mtender','ocds-1','h1',?, 'analyzed', ?, ?)",
        (nj, now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id='ocds-1'").fetchone()["id"]
    conn.execute(
        "INSERT INTO verdicts(tender_id, stage_name, verdict, score, confidence, reason, "
        "model, created_at) VALUES(?, 'applicability', 'can', 82, 0.9, ?, 'stub', ?)",
        (tid, json.dumps({"gaps": ["warranty gap"]}), now))
    conn.execute(
        "INSERT INTO suppliers(tender_id, items_json, total_cost, tender_value, currency, "
        "margin, matched_count, unmatched_count, margin_partial, created_at) "
        "VALUES(?, '[]', 800000, 1000000, 'MDL', 0.2, 1, 0, 0, ?)", (tid, now))
    conn.commit()
    conn.close()
    return tid


def test_digest_home(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    tid = _seed(p)
    c = TestClient(create_app(p))
    r = c.get("/")
    assert r.status_code == 200
    assert "Analizor de spectru" in r.text
    assert "ARCOM" in r.text
    r2 = c.get(f"/tender?id={tid}")
    assert r2.status_code == 200
    assert "warranty gap" in r2.text


def test_config_list_and_edit(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    _seed(p)
    c = TestClient(create_app(p))
    assert "greeting.text" in c.get("/config").text
    r = c.post("/config/save",
               data={"key": "greeting.text", "vtype": "str", "sval": "buna ziua", "note": "t"},
               follow_redirects=False)
    assert r.status_code == 303
    conn = db.connect(p)
    store = ConfigStore(conn)
    store.reload()
    assert store.get("greeting.text") == "buna ziua"
    hist = store.history("greeting.text")
    assert len(hist) >= 2
    conn.close()


def test_config_save_invalid_json_no_write(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    _seed(p)
    c = TestClient(create_app(p))
    r = c.post("/config/save",
               data={"key": "greeting.text", "vtype": "json", "jval": "{not valid", "note": ""},
               follow_redirects=False)
    assert r.status_code == 303
    assert "err=" in r.headers["location"]
    conn = db.connect(p)
    store = ConfigStore(conn)
    store.reload()
    assert store.get("greeting.text") == "salut"
    conn.close()


def test_config_rollback(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    _seed(p)
    c = TestClient(create_app(p))
    c.post("/config/save",
           data={"key": "greeting.text", "vtype": "str", "sval": "v2", "note": ""},
           follow_redirects=False)
    conn = db.connect(p)
    store = ConfigStore(conn)
    store.reload()
    assert store.get("greeting.text") == "v2"
    v1 = [h["version"] for h in store.history("greeting.text")][-1]
    conn.close()
    c.post("/config/rollback", data={"key": "greeting.text", "version": v1},
           follow_redirects=False)
    conn = db.connect(p)
    store = ConfigStore(conn)
    store.reload()
    assert store.get("greeting.text") == "salut"
    conn.close()


def test_token_auth(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    _seed(p)
    conn = db.connect(p)
    store = ConfigStore(conn)
    store.reload()
    store.set("web.token", "secret123")
    conn.close()
    c = TestClient(create_app(p))
    r = c.get("/")
    assert r.status_code == 401
    assert "token" in r.text.lower()
    r2 = c.get("/?token=secret123")
    assert r2.status_code == 200
    assert "Digest" in r2.text
    r3 = c.get("/", headers={"X-Token": "secret123"})
    assert r3.status_code == 200


def test_read_only_blocks_write(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    _seed(p)
    conn = db.connect(p)
    store = ConfigStore(conn)
    store.reload()
    store.set("web.read_only", True)
    conn.close()
    c = TestClient(create_app(p))
    r = c.post("/config/save",
               data={"key": "greeting.text", "vtype": "str", "sval": "x", "note": ""},
               follow_redirects=False)
    assert r.status_code == 303
    assert "read-only" in r.headers["location"]
    conn = db.connect(p)
    store = ConfigStore(conn)
    store.reload()
    assert store.get("greeting.text") == "salut"
    conn.close()


def test_healthz_no_auth(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    _seed(p)
    conn = db.connect(p)
    store = ConfigStore(conn)
    store.reload()
    store.set("web.token", "secret123")
    conn.close()
    c = TestClient(create_app(p))
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_config_typed_controls(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    _seed(p)
    c = TestClient(create_app(p))

    c.post("/config/save", data={"key": "web.digest_limit", "vtype": "int", "nval": "33"},
           follow_redirects=False)
    c.post("/config/save", data={"key": "suppliers.web_enabled", "vtype": "bool", "bval": "1"},
           follow_redirects=False)
    c.post("/config/save", data={"key": "llm.cache_enabled", "vtype": "bool"},
           follow_redirects=False)
    c.post("/config/save",
           data={"key": "supervisor.digest_verdicts", "vtype": "list_str", "lval": "can, partial, gray"},
           follow_redirects=False)

    conn = db.connect(p)
    store = ConfigStore(conn)
    store.reload()
    assert store.get("web.digest_limit") == 33
    assert isinstance(store.get("web.digest_limit"), int)
    assert store.get("suppliers.web_enabled") is True
    assert store.get("llm.cache_enabled") is False
    assert store.get("supervisor.digest_verdicts") == ["can", "partial", "gray"]
    conn.close()

    item = c.get("/config/item?key=web.digest_limit").text
    assert 'type="number"' in item
    bool_item = c.get("/config/item?key=llm.cache_enabled").text
    assert 'class="switch"' in bool_item
    assert "Cache identical LLM calls" in bool_item


def test_restart_button_guarded(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    _seed(p)
    import web.context as wc
    calls = []
    monkeypatch.setattr(wc, "_schedule_restart", lambda *a, **k: calls.append(1))
    c = TestClient(create_app(p))

    assert 'action="/admin/restart"' in c.get("/config").text
    r = c.post("/admin/restart", follow_redirects=False)
    assert r.status_code == 200
    assert "Restarting" in r.text
    assert calls == [1]


def test_restart_disabled_when_flag_off(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    _seed(p)
    conn = db.connect(p)
    store = ConfigStore(conn)
    store.reload()
    store.set("web.allow_restart", False)
    conn.close()
    import web.context as wc
    calls = []
    monkeypatch.setattr(wc, "_schedule_restart", lambda *a, **k: calls.append(1))
    c = TestClient(create_app(p))
    assert 'action="/admin/restart"' not in c.get("/config").text
    r = c.post("/admin/restart", follow_redirects=False)
    assert r.status_code == 303
    assert calls == []


def test_restart_blocked_in_readonly(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    _seed(p)
    conn = db.connect(p)
    store = ConfigStore(conn)
    store.reload()
    store.set("web.read_only", True)
    conn.close()
    import web.context as wc
    calls = []
    monkeypatch.setattr(wc, "_schedule_restart", lambda *a, **k: calls.append(1))
    c = TestClient(create_app(p))
    r = c.post("/admin/restart", follow_redirects=False)
    assert r.status_code == 303
    assert calls == []
