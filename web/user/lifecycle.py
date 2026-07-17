from __future__ import annotations

import time

from engine.dateparse import day_end_ts
from web.render import _e

OPEN = "open"
CLOSED = "closed"
PENDING = "pending"
UNKNOWN = "unknown"

LABEL = {OPEN: "Open for bids", CLOSED: "Bidding closed",
         PENDING: "Not open yet", UNKNOWN: "N/A"}


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
    """Whatever the source calls the current stage, in the source's own words."""
    for key in ("status_details", "status"):
        v = str(nj.get(key) or "").strip()
        if v:
            return v
    return ""


def state_of(nj, deadline_raw, closed, pending=(), now=None):
    """Can we still submit a bid?

    Checked in order of how much each signal can be trusted:
      1. awarded  - somebody is already being awarded the job. Structural, so it holds
                    whatever the portal calls the stage and in whatever language.
      2. status / status_details in the configured closed list.
      3. a submission deadline: still ahead -> OPEN, behind us -> CLOSED. A real date
         outranks any label, so a plan that already carries a submission window is a
         live tender, not a plan.
      4. status / status_details in the configured pending list -> not open YET.
    A status merely EXISTING proves nothing: OCDS keeps tender.status = "active" through
    qualification and award, long after bidding shut.
    """
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
    """Partition rows into (open_or_unknown, closed_ids, not_open_yet).

    The ONLY place the inbox rule lives. The list, the nav badges, the sweep and the
    Not-open-yet page all call this, so a tender can never be visible in one place and
    counted in another.

    Every bucket is COMPUTED here, never stored. That is deliberate: when a plan finally
    grows a submission window it walks into the inbox by itself on the next page load.
    Writing "not open yet" into tender_work would make it a human decision and bury the
    tender for good.
    """
    from web.user import cards
    closed = closed_statuses(store)
    pending = pending_statuses(store)
    live, gone, waiting = [], [], []
    for r in rows:
        if r["id"] in decided:
            continue
        nj = cards.nj_of(r)
        state = state_of(nj, nj.get("deadline"), closed, pending)
        if state == CLOSED:
            gone.append(r["id"])
        elif state == PENDING:
            waiting.append((r, state))
        else:
            live.append((r, state))
    return live, gone, waiting
