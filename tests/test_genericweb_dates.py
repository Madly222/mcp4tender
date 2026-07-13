from __future__ import annotations
import datetime as dt
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workflows.collectors.genericweb import (DEFAULT_EXTRACT_PROMPT, _normalize_item,
                                             _tender_age_days, _tender_date)

SITE = {"url": "https://tenderhub.md", "label": "TenderHub"}


def _n(**item):
    item.setdefault("title", "T")
    return _normalize_item(SITE, item)


# ---- prompt now asks for the third date ----

def test_prompt_requests_enquiry_deadline():
    p = DEFAULT_EXTRACT_PROMPT
    assert "enquiry_deadline" in p
    assert "clarificari" in p or "clarific" in p
    assert "prefer ISO YYYY-MM-DD" in p


# ---- publication date lands on the canonical key, in ISO ----

def test_publication_date_is_iso_and_key_renamed():
    nj = _n(date="13 iulie 2026")
    assert nj["publication_date"] == "2026-07-13"
    assert nj["published_raw"] == "13 iulie 2026"


def test_deadline_iso_with_time():
    nj = _n(deadline="15.07.2026, ora 10:00")
    assert nj["deadline"] == "2026-07-15T10:00:00"
    assert nj["deadline_raw"] == "15.07.2026, ora 10:00"


def test_enquiry_deadline_captured():
    nj = _n(enquiry_deadline="22 iunie 2026")
    assert nj["enquiry_deadline"] == "2026-06-22"
    assert nj["enquiry_deadline_raw"] == "22 iunie 2026"


def test_iso_utc_from_site_converted_to_local():
    nj = _n(deadline="2026-07-13T06:00:00Z")
    assert nj["deadline"] == "2026-07-13T09:00:00"


def test_russian_and_english_dates():
    assert _n(date="15 июля 2026")["publication_date"] == "2026-07-15"
    assert _n(date="July 15, 2026")["publication_date"] == "2026-07-15"


def test_unparseable_text_is_preserved_not_dropped():
    nj = _n(deadline="in curand", date="peste o saptamana")
    assert nj["deadline"] == "in curand"
    assert nj["publication_date"] == "peste o saptamana"


def test_missing_dates_stay_none():
    nj = _n()
    assert nj["publication_date"] is None
    assert nj["deadline"] is None
    assert nj["enquiry_deadline"] is None


def test_collection_timestamp_untouched():
    nj = _n(date="13 iulie 2026")
    assert nj["date"].endswith("Z")            # still the collection time, not the tender date


# ---- age filter now understands month names ----

def test_tender_date_handles_month_names():
    assert _tender_date("13 iulie 2026") == dt.date(2026, 7, 13)
    assert _tender_date("15.07.2026") == dt.date(2026, 7, 15)
    assert _tender_date("in curand") is None


def test_age_days_from_month_name():
    old = (dt.date.today() - dt.timedelta(days=120))
    months = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
              "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie"]
    txt = f"{old.day} {months[old.month - 1]} {old.year}"
    age = _tender_age_days(txt)
    assert age is not None and 119 <= age <= 121


def test_age_none_for_undated_items():
    assert _tender_age_days(None) is None
    assert _tender_age_days("in curand") is None
