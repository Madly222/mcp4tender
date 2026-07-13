from __future__ import annotations
import datetime as dt, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import db
from engine.collectors import CollectContext, CollectResult, CollectedItem, register_collector
from engine.config_store import ConfigStore
from engine.scheduler import Scheduler, job_due, job_times, now_in_tz
from workflows.collect_jobs import run_collect_job
import workflows  # noqa: F401
DEFAULTS = Path(__file__).resolve().parent.parent/"config"/"defaults"
@register_collector("faketest")
class _Fake:
    source = "faketest"
    def collect(self, ctx: CollectContext) -> CollectResult:
        return CollectResult(items=[CollectedItem("f1",{"a":1},{"title":"Mobilier birou lemn","buyer":"x"}),
                                    CollectedItem("f2",{"a":2},{"title":"Scaune","buyer":"y"})], fetched=2, cursor="c1")
def _store(tmp_path):
    conn = db.connect(tmp_path/"s.db"); db.init_schema(conn)
    store = ConfigStore(conn); store.reload(); store.seed_defaults(DEFAULTS)
    return conn, store
def test_weekday_filter():
    now = dt.datetime(2026,1,5,6,0); assert now.weekday()==0
    assert job_due({"kind":"collect","at":["06:00"],"days":["mon"]}, now, {}) is not None
    assert job_due({"kind":"collect","at":["06:00"],"days":["tue"]}, now, {}) is None
    assert job_due({"kind":"collect","at":["06:00"],"days":[]}, now, {}) is not None
def test_weekday_numeric():
    now = dt.datetime(2026,1,7,6,0); assert now.weekday()==2
    assert job_due({"at":["06:00"],"days":[2]}, now, {}) is not None
    assert job_due({"at":["06:00"],"days":[3]}, now, {}) is None
def test_times_capped_at_24():
    at=[("%02d:00"%h) for h in range(24)]+["12:30","13:30"]
    t=job_times({"at":at}); assert len(t)==24 and t==sorted(t)
def test_times_dedup():
    assert job_times({"at":["06:00","06:00","18:00"]})==["06:00","18:00"]
def test_now_in_tz(tmp_path):
    conn, store = _store(tmp_path)
    store.set("schedule.timezone",""); assert now_in_tz(store).tzinfo is None
    store.set("schedule.timezone","Europe/Chisinau"); assert now_in_tz(store).tzinfo is not None
def test_scheduler_dispatches_collect_job(tmp_path):
    conn, store = _store(tmp_path); now = dt.datetime(2026,1,5,6,0)
    store.set("schedule.jobs", [{"kind":"collect","sources":["faketest"],"at":["06:00"],"analyze":False,"enabled":True}])
    cap=[]; sch=Scheduler(store, lambda pipeline, job: cap.append((pipeline, job.get("kind"))))
    assert sch.tick(now=now)==["collect"] and cap==[(None,"collect")]
def test_collect_job_stamps_incremental(tmp_path):
    conn, store = _store(tmp_path); store.set("sources.faketest", {"enabled": True})
    assert run_collect_job({"sources":["faketest"],"analyze":False}, store, conn)["new"]==2
    assert [r["origin"] for r in conn.execute("SELECT origin FROM tenders").fetchall()]==["incremental","incremental"]
def test_collect_job_disabled_source_noop(tmp_path):
    conn, store = _store(tmp_path); store.set("sources.faketest", {"enabled": False})
    assert run_collect_job({"sources":["faketest"],"analyze":False}, store, conn)["new"]==0
    assert conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]==0
def test_collect_job_runs_analysis(tmp_path):
    conn, store = _store(tmp_path); store.set("sources.faketest", {"enabled": True})
    r = run_collect_job({"sources":["faketest"],"analyze":True}, store, conn)
    assert r["analyze"] is not None
    assert "new" not in {row["status"] for row in conn.execute("SELECT status FROM tenders").fetchall()}
