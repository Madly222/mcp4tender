from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db, run_collector
from engine.config_store import ConfigStore
from engine.llm import LLMGateway, StubProvider
import workflows  # noqa: F401
import workflows.collectors.genericweb as gw


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("llm.provider", "stub")
    return conn, store


class RealFakeProvider:
    name = "anthropic"
    available = True

    def __init__(self):
        self.calls = 0

    def generate(self, model, system, messages, max_tokens):
        self.calls += 1
        return {"text": '{"ok": true}', "input_tokens": 10, "output_tokens": 5}


def test_stub_response_is_never_cached(tmp_path):
    conn, store = fresh(tmp_path)
    g = LLMGateway(store, conn, provider=StubProvider())
    g.complete("triage", "sys", [{"role": "user", "content": "hello"}])
    n = conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
    assert n == 0


def test_poisoned_stub_cache_entry_is_purged_for_real_provider(tmp_path):
    conn, store = fresh(tmp_path)
    stub = LLMGateway(store, conn, provider=StubProvider())
    real = LLMGateway(store, conn, provider=RealFakeProvider())
    msgs = [{"role": "user", "content": "hello"}]
    key_fields = {"model": real.model_for("triage"), "system": "sys",
                  "messages": msgs, "max_tokens": 1024, "prefill": None}
    from engine.hashing import content_hash
    conn.execute(
        "INSERT INTO llm_cache(cache_key, model, response_json, input_tokens, "
        "output_tokens, created_at) VALUES(?,?,?,?,?,?)",
        (content_hash(key_fields), key_fields["model"],
         json.dumps({"text": "STUB_RESPONSE: hello"}), 0, 0, time.time()))
    conn.commit()
    out = real.complete("triage", "sys", msgs)
    assert not out["text"].startswith("STUB_RESPONSE:")
    assert real.provider.calls == 1
    row = conn.execute("SELECT response_json FROM llm_cache").fetchone()
    assert "STUB_RESPONSE" not in row["response_json"]
    assert stub.provider.name == "stub"


def test_real_response_is_still_cached(tmp_path):
    conn, store = fresh(tmp_path)
    prov = RealFakeProvider()
    g = LLMGateway(store, conn, provider=prov)
    msgs = [{"role": "user", "content": "hello"}]
    g.complete("triage", "sys", msgs)
    out = g.complete("triage", "sys", msgs)
    assert prov.calls == 1
    assert out["cached"] is True


def _site_store(store):
    store.set("sources.genericweb", {"enabled": True, "incremental_max_pages": 5,
                                     "fallback_batch": 30})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md/list",
                                 "enabled": True, "step_percent": 100}])


def test_incremental_skips_model_when_front_page_unchanged(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    _site_store(store)
    calls = {"extract": 0}

    def fake_extract(g, st, text, url, sc):
        calls["extract"] += 1
        return [{"title": "T1", "url": "https://a.md/t/1"}], None, None

    monkeypatch.setattr(gw, "get_text",
                        lambda url, timeout=30, headers=None: "<p>same page</p>")
    monkeypatch.setattr(gw, "_extract", fake_extract)
    run_collector("genericweb", store, conn, params={"mode": "incremental"})
    assert calls["extract"] == 1
    run_collector("genericweb", store, conn, params={"mode": "incremental"})
    assert calls["extract"] == 1
    note = conn.execute(
        "SELECT note FROM crawl_state WHERE site_id='s1'").fetchone()["note"]
    assert "unchanged" in note


def test_incremental_runs_model_when_front_page_changed(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    _site_store(store)
    calls = {"extract": 0}
    page = {"html": "<p>v1</p>"}

    def fake_extract(g, st, text, url, sc):
        calls["extract"] += 1
        return [{"title": "T1", "url": "https://a.md/t/1"}], None, None

    monkeypatch.setattr(gw, "get_text",
                        lambda url, timeout=30, headers=None: page["html"])
    monkeypatch.setattr(gw, "_extract", fake_extract)
    run_collector("genericweb", store, conn, params={"mode": "incremental"})
    page["html"] = "<p>v2 new tender</p>"
    run_collector("genericweb", store, conn, params={"mode": "incremental"})
    assert calls["extract"] == 2


def test_backfill_ignores_page_hash_gate(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    _site_store(store)
    calls = {"extract": 0}

    def fake_extract(g, st, text, url, sc):
        calls["extract"] += 1
        return [{"title": f"T{calls['extract']}", "url": "https://a.md/t/1"}], None, None

    monkeypatch.setattr(gw, "get_text",
                        lambda url, timeout=30, headers=None: "<p>same page</p>")
    monkeypatch.setattr(gw, "_extract", fake_extract)
    run_collector("genericweb", store, conn, params={"mode": "backfill", "site_id": "s1"})
    run_collector("genericweb", store, conn, params={"mode": "backfill", "site_id": "s1"})
    assert calls["extract"] == 2
