from __future__ import annotations

import os

from engine import db
from engine.config_store import ConfigStore
from web.render import _login


def _open(db_path):
    conn = db.connect(db_path)
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    return conn, store


def _expected_token(store):
    return os.environ.get("TENDERENGINE_WEB_TOKEN") or store.get("web.token", "") or ""


def _check_auth(request, token):
    if not token:
        return True, "open"
    if request.cookies.get("te_token") == token:
        return True, "cookie"
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and auth[7:] == token:
        return True, "header"
    if request.headers.get("x-token") == token:
        return True, "header"
    if request.query_params.get("token") == token:
        return True, "query"
    return False, "none"


def _schedule_restart(delay=1.0):
    import threading
    import time

    def _die():
        time.sleep(delay)
        os._exit(3)

    threading.Thread(target=_die, daemon=True).start()


def _accounts_on(conn):
    """True once at least one company account exists. Until then the old
    web.token flow stays in charge, so an existing install is never locked out."""
    try:
        from engine import accounts
        return accounts.count(conn) > 0
    except Exception:
        return False


def add_context_middleware(app, db_path):
    @app.middleware("http")
    async def context(request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        conn, store = _open(db_path)
        request.state.conn = conn
        request.state.store = store
        request.state.readonly = bool(store.get("web.read_only", False))
        request.state.account = None
        try:
            if _accounts_on(conn):
                from engine import accounts
                acct = accounts.session_account(conn, request.cookies.get("te_session"))
                request.state.account = acct
                request.state.authed = bool(acct)
                unguarded = ((request.url.path == "/login" and request.method == "POST")
                             or request.url.path == "/logout")
                if not acct and not unguarded:
                    return _login(request)
                return await call_next(request)
            token = _expected_token(store)
            authed, via = _check_auth(request, token)
            request.state.authed = authed
            if not authed and not (request.url.path == "/login" and request.method == "POST"):
                return _login(request)
            response = await call_next(request)
            if via == "query" and token:
                response.set_cookie("te_token", token, httponly=True, samesite="lax")
            return response
        finally:
            conn.close()
