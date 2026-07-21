from __future__ import annotations

from engine.lifecycle import (  # noqa: F401
    CLOSED, OPEN, PENDING, UNKNOWN, _says, closed_statuses, pending_statuses,
    state_of, status_text,
)
from web.render import _e

LABEL = {OPEN: "Open for bids", CLOSED: "Bidding closed",
         PENDING: "Not open yet", UNKNOWN: "N/A"}


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
