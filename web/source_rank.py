from __future__ import annotations

from engine.dedup import site_token


def _catalog(store):
    cat = {"mtender": ("MTender", "api")}
    for s in store.get("sites.tenders", []) or []:
        tok = site_token(s)
        cat[tok] = (s.get("label") or s.get("url") or tok, "site")
    return cat


def sources_in_order(store):
    cat = _catalog(store)
    rank = [t for t in (store.get("sources.rank", []) or []) if t in cat]
    rest = [t for t in cat if t not in rank]
    return [(t, cat[t][0], cat[t][1]) for t in rank + rest]


def move(store, token, direction):
    order = [t for (t, _l, _k) in sources_in_order(store)]
    if token in order:
        i = order.index(token)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
    return order
