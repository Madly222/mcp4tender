from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db
from engine.config_store import ConfigStore
from engine.llm import LLMGateway, StubProvider


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("llm.provider", "stub")
    store.set("llm.models", {"default": "claude-haiku-4-5-20251001",
                             "applicability": "claude-sonnet-4-6"})
    store.set("llm.pricing", {"claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0}})
    store.set("llm.cache_enabled", True)
    return conn, store


class CountingProvider(StubProvider):
    name = "counting"

    def __init__(self):
        self.calls = 0

    def generate(self, model, system, messages, max_tokens):
        self.calls += 1
        return {"text": "answer", "input_tokens": 1000, "output_tokens": 500}


def msg(text="hello"):
    return [{"role": "user", "content": text}]


def test_model_per_stage(tmp_path):
    conn, store = fresh(tmp_path)
    gw = LLMGateway(store, conn, provider=StubProvider())
    assert gw.model_for("applicability") == "claude-sonnet-4-6"
    assert gw.model_for("unknown") == "claude-haiku-4-5-20251001"


def test_complete_returns_usage(tmp_path):
    conn, store = fresh(tmp_path)
    gw = LLMGateway(store, conn, provider=CountingProvider())
    r = gw.complete("default", "sys", msg(), max_tokens=64)
    assert r["text"] == "answer"
    assert r["input_tokens"] == 1000
    assert r["cached"] is False


def test_cost_from_pricing(tmp_path):
    conn, store = fresh(tmp_path)
    gw = LLMGateway(store, conn, provider=CountingProvider())
    r = gw.complete("default", "sys", msg(), max_tokens=64)
    assert abs(r["cost"] - ((1000 / 1e6) * 1.0 + (500 / 1e6) * 5.0)) < 1e-9


def test_cache_hit_second_call(tmp_path):
    conn, store = fresh(tmp_path)
    prov = CountingProvider()
    gw = LLMGateway(store, conn, provider=prov)
    gw.complete("default", "sys", msg("same"), max_tokens=64)
    r2 = gw.complete("default", "sys", msg("same"), max_tokens=64)
    assert r2["cached"] is True
    assert r2["cost"] == 0.0
    assert prov.calls == 1


def test_cache_miss_on_different_input(tmp_path):
    conn, store = fresh(tmp_path)
    prov = CountingProvider()
    gw = LLMGateway(store, conn, provider=prov)
    gw.complete("default", "sys", msg("a"), max_tokens=64)
    gw.complete("default", "sys", msg("b"), max_tokens=64)
    assert prov.calls == 2


def test_cache_disabled(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("llm.cache_enabled", False)
    prov = CountingProvider()
    gw = LLMGateway(store, conn, provider=prov)
    gw.complete("default", "sys", msg("x"), max_tokens=64)
    gw.complete("default", "sys", msg("x"), max_tokens=64)
    assert prov.calls == 2


def test_stub_provider_used_when_configured(tmp_path):
    conn, store = fresh(tmp_path)
    gw = LLMGateway(store, conn)
    assert gw.provider.name == "stub"


if __name__ == "__main__":
    import tempfile

    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as d:
                try:
                    fn(Path(d))
                    print(f"PASS {name}")
                except Exception as exc:
                    print(f"FAIL {name}: {exc}")
                    raise
    print("all tests passed")
