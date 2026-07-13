from __future__ import annotations

import datetime as dt

from engine.dateparse import parse_date
from engine.jsonutil import loads_loose
from engine.lifecycle import archive_reason

SEGMENTS = ("new", "history", "archive")

DEFAULT_NEW_DAYS = 7
DEFAULT_ARCHIVE_DAYS = 90


def tender_pub_date(nj):
    if not isinstance(nj, dict):
        return None
    return parse_date(nj.get("publication_date")) or parse_date(nj.get("published"))


def tender_deadline(nj):
    if not isinstance(nj, dict):
        return None
    return parse_date(nj.get("deadline"))


def read_thresholds(store):
    return (int(store.get("results.new_days", DEFAULT_NEW_DAYS)),
            int(store.get("results.archive_after_days", DEFAULT_ARCHIVE_DAYS)))


def classify_segment(origin, created_at, pub_date, deadline, now=None,
                     new_days=DEFAULT_NEW_DAYS, archive_days=DEFAULT_ARCHIVE_DAYS):
    now = now or dt.datetime.now()
    today = now.date()
    found = dt.datetime.fromtimestamp(created_at).date() if created_at else today
    if archive_reason(pub_date, deadline, found, now, archive_days):
        return "archive"
    found_age = (today - found).days
    if origin == "incremental" and found_age <= new_days:
        return "new"
    return "history"


def classify_row(row, store, now=None):
    nj = loads_loose(row["normalized_json"]) if row["normalized_json"] else {}
    new_days, archive_days = read_thresholds(store)
    origin = row["origin"] if "origin" in row.keys() else None
    return classify_segment(origin or "backfill", row["created_at"],
                            tender_pub_date(nj), tender_deadline(nj),
                            now=now, new_days=new_days, archive_days=archive_days)


def partition(rows, store, now=None):
    out = {s: [] for s in SEGMENTS}
    for r in rows:
        out[classify_row(r, store, now=now)].append(r)
    return out
