from __future__ import annotations
import datetime as dt, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.dateparse import parse, parse_date, to_iso, humanize, day_month

D = dt.date

# ---- ISO with timezone: the real bug from the UI ----
def test_iso_utc_converted_to_chisinau_summer():
    i = parse("2026-07-13T06:00:00Z")
    assert i.date == D(2026, 7, 13) and i.time == "09:00"

def test_iso_utc_converted_winter_dst():
    i = parse("2026-01-13T06:00:00Z")
    assert i.date == D(2026, 1, 13) and i.time == "08:00"

def test_iso_utc_midnight_rolls_date():
    i = parse("2026-07-13T23:30:00Z")
    assert i.date == D(2026, 7, 14) and i.time == "02:30"

def test_iso_offset_form():
    i = parse("2026-06-22T07:00:00+00:00")
    assert i.date == D(2026, 6, 22) and i.time == "10:00"

def test_iso_naive_not_shifted():
    i = parse("2026-07-13 10:00")
    assert i.date == D(2026, 7, 13) and i.time == "10:00"

def test_iso_date_only():
    i = parse("2026-07-13")
    assert i.date == D(2026, 7, 13) and i.time is None

# ---- numeric ----
def test_numeric_dayfirst_default():
    assert parse_date("03/07/2026") == D(2026, 7, 3)

def test_numeric_unambiguous_day_gt_12():
    assert parse_date("15.07.2026") == D(2026, 7, 15)

def test_numeric_month_first_when_second_gt_12():
    assert parse_date("07/15/2026") == D(2026, 7, 15)

def test_numeric_with_time_ora():
    i = parse("15.07.2026, ora 10:00")
    assert i.date == D(2026, 7, 15) and i.time == "10:00"

def test_numeric_with_plain_time():
    i = parse("31.12.2025 23:59")
    assert i.date == D(2025, 12, 31) and i.time == "23:59"

def test_numeric_dashes():
    assert parse_date("15-07-2026") == D(2026, 7, 15)

def test_ymd_dotted():
    assert parse_date("2026.07.13") == D(2026, 7, 13)

def test_invalid_date_rejected():
    assert parse_date("31.02.2026") is None
    assert parse_date("2026-13-45") is None

# ---- Romanian month names ----
def test_ro_month_full():
    assert parse_date("13 iulie 2026") == D(2026, 7, 13)

def test_ro_month_with_diacritics_and_time():
    i = parse("5 februarie 2026, ora 14:30")
    assert i.date == D(2026, 2, 5) and i.time == "14:30"

def test_ro_month_abbrev():
    assert parse_date("13 iul. 2026") == D(2026, 7, 13)

def test_ro_de_form():
    assert parse_date("13 de martie 2026") == D(2026, 3, 13)

# ---- Russian month names ----
def test_ru_month_genitive():
    assert parse_date("15 июля 2026") == D(2026, 7, 15)

def test_ru_month_with_g():
    assert parse_date("1 декабря 2025 г.") == D(2025, 12, 1)

# ---- English ----
def test_en_month_first():
    assert parse_date("July 15, 2026") == D(2026, 7, 15)

def test_en_day_first():
    assert parse_date("15 January 2026") == D(2026, 1, 15)

# ---- misc ----
def test_none_and_garbage():
    assert not parse(None)
    assert not parse("")
    assert not parse("in curand")
    assert parse_date("no date here") is None

def test_embedded_in_sentence():
    assert parse_date("Termen limita de depunere: 20.08.2026 pana la ora 11:00") == D(2026, 8, 20)
    assert parse("Termen limita: 20.08.2026 ora 11:00").time == "11:00"

def test_to_iso_and_humanize():
    assert to_iso("13 iulie 2026") == "2026-07-13"
    assert humanize("2026-07-13T06:00:00Z") == "13.07.2026, 09:00"
    assert humanize("2026-07-13") == "13.07.2026"
    assert humanize("garbage") is None

def test_accepts_date_objects():
    assert parse_date(D(2026, 5, 4)) == D(2026, 5, 4)
    assert parse(dt.datetime(2026, 5, 4, 8, 30)).time == "08:30"

def test_day_month_splits_for_the_date_badge():
    assert day_month("2026-07-27T07:00:00Z") == ("27", "Jul")
    assert day_month("27.07.2026") == ("27", "Jul")
    assert day_month("3 august 2026") == ("03", "Aug")
    assert day_month("garbage") == ("--", "")
    assert day_month(None) == ("--", "")
