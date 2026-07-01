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


def add_context_middleware(app, db_path):
    @app.middleware("http")
    async def context(request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        conn, store = _open(db_path)
        request.state.conn = conn
        request.state.store = store
        request.state.readonly = bool(store.get("web.read_only", False))
        try:
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
