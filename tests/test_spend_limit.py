from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from engine import db
from engine.config_store import ConfigStore
from engine.llm import LLMGateway, SpendLimitError

DEFAULTS = str(Path(__file__).resolve().parent.parent / "config" / "defaults")

MSG = [{"role": "user", "content": "hello"}]


class PaidProvider:
    name = "anthropic"
    available = True

    def __init__(self):
        self.calls = 0

    def generate(self, model, system, messages, max_tokens):
        self.calls += 1
        return {"text": "ok", "input_tokens": 100000, "output_tokens": 100000}


def _gw(tmp_path, limit, cache=False):
    conn = db.connect(str(tmp_path / "s.db"))
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.seed_defaults(DEFAULTS)
    store.reload()
    store.set("llm.daily_limit_usd", limit)
    store.set("llm.cache_enabled", cache)
    prov = PaidProvider()
    return LLMGateway(store, conn, provider=prov), prov, conn


def test_calls_flow_until_the_limit_then_get_refused(tmp_path):
    gw, prov, conn = _gw(tmp_path, limit=1.0)
    # each call: 100k in @ $1/M + 100k out @ $5/M = $0.60
    gw.complete("extract", "", MSG)
    gw.complete("extract", "", MSG)  # now $1.20 spent, over the $1 cap
    with pytest.raises(SpendLimitError):
        gw.complete("extract", "", MSG)
    assert prov.calls == 2
    conn.close()


def test_zero_limit_means_no_cap(tmp_path):
    gw, prov, conn = _gw(tmp_path, limit=0)
    for _ in range(5):
        gw.complete("extract", "", MSG)
    assert prov.calls == 5
    conn.close()


def test_cached_calls_are_free_and_never_blocked(tmp_path):
    gw, prov, conn = _gw(tmp_path, limit=1.0, cache=True)
    gw.complete("extract", "", MSG)
    gw.complete("extract", "", MSG)  # $1.20, over cap
    before = prov.calls
    # identical prompt -> served from cache -> costs nothing -> allowed despite the cap
    out = gw.complete("extract", "", MSG)
    assert out["cached"] is True and out["cost"] == 0.0
    assert prov.calls == before
    conn.close()


def test_yesterdays_spend_does_not_count_against_today(tmp_path):
    gw, prov, conn = _gw(tmp_path, limit=1.0)
    yesterday = time.time() - 26 * 3600
    conn.execute(
        "INSERT INTO llm_spend(ts, stage, model, provider, input_tokens, output_tokens, "
        "cost, cached, tender_id, site_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (yesterday, "extract", "m", "anthropic", 0, 0, 9.99, 0, None, None))
    conn.commit()
    assert gw.spent_today() == 0.0
    gw.complete("extract", "", MSG)  # allowed — yesterday's $9.99 is not counted
    assert prov.calls == 1
    conn.close()


def test_stub_provider_is_never_capped(tmp_path):
    conn = db.connect(str(tmp_path / "stub.db"))
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.seed_defaults(DEFAULTS)
    store.reload()
    store.set("llm.daily_limit_usd", 0.01)
    store.set("llm.provider", "stub")
    from engine.llm import StubProvider
    gw = LLMGateway(store, conn, provider=StubProvider())
    for _ in range(3):
        gw.complete("extract", "", MSG)
    conn.close()
