from __future__ import annotations


def cheapest_per_partner(conn, mpn_norm):
    if not mpn_norm:
        return []
    rows = conn.execute(
        "SELECT partner, brand, mpn, description, product_type, price_usd, promo_usd, "
        "currency, price_original, warranty, stock FROM partner_offers "
        "WHERE active=1 AND mpn_norm=? AND mpn_norm != '' "
        "ORDER BY partner, price_usd IS NULL, price_usd", (mpn_norm,)).fetchall()
    best = {}
    for r in rows:
        if r["partner"] not in best:
            best[r["partner"]] = r
    offers = list(best.values())
    offers.sort(key=lambda r: (r["price_usd"] is None,
                               r["price_usd"] if r["price_usd"] is not None else 0.0))
    return offers


def top_partners(conn, mpn_norm, limit=3):
    return cheapest_per_partner(conn, mpn_norm)[:limit]


def multi_partner_products(conn, q="", ptype="", limit=100):
    where = ["active=1", "mpn_norm != ''"]
    args = []
    if ptype:
        where.append("product_type = ?")
        args.append(ptype)
    if q:
        like = f"%{q.strip()}%"
        where.append("(brand LIKE ? OR mpn LIKE ? OR description LIKE ?)")
        args += [like, like, like]
    clause = " AND ".join(where)
    return conn.execute(
        f"SELECT mpn_norm, MAX(brand) brand, MAX(description) description, "
        f"MAX(product_type) product_type, COUNT(DISTINCT partner) partners, "
        f"MIN(price_usd) best_usd FROM partner_offers WHERE {clause} "
        f"GROUP BY mpn_norm HAVING partners > 1 ORDER BY partners DESC, best_usd LIMIT ?",
        args + [limit]).fetchall()
