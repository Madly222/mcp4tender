from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db
from engine.config_store import ConfigStore
from engine.orchestrator import process_one, process_batch
from engine.scheduler import Scheduler, job_due
from engine.checks import run_startup_checks
import workflows  # noqa: F401


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("pipeline.demo", ["dummy_echo", "dummy_shout"])
    store.set("dummy.message", "hi")
    store.set("runtime.max_retries", 3)
    store.set("runtime.retry_backoff", 0)
    return conn, store


def item(source="mtender", ext="T-1", content=None):
    return {"source": source, "external_id": ext, "content": content or {"title": "x"}}


def test_process_one_done(tmp_path):
    conn, store = fresh(tmp_path)
    r = process_one("pipeline.demo", item(), store, conn)
    assert r["status"] == "done"
    row = conn.execute("SELECT status FROM tenders WHERE id = ?", (r["tender_id"],)).fetchone()
    assert row["status"] == "done"


def test_dedup_skips_unchanged(tmp_path):
    conn, store = fresh(tmp_path)
    r1 = process_one("pipeline.demo", item(), store, conn)
    r2 = process_one("pipeline.demo", item(), store, conn)
    assert r1["status"] == "done"
    assert r2["status"] == "skipped_dedup"
    assert r1["tender_id"] == r2["tender_id"]


def test_changed_content_reprocesses(tmp_path):
    conn, store = fresh(tmp_path)
    process_one("pipeline.demo", item(content={"title": "v1"}), store, conn)
    r = process_one("pipeline.demo", item(content={"title": "v2"}), store, conn)
    assert r["status"] == "done"


def test_force_bypasses_dedup(tmp_path):
    conn, store = fresh(tmp_path)
    process_one("pipeline.demo", item(), store, conn)
    r = process_one("pipeline.demo", item(), store, conn, force=True)
    assert r["status"] == "done"


def test_retry_recovers(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("pipeline.flaky", ["dummy_flaky"])
    store.set("dummy.flaky_fail_times", 2)
    store.set("runtime.max_retries", 3)
    r = process_one("pipeline.flaky", item(ext="F-1"), store, conn)
    assert r["status"] == "done"


def test_retry_exhausted_fails(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("pipeline.flaky", ["dummy_flaky"])
    store.set("dummy.flaky_fail_times", 5)
    store.set("runtime.max_retries", 1)
    r = process_one("pipeline.flaky", item(ext="F-2"), store, conn)
    assert r["status"] == "failed"
    row = conn.execute("SELECT status FROM tenders WHERE id = ?", (r["tender_id"],)).fetchone()
    assert row["status"] == "failed"


def test_batch_summary(tmp_path):
    conn, store = fresh(tmp_path)
    items = [item(ext="A"), item(ext="B"), item(ext="A")]
    s = process_batch("pipeline.demo", items, store, conn)
    assert s["total"] == 3
    assert s["done"] == 2
    assert s["skipped_dedup"] == 1


def test_scheduler_at_fires_once_per_slot(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("schedule.jobs", [{"pipeline": "pipeline.demo", "at": ["03:00"], "enabled": True}])
    calls = []
    sch = Scheduler(store, lambda p, j: calls.append(p))
    now = dt.datetime(2026, 1, 1, 3, 0, 15)
    sch.tick(now)
    sch.tick(now.replace(second=45))
    assert calls == ["pipeline.demo"]


def test_scheduler_disabled_job_skipped(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("schedule.jobs", [{"pipeline": "pipeline.demo", "at": ["03:00"], "enabled": False}])
    calls = []
    sch = Scheduler(store, lambda p, j: calls.append(p))
    sch.tick(dt.datetime(2026, 1, 1, 3, 0, 0))
    assert calls == []


def test_scheduler_every_minutes(tmp_path):
    job = {"pipeline": "p", "every_minutes": 30}
    last = {}
    now = dt.datetime(2026, 1, 1, 0, 0, 0)
    assert job_due(job, now, last) is not None
    last[__import__("engine.scheduler", fromlist=["job_key"]).job_key(job)] = now
    assert job_due(job, now + dt.timedelta(minutes=10), last) is None
    assert job_due(job, now + dt.timedelta(minutes=31), last) is not None


def test_startup_checks_ok(tmp_path):
    conn, store = fresh(tmp_path)
    ok, results = run_startup_checks(conn, store)
    assert ok
    names = {r[0] for r in results}
    assert {"db", "schema", "configs", "stages"} <= names


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
