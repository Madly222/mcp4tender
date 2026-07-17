from __future__ import annotations

import time

from engine.dateparse import day_end_ts
from web.render import _e

OPEN = "open"
CLOSED = "closed"
UNKNOWN = "unknown"

LABEL = {OPEN: "Open for bids", CLOSED: "Bidding closed", UNKNOWN: "N/A"}


def closed_statuses(store):
    raw = store.get("results.closed_statuses", []) or []
    return {str(s).strip().lower() for s in raw if str(s).strip()}


def status_text(nj):
    """Whatever the source calls the current stage, in the source's own words."""
    for key in ("status_details", "status"):
        v = str(nj.get(key) or "").strip()
        if v:
            return v
    return ""


def state_of(nj, deadline_raw, closed, now=None):
    """Can we still submit a bid?

    Checked in order of how much each signal can be trusted:
      1. awarded  - somebody is already being awarded the job. Structural, so it holds
                    whatever the portal calls the stage and in whatever language.
      2. status / status_details in the configured closed list.
      3. a submission deadline still ahead of us.
    A status merely EXISTING proves nothing: OCDS keeps tender.status = "active" through
    qualification and award, long after bidding shut.
    """
    now = now or time.time()
    if nj.get("awarded"):
        return CLOSED
    for key in ("status", "status_details"):
        v = str(nj.get(key) or "").strip().lower()
        if v and v in closed:
            return CLOSED
    ts = day_end_ts(deadline_raw)
    if ts is not None:
        return CLOSED if int((ts - now) // 86400) < 0 else OPEN
    return UNKNOWN


def chip(state, nj=None):
    if state == OPEN:
        return ""
    if state == CLOSED:
        return f'<span class="chip bad">{LABEL[CLOSED]}</span>'
    text = status_text(nj or {})
    if not text:
        return '<span class="chip plain">N/A</span>'
    return (f'<span class="chip warn" title="No submission deadline in the record — '
            f'add this to Company settings if it means bidding is over">{_e(text[:34])}</span>')


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
        state = state_of(nj, nj.get("deadline"), closed)
        if state == CLOSED:
            gone.append(r["id"])
        else:
            kept.append((r, state))
    return kept, gone
