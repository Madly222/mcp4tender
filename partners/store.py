from __future__ import annotations

import json
import time

from partners.profiles import get_profile as _builtin
from partners.schema import init_partner_schema


def load_profile(conn, partner):
    init_partner_schema(conn)
    row = conn.execute("SELECT profile_json FROM partner_profiles WHERE partner=?",
                       (partner,)).fetchone()
    if row:
        try:
            return json.loads(row["profile_json"] if hasattr(row, "keys") else row[0])
        except (ValueError, TypeError):
            pass
    return _builtin(partner)


def save_profile(conn, profile):
    init_partner_schema(conn)
    partner = profile["partner"]
    conn.execute(
        "INSERT INTO partner_profiles(partner, profile_json, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(partner) DO UPDATE SET profile_json=excluded.profile_json, "
        "updated_at=excluded.updated_at",
        (partner, json.dumps(profile, ensure_ascii=False), time.time()))
    conn.commit()


def list_partners(conn):
    init_partner_schema(conn)
    rows = conn.execute(
        "SELECT partner, COUNT(*) n FROM partner_offers WHERE active=1 "
        "GROUP BY partner").fetchall()
    return [(r["partner"], r["n"]) for r in rows]


def add_staging(conn, partner, filename, path, sha, detected):
    init_partner_schema(conn)
    cur = conn.execute(
        "INSERT INTO partner_staging(partner, filename, path, sha256, detected_json, "
        "created_at) VALUES(?,?,?,?,?,?)",
        (partner, filename, path, sha, json.dumps(detected, ensure_ascii=False), time.time()))
    conn.commit()
    return cur.lastrowid


def get_staging(conn, staging_id):
    init_partner_schema(conn)
    row = conn.execute("SELECT * FROM partner_staging WHERE id=?", (staging_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["detected"] = json.loads(d.get("detected_json") or "{}")
    except (ValueError, TypeError):
        d["detected"] = {}
    return d


def drop_staging(conn, staging_id):
    conn.execute("DELETE FROM partner_staging WHERE id=?", (staging_id,))
    conn.commit()
