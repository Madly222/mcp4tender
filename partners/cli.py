from __future__ import annotations

import argparse
import sqlite3
import sys

from partners.ingest import ingest_workbook
from partners.profiles import get_profile, known_partners
from partners.schema import init_partner_schema


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_partner_schema(conn)
    return conn


def cmd_ingest(args):
    profile = get_profile(args.partner)
    if not profile:
        print(f"unknown partner '{args.partner}'. known: {', '.join(known_partners())}")
        return 2
    conn = _connect(args.db)
    report = ingest_workbook(conn, args.file, profile)
    print(f"partner: {report['partner']}   file_id: {report['file_id']}")
    total = 0
    for sheet, stats in report["sheets"].items():
        if "skipped" in stats:
            print(f"  [skip] {sheet}: {stats['skipped']}")
            continue
        prod = stats.get("products", 0)
        total += prod
        miss = stats.get("missing_columns") or []
        miss_s = f"  missing_cols={miss}" if miss else ""
        print(f"  [ok]   {sheet}: header_row={stats.get('header_row')} "
              f"products={prod} categories={stats.get('categories', 0)} "
              f"unparsed={stats.get('unparsed', 0)}{miss_s}")
    print(f"total offers ingested: {total}")
    return 0


def cmd_sample(args):
    conn = _connect(args.db)
    rows = conn.execute(
        "SELECT partner, brand, mpn, price_usd, promo_usd, category_path, "
        "substr(description,1,60) d FROM partner_offers ORDER BY id LIMIT ?",
        (args.n,)).fetchall()
    for r in rows:
        promo = f" promo={r['promo_usd']}" if r["promo_usd"] is not None else ""
        print(f"{r['partner']:8} {str(r['brand']):12} {str(r['mpn']):20} "
              f"${r['price_usd']}{promo}  [{r['category_path']}]  {r['d']}")
    return 0


def cmd_categorize(args):
    from partners.categorize import reclassify_all
    conn = _connect(args.db)
    r = reclassify_all(conn)
    pct = (r["typed"] * 100 // r["total"]) if r["total"] else 0
    rule_pct = (r["by_rule"] * 100 // r["total"]) if r["total"] else 0
    print(f"reclassified {r['total']} offers: typed {r['typed']} ({pct}%), "
          f"by rule {r['by_rule']} ({rule_pct}%), path-fallback {r['typed'] - r['by_rule']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="partners")
    ap.add_argument("--db", default="tenderengine.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest")
    p.add_argument("--partner", required=True)
    p.add_argument("file")
    p.set_defaults(func=cmd_ingest)
    s = sub.add_parser("sample")
    s.add_argument("-n", type=int, default=10)
    s.set_defaults(func=cmd_sample)
    z = sub.add_parser("categorize")
    z.set_defaults(func=cmd_categorize)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
