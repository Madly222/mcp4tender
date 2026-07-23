from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.dateparse import parse_date
from workflows.collectors.genericweb import _normalize_item


def test_english_textual_dates_parse():
    assert str(parse_date("September 12, 2026")) == "2026-09-12"
    assert str(parse_date("12 September 2026")) == "2026-09-12"
    assert str(parse_date("12th September 2026")) == "2026-09-12"
    assert str(parse_date("March 3rd, 2026")) == "2026-03-03"
    assert str(parse_date("July 1st 2026")) == "2026-07-01"
    assert str(parse_date("Aug. 5, 2026")) == "2026-08-05"


def test_romanian_dates_unbroken():
    assert str(parse_date("12 iunie 2026")) == "2026-06-12"
    assert str(parse_date("5 septembrie 2026")) == "2026-09-05"
    assert str(parse_date("03.07.2026")) == "2026-07-03"


def test_numeric_dayfirst_flag():
    assert str(parse_date("07/12/2026")) == "2026-12-07"
    assert str(parse_date("07/12/2026", dayfirst=False)) == "2026-07-12"


def _item(deadline):
    return {"title": "T", "url": "https://a.md/t/1", "deadline": deadline}


def test_site_date_order_controls_normalization():
    dmy_site = {"id": "s1", "url": "https://a.md"}
    mdy_site = {"id": "s2", "url": "https://b.com", "date_order": "mdy"}
    assert _normalize_item(dmy_site, _item("07/12/2026"))["deadline"] == "2026-12-07"
    assert _normalize_item(mdy_site, _item("07/12/2026"))["deadline"] == "2026-07-12"
    assert _normalize_item(mdy_site, _item("September 12, 2026"))["deadline"] == "2026-09-12"
