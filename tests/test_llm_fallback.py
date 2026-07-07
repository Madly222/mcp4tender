from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from engine import db
from engine.config_store import ConfigStore
from engine.llm import LLMGateway


def _store(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("llm.cache_enabled", False)
    store.set("llm.models", {"default": "good-model", "applicability": "dead-model"})
    return conn, store


class FakeProvider:
    name = "fake"

    def generate(self, model, system, messages, max_tokens):
        if model == "dead-model":
            raise RuntimeError("Error code: 400 - invalid_request_error: model: dead-model")
        return {"text": "ok", "input_tokens": 1, "output_tokens": 1}


def test_model_fallback_on_bad_model(tmp_path):
    conn, store = _store(tmp_path)
    gw = LLMGateway(store, conn, provider=FakeProvider())
    r = gw.complete("applicability", "sys", [{"role": "user", "content": "hi"}])
    assert r["text"] == "ok" and r["model"] == "good-model"


def test_empty_content_guarded(tmp_path):
    conn, store = _store(tmp_path)
    gw = LLMGateway(store, conn, provider=FakeProvider())
    with pytest.raises(ValueError):
        gw.complete("extract", "sys", [{"role": "user", "content": "   "}])
