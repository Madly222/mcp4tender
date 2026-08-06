from __future__ import annotations

from partners.profiles.accent import ACCENT

_REGISTRY = {p["partner"].casefold(): p for p in (ACCENT,)}


def get_profile(name):
    return _REGISTRY.get(str(name).casefold())


def known_partners():
    return sorted(_REGISTRY)
