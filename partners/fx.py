from __future__ import annotations

import json


def read_fx_rates(conn):
    try:
        row = conn.execute(
            "SELECT value_json FROM configs WHERE key='suppliers.fx_rates' AND active=1"
        ).fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    raw = row["value_json"] if hasattr(row, "keys") else row[0]
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def _rate(fx, frm, to):
    if frm == to:
        return 1.0
    direct = fx.get(f"{frm}->{to}")
    if direct:
        return float(direct)
    inv = fx.get(f"{to}->{frm}")
    if inv:
        return 1.0 / float(inv)
    return None


def to_usd(amount, currency, fx_rates):
    if amount is None:
        return None
    cur = (currency or "USD").upper()
    if cur == "USD":
        return float(amount)
    fx = fx_rates or {}
    direct = _rate(fx, cur, "USD")
    if direct is not None:
        return float(amount) * direct
    to_mdl = _rate(fx, cur, "MDL")
    usd_mdl = _rate(fx, "USD", "MDL")
    if to_mdl is not None and usd_mdl:
        return float(amount) * to_mdl / usd_mdl
    return None


def backfill_usd(conn, fx_rates):
    rows = conn.execute(
        "SELECT id, price_original, currency FROM partner_offers "
        "WHERE price_usd IS NULL AND price_original IS NOT NULL").fetchall()
    filled = 0
    for r in rows:
        val = to_usd(r["price_original"], r["currency"], fx_rates)
        if val is not None:
            conn.execute("UPDATE partner_offers SET price_usd=? WHERE id=?", (val, r["id"]))
            filled += 1
    conn.commit()
    return {"missing": len(rows), "filled": filled}
