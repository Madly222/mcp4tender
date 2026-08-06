from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from partners.rank import cheapest_per_partner, multi_partner_products, top_partners
from partners.schema import init_partner_schema


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_partner_schema(c)
    return c


def _add(c, partner, mpn, price, promo=None, active=1, ptype="Network Switch"):
    c.execute(
        "INSERT INTO partner_offers(file_id,partner,sheet,row_no,brand,mpn,mpn_norm,"
        "description,product_type,type_source,price_original,currency,price_usd,promo_usd,"
        "active,extra_json,created_at) VALUES(1,?,?,1,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (partner, "S", "MikroTik", mpn, mpn.upper().replace(" ", ""), "24-port switch",
         ptype, "rule", price, "USD", price, promo, active, "{}", time.time()))
    c.commit()


def test_top3_ranks_by_regular_price_not_promo():
    c = _conn()
    _add(c, "Accent", "CRS326", 210.0)
    _add(c, "PartnerB", "CRS326", 199.0, promo=150.0)  # deep promo must NOT reorder
    _add(c, "PartnerC", "CRS326", 205.0)
    top = top_partners(c, "CRS326")
    assert [o["partner"] for o in top] == ["PartnerB", "PartnerC", "Accent"]
    assert top[0]["promo_usd"] == 150.0  # shown as a note, ranking still by 199


def test_cheapest_offer_per_partner_wins():
    c = _conn()
    _add(c, "PartnerB", "CRS326", 250.0)
    _add(c, "PartnerB", "CRS326", 199.0)
    offers = cheapest_per_partner(c, "CRS326")
    assert len(offers) == 1 and offers[0]["price_usd"] == 199.0


def test_superseded_offers_are_ignored():
    c = _conn()
    _add(c, "Accent", "CRS326", 150.0, active=0)  # old, cheaper, inactive
    _add(c, "Accent", "CRS326", 210.0, active=1)
    _add(c, "PartnerB", "CRS326", 199.0)
    top = top_partners(c, "CRS326")
    assert top[0]["partner"] == "PartnerB" and top[0]["price_usd"] == 199.0
    assert all(o["price_usd"] != 150.0 for o in top)


def test_only_multi_partner_products_are_listed():
    c = _conn()
    _add(c, "Accent", "CRS326", 210.0)
    _add(c, "PartnerB", "CRS326", 199.0)
    _add(c, "Accent", "SOLO-1", 10.0)  # only one partner -> not comparable
    rows = multi_partner_products(c)
    keys = {r["mpn_norm"] for r in rows}
    assert "CRS326" in keys and "SOLO-1" not in keys
    row = next(r for r in rows if r["mpn_norm"] == "CRS326")
    assert row["partners"] == 2 and row["best_usd"] == 199.0


def test_limit_is_three():
    c = _conn()
    for i, p in enumerate(["A", "B", "C", "D", "E"]):
        _add(c, p, "CRS326", 100.0 + i)
    assert len(top_partners(c, "CRS326")) == 3
