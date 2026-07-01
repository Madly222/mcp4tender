from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db
from engine.config_store import ConfigStore
from engine.jsonutil import loads_loose
from engine.llm import LLMGateway


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    return conn, store


def test_loads_loose_plain():
    assert loads_loose('{"a": 1}') == {"a": 1}


def test_loads_loose_code_fence():
    assert loads_loose('```json\n{"a": 1}\n```') == {"a": 1}


def test_loads_loose_with_preamble():
    txt = 'Iată rezultatul:\n{"can_execute": "can"}\nSper că ajută.'
    assert loads_loose(txt) == {"can_execute": "can"}


def test_loads_loose_garbage_returns_none():
    assert loads_loose("not json at all") is None
    assert loads_loose("") is None


def test_prefill_prepends_for_continuation(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("llm.cache_enabled", False)

    class Continuation:
        name = "c"; available = True
        def generate(self, model, system, messages, max_tokens):
            return {"text": '"a": 1}', "input_tokens": 5, "output_tokens": 5}

    gw = LLMGateway(store, conn, provider=Continuation())
    r = gw.complete("default", "sys", [{"role": "user", "content": "x"}], prefill="{")
    assert loads_loose(r["text"]) == {"a": 1}


def test_prefill_no_double_when_already_braced(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("llm.cache_enabled", False)

    class FullJson:
        name = "f"; available = True
        def generate(self, model, system, messages, max_tokens):
            return {"text": '{"a": 1}', "input_tokens": 5, "output_tokens": 5}

    gw = LLMGateway(store, conn, provider=FullJson())
    r = gw.complete("default", "sys", [{"role": "user", "content": "x"}], prefill="{")
    assert loads_loose(r["text"]) == {"a": 1}


def test_expects_real_but_stub(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("llm.provider", "stub")
    gw = LLMGateway(store, conn)
    assert gw.expects_real_but_stub() is False
    store.set("llm.provider", "auto")
    gw2 = LLMGateway(store, conn)
    # no API key in test env -> stub provider while auto expected
    assert gw2.expects_real_but_stub() is True


def test_flag_parse_failure_sets_review(tmp_path):
    conn, store = fresh(tmp_path)
    now = time.time()
    conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        ("t", "x", "h", "{}", "analyzed", now, now))
    conn.commit()
    from workflows.verify import flag_parse_failure
    flag_parse_failure(conn, 1, "applicability", "garbage output")
    v = conn.execute("SELECT needs_review FROM verifications WHERE tender_id=1").fetchone()
    assert v["needs_review"] == 1
    st = conn.execute("SELECT status FROM tenders WHERE id=1").fetchone()["status"]
    assert st == "needs_review"


if __name__ == "__main__":
    import tempfile

    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as d:
                argn = fn.__code__.co_varnames[:fn.__code__.co_argcount]
                args = [Path(d)] if argn else []
                try:
                    fn(*args)
                    print(f"PASS {name}")
                except Exception as exc:
                    print(f"FAIL {name}: {exc}")
                    raise
    print("all tests passed")
