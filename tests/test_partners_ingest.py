from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
import pytest

from partners.ingest import ingest_workbook
from partners.profiles import get_profile
from partners.schema import init_partner_schema

HEADER = ["", "BRAND", "P/N", "Description", "Online, LEI", "", "Online, USD",
          "Dealer B, USD", "Promo Dealer, USD ", "", "Warranty", "Stock"]


def _make_book(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PriceList"
    for c, val in enumerate(HEADER, start=1):
        ws.cell(7, c, val)
    rows = [
        ("cat", 0, "PC COMPONENTS"),
        ("cat", 1, "CASE"),
        ("cat", 2, "SHARKOON"),
        ("prod", 3, ("SHARKOON", "RGB SLIDER BK", "Sharkoon RGB SLIDER Black ATX", 890, 48.5, 46, None)),
        ("prod", 3, ("SHARKOON", "RGB FLOW", "Sharkoon RGB FLOW ATX", 1199, 64, 61, None)),
        ("cat", 1, "COOLERS"),
        ("cat", 2, "Case Fan/Fan Control"),
        ("prod", 3, ("DEEPCOOL", "XDC-RF120B", "120mm Case Fan DEEPCOOL", 100, 5.6, 4.7, 4.0)),
        ("cat", 0, "PERIPHERALS"),
        ("cat", 1, "MICE"),
        ("prod", 2, ("LOGITECH", "M90", "Logitech M90 mouse", 120, 6.5, 6.0, None)),
    ]
    r = 8
    for kind, level, payload in rows:
        if kind == "cat":
            ws.cell(r, 1, payload)
        else:
            brand, mpn, desc, lei, retail, dealer, promo = payload
            ws.cell(r, 2, brand)
            ws.cell(r, 3, mpn)
            ws.cell(r, 4, desc)
            ws.cell(r, 5, lei)
            ws.cell(r, 7, retail)
            ws.cell(r, 8, dealer)
            ws.cell(r, 9, promo)
            ws.cell(r, 11, "24 Month")
        ws.row_dimensions[r].outline_level = level
        r += 1
    refurb = wb.create_sheet("Used-Refurb")
    refurb.cell(1, 1, "should be skipped")
    wb.save(path)


def _conn(tmp_path):
    conn = sqlite3.connect(tmp_path / "p.db")
    conn.row_factory = sqlite3.Row
    init_partner_schema(conn)
    return conn


def test_accent_shaped_file_ingests_cleanly(tmp_path):
    f = tmp_path / "accent.xlsx"
    _make_book(f)
    conn = _conn(tmp_path)
    report = ingest_workbook(conn, str(f), get_profile("accent"))
    pl = report["sheets"]["PriceList"]
    assert pl["header_row"] == 7
    assert pl["products"] == 4 and pl["unparsed"] == 0
    assert report["sheets"]["Used-Refurb"]["skipped"]
    n = conn.execute("SELECT COUNT(*) c FROM partner_offers").fetchone()["c"]
    assert n == 4


def test_breadcrumb_follows_outline_levels(tmp_path):
    f = tmp_path / "a.xlsx"
    _make_book(f)
    conn = _conn(tmp_path)
    ingest_workbook(conn, str(f), get_profile("accent"))
    row = conn.execute("SELECT category_path FROM partner_offers WHERE mpn='RGB FLOW'").fetchone()
    assert row["category_path"] == "PC COMPONENTS / CASE / SHARKOON"
    fan = conn.execute("SELECT category_path FROM partner_offers WHERE mpn='XDC-RF120B'").fetchone()
    assert fan["category_path"] == "PC COMPONENTS / COOLERS / Case Fan/Fan Control"
    # a level-2 product under a fresh level-0 category must NOT keep stale deeper crumbs
    mouse = conn.execute("SELECT category_path FROM partner_offers WHERE mpn='M90'").fetchone()
    assert mouse["category_path"] == "PERIPHERALS / MICE"


def test_price_and_promo_are_normalized(tmp_path):
    f = tmp_path / "a.xlsx"
    _make_book(f)
    conn = _conn(tmp_path)
    ingest_workbook(conn, str(f), get_profile("accent"))
    r = conn.execute("SELECT price_usd, promo_usd, currency, mpn_norm, extra_json "
                     "FROM partner_offers WHERE mpn='XDC-RF120B'").fetchone()
    assert r["price_usd"] == 4.7 and r["promo_usd"] == 4.0 and r["currency"] == "USD"
    assert r["mpn_norm"] == "XDC-RF120B"
    assert '"price_lei": 100' in r["extra_json"]


def test_resending_the_same_file_is_rejected(tmp_path):
    f = tmp_path / "a.xlsx"
    _make_book(f)
    conn = _conn(tmp_path)
    ingest_workbook(conn, str(f), get_profile("accent"))
    with pytest.raises(sqlite3.IntegrityError):
        ingest_workbook(conn, str(f), get_profile("accent"))
