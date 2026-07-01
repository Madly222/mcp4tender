from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db
from engine.config_store import ConfigStore
from engine.registry import all_stages, get_stage
from engine.runner import run_pipeline
import workflows  # noqa: F401


def fresh_store(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    return conn, store


def test_stages_registered():
    assert "dummy_echo" in all_stages()
    assert "dummy_shout" in all_stages()


def test_config_versioning(tmp_path):
    _, store = fresh_store(tmp_path)
    v1 = store.set("x.key", {"a": 1})
    v2 = store.set("x.key", {"a": 2})
    assert v1 == 1 and v2 == 2
    assert store.get("x.key") == {"a": 2}
    hist = store.history("x.key")
    assert len(hist) == 2


def test_config_rollback(tmp_path):
    _, store = fresh_store(tmp_path)
    store.set("x.key", "first")
    store.set("x.key", "second")
    store.rollback("x.key", 1)
    assert store.get("x.key") == "first"


def test_hot_reload_across_two_handles(tmp_path):
    conn, writer = fresh_store(tmp_path)
    reader = ConfigStore(conn)
    reader.reload()
    writer.set("dummy.message", "value-A")
    assert reader.get("dummy.message") == "value-A"
    writer.set("dummy.message", "value-B")
    assert reader.get("dummy.message") == "value-B"


def test_pipeline_end_to_end(tmp_path):
    conn, store = fresh_store(tmp_path)
    store.set("dummy.message", "hello world")
    store.set("pipeline.demo", ["dummy_echo", "dummy_shout"])
    result = run_pipeline("pipeline.demo", store, conn)
    assert result["status"] == "done"
    assert result["payload"]["shout"] == "HELLO WORLD!"


def test_pipeline_reflects_config_change_without_reimport(tmp_path):
    conn, store = fresh_store(tmp_path)
    store.set("pipeline.demo", ["dummy_echo"])
    store.set("dummy.message", "first")
    r1 = run_pipeline("pipeline.demo", store, conn)
    store.set("dummy.message", "second")
    r2 = run_pipeline("pipeline.demo", store, conn)
    assert r1["payload"]["message"] == "first"
    assert r2["payload"]["message"] == "second"


def test_stage_input_validation(tmp_path):
    conn, store = fresh_store(tmp_path)
    store.set("pipeline.bad", ["dummy_shout"])
    result = run_pipeline("pipeline.bad", store, conn)
    assert result["status"] == "failed"


if __name__ == "__main__":
    import tempfile

    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as d:
                try:
                    if fn.__code__.co_argcount:
                        fn(Path(d))
                    else:
                        fn()
                    print(f"PASS {name}")
                except Exception as exc:
                    print(f"FAIL {name}: {exc}")
                    raise
    print("all tests passed")
