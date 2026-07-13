from __future__ import annotations
import datetime as dt
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import db
from engine.config_store import ConfigStore
from engine.lifecycle import (archive_reason, collect_ceiling, item_archive_reason, item_dates)

NOW = dt.datetime(2026, 7, 10, 12, 0)
T = NOW.date()
def d(days): return T - dt.timedelta(days=days)
def ahead(days): return T + dt.timedelta(days=days)


# ---- the rule ----

def test_live_tender_with_future_deadline_is_never_archived_by_age():
    assert archive_reason(d(100), ahead(5), T, NOW, 90) is None
    assert archive_reason(d(3650), ahead(1), T, NOW, 90) is None


def test_passed_deadline_archives_even_if_fresh():
    assert archive_reason(d(1), d(1), T, NOW, 90) == "deadline"


def test_deadline_today_is_still_live():
    assert archive_reason(d(1), T, T, NOW, 90) is None


def test_age_only_applies_without_deadline():
    assert archive_reason(d(91), None, T, NOW, 90) == "age"
    assert archive_reason(d(90), None, T, NOW, 90) is None


def test_undated_never_archived_at_collect_time():
    assert archive_reason(None, None, T, NOW, 90) is None


def test_falls_back_to_found_date():
    assert archive_reason(None, None, d(120), NOW, 90) == "age"


# ---- item helpers ----

def test_item_dates_reads_both_keys():
    assert item_dates({"published": "13 iulie 2026"})[0] == dt.date(2026, 7, 13)
    assert item_dates({"publication_date": "2026-07-13"})[0] == dt.date(2026, 7, 13)


def test_item_archive_reason_on_normalized():
    nj = {"publication_date": "2026-01-01", "deadline": "2026-07-15T10:00:00"}
    assert item_archive_reason(nj, T, NOW, 90) is None            # live: deadline ahead
    nj2 = {"publication_date": "2026-01-01", "deadline": "2026-06-01"}
    assert item_archive_reason(nj2, T, NOW, 90) == "deadline"
    nj3 = {"publication_date": "2026-01-01"}
    assert item_archive_reason(nj3, T, NOW, 90) == "age"


# ---- ceiling ----

def test_ceiling_takes_the_smaller_limit(tmp_path):
    conn = db.connect(tmp_path / "c.db"); db.init_schema(conn)
    s = ConfigStore(conn); s.reload()
    s.set("collect.max_age_days", 30); s.set("results.archive_after_days", 90)
    assert collect_ceiling(s) == 30
    s.set("collect.max_age_days", 120)
    assert collect_ceiling(s) == 90


def test_ceiling_ignores_zero_and_missing(tmp_path):
    conn = db.connect(tmp_path / "c2.db"); db.init_schema(conn)
    s = ConfigStore(conn); s.reload()
    s.set("collect.max_age_days", 0); s.set("results.archive_after_days", 45)
    assert collect_ceiling(s) == 45
