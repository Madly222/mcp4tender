from __future__ import annotations

import time

from engine.dateparse import day_end_ts

OPEN = "open"
CLOSED = "closed"
UNKNOWN = "unknown"

LABEL = {OPEN: "Open for bids", CLOSED: "Bidding closed", UNKNOWN: "N/A"}


def closed_statuses(store):
    raw = store.get("results.closed_statuses", []) or []
    return {str(s).strip().lower() for s in raw if str(s).strip()}


def state_of(status, deadline_raw, closed, now=None):
    now = now or time.time()
    st = str(status or "").strip().lower()
    if st and st in closed:
        return CLOSED
    ts = day_end_ts(deadline_raw)
    if ts is not None:
        return CLOSED if int((ts - now) // 86400) < 0 else OPEN
    return OPEN if st else UNKNOWN


def chip(state):
    if state == OPEN:
        return ""
    cls = "bad" if state == CLOSED else "plain"
    return f'<span class="chip {cls}">{LABEL[state]}</span>'


def split(rows, store, decided=()):
    """Partition rows into (kept_with_state, closed_ids).

    The ONLY place the inbox rule lives. The list, the nav badge and the sweep all call
    this, so a tender can never be visible in one and counted in another.
    """
    from web.user import cards
    closed = closed_statuses(store)
    kept, gone = [], []
    for r in rows:
        if r["id"] in decided:
            continue
        nj = cards.nj_of(r)
        state = state_of(nj.get("status"), cards.deadline_of(r, nj)[0], closed)
        if state == CLOSED:
            gone.append(r["id"])
        else:
            kept.append((r, state))
    return kept, gone
