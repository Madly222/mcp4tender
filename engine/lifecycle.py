from __future__ import annotations

import datetime as dt

from engine.dateparse import parse_date

DEFAULT_ARCHIVE_DAYS = 90


def archive_reason(pub_date, deadline, found_date=None, now=None,
                   archive_days=DEFAULT_ARCHIVE_DAYS):
    today = (now or dt.datetime.now()).date()
    if deadline is not None:
        return "deadline" if deadline < today else None
    basis = pub_date or found_date or today
    age = (today - basis).days
    if archive_days and age > archive_days:
        return "age"
    return None


def item_dates(nj):
    if not isinstance(nj, dict):
        return None, None
    pub = parse_date(nj.get("publication_date")) or parse_date(nj.get("published"))
    deadline = parse_date(nj.get("deadline"))
    return pub, deadline


def item_archive_reason(nj, found_date=None, now=None, archive_days=DEFAULT_ARCHIVE_DAYS):
    pub, deadline = item_dates(nj)
    return archive_reason(pub, deadline, found_date, now, archive_days)


def collect_ceiling(store):
    def _int(v):
        try:
            n = int(v)
            return n if n > 0 else None
        except (TypeError, ValueError):
            return None
    limits = [_int(store.get("collect.max_age_days")),
              _int(store.get("results.archive_after_days", DEFAULT_ARCHIVE_DAYS))]
    limits = [x for x in limits if x]
    return min(limits) if limits else None
