from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def norm_label(value):
    if value is None:
        return ""
    return _WS.sub(" ", str(value).strip().casefold())


def norm_mpn(value):
    if value is None:
        return ""
    return _WS.sub("", str(value).strip().upper())


def clean_text(value):
    if value is None:
        return None
    out = _WS.sub(" ", str(value).strip())
    return out or None


def to_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not raw:
        return None
    raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None
