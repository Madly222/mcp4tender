from __future__ import annotations
import datetime as dt
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workflows.collectors.mtender import MTenderCollector, normalize_record
from workflows.collectors import genericweb as gw
from engine.lifecycle import archive_reason, item_archive_reason
from engine.dateparse import parse_date

T = dt.date.today()
def d(n): return (T - dt.timedelta(days=n)).isoformat()
def ahead(n): return (T + dt.timedelta(days=n)).isoformat()


def _rec(pub, deadline):
    tender = {"title": "X", "datePublished": pub}
    if deadline:
        tender["tenderPeriod"] = {"endDate": deadline}
    return {"records": [{"ocid": "ocds-1", "compiledRelease": {"date": pub, "tender": tender}}]}


# ---- mtender: the normalized record is judged by the same rule ----

def test_mtender_dead_tender_is_skipped():
    nj = normalize_record(_rec(d(100), d(5)), "ocds-1")
    assert item_archive_reason(nj, archive_days=90) == "deadline"


def test_mtender_live_old_tender_is_kept():
    nj = normalize_record(_rec(d(100), ahead(5)), "ocds-1")
    assert item_archive_reason(nj, archive_days=90) is None


def test_mtender_old_undated_deadline_skipped_by_age():
    nj = normalize_record(_rec(d(100), None), "ocds-1")
    assert item_archive_reason(nj, archive_days=90) == "age"


def test_mtender_collector_reports_too_old_field():
    import inspect
    src = inspect.getsource(MTenderCollector.collect)
    assert "skipped_dead" in src and "too_old=skipped_dead" in src
    assert "item_archive_reason" in src


# ---- genericweb: same rule, using raw LLM strings ----

def _skip(date_txt, deadline_txt, ceiling=90):
    return archive_reason(parse_date(date_txt), parse_date(deadline_txt), archive_days=ceiling)


def test_genericweb_skips_expired_deadline():
    assert _skip("1 iunie 2026", d(2)) == "deadline"


def test_genericweb_keeps_live_old_tender():
    assert _skip(d(200), ahead(3)) is None


def test_genericweb_skips_old_without_deadline():
    assert _skip(d(120), None) == "age"


def test_genericweb_keeps_undated():
    assert _skip(None, None) is None
    assert _skip("in curand", "in curand") is None


def test_genericweb_uses_ceiling_not_raw_max_age():
    import inspect
    src = inspect.getsource(gw.GenericWebCollector.collect) if hasattr(gw, "GenericWebCollector") \
        else Path("workflows/collectors/genericweb.py").read_text()
    assert "collect_ceiling(store)" in src
    assert "archive_reason(" in src
