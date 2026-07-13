from __future__ import annotations
import datetime as dt, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import db
from engine.collectors import _origin_for, _store_item, CollectedItem
from engine.config_store import ConfigStore
from workflows.segments import classify_segment, partition
NOW = dt.datetime(2026, 1, 15, 12, 0, 0)
def days_ago(n): return (NOW - dt.timedelta(days=n)).timestamp()
def d(n): return (NOW - dt.timedelta(days=n)).date()
def test_new_incremental_recent():
    assert classify_segment("incremental", days_ago(2), d(2), None, now=NOW, new_days=7, archive_days=90) == "new"
def test_backfill_never_new():
    assert classify_segment("backfill", days_ago(0), d(0), None, now=NOW, new_days=7, archive_days=90) == "history"
def test_archive_by_deadline():
    assert classify_segment("incremental", days_ago(1), d(1), d(1), now=NOW, new_days=7, archive_days=90) == "archive"
def test_origin_for_mode():
    assert _origin_for({"mode":"backfill"})=="backfill" and _origin_for(None)=="incremental"
def _store(conn, ext, origin, nj, ago):
    _store_item(conn, "genericweb", CollectedItem(external_id=ext, raw={"x":1}, normalized=nj), origin)
    conn.execute("UPDATE tenders SET created_at=? WHERE external_id=?", (days_ago(ago), ext)); conn.commit()
def test_partition_and_month_names(tmp_path):
    conn = db.connect(tmp_path/"t.db"); db.init_schema(conn)
    store = ConfigStore(conn); store.reload()
    store.set("results.new_days", 7); store.set("results.archive_after_days", 90)
    _store(conn, "g:new", "incremental", {"title":"n","publication_date":d(1).isoformat()}, 1)
    _store(conn, "g:hist", "backfill", {"title":"h","published":"5 ianuarie 2026"}, 10)
    _store(conn, "g:arch", "incremental", {"title":"a","published":"13 iulie 2025"}, 5)
    rows = conn.execute("SELECT id, origin, created_at, normalized_json FROM tenders").fetchall()
    b = partition(rows, store, now=NOW)
    assert len(b["new"])==1 and len(b["history"])==1 and len(b["archive"])==1
