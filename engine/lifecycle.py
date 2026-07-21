from __future__ import annotations

import datetime as dt
import time

from engine.dateparse import day_end_ts, parse_date

DEFAULT_ARCHIVE_DAYS = 90

OPEN = "open"
CLOSED = "closed"
PENDING = "pending"
UNKNOWN = "unknown"


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


def _set(store, key):
    raw = store.get(key, []) or []
    return {str(s).strip().lower() for s in raw if str(s).strip()}


def closed_statuses(store):
    return _set(store, "results.closed_statuses")


def pending_statuses(store):
    return _set(store, "results.pending_statuses")


def _says(nj, names):
    for key in ("status", "status_details"):
        v = str(nj.get(key) or "").strip().lower()
        if v and v in names:
            return True
    return False


def status_text(nj):
    for key in ("status_details", "status"):
        v = str(nj.get(key) or "").strip()
        if v:
            return v
    return ""


def state_of(nj, deadline_raw, closed, pending=(), now=None):
    now = now or time.time()
    if nj.get("awarded"):
        return CLOSED
    if _says(nj, closed):
        return CLOSED
    ts = day_end_ts(deadline_raw)
    if ts is not None:
        return CLOSED if int((ts - now) // 86400) < 0 else OPEN
    if _says(nj, pending or ()):
        return PENDING
    return UNKNOWN


def keep_on_collect(nj, store, now=None):
    if not isinstance(nj, dict):
        return True
    state = state_of(nj, nj.get("deadline"), closed_statuses(store),
                     pending_statuses(store), now)
    return state != CLOSED
