from __future__ import annotations

from engine import accounts

USER_PREFIXES = ("/app", "/static/")
ALWAYS_OPEN = ("/login", "/logout", "/healthz")


def is_user_zone(path):
    return path == "/app" or any(path.startswith(p) for p in USER_PREFIXES)


def may_visit(acct, path):
    if acct is None or accounts.is_admin(acct):
        return True
    return is_user_zone(path) or path in ALWAYS_OPEN


def landing_for(acct):
    if acct is None or accounts.is_admin(acct):
        return "/"
    return "/app"
