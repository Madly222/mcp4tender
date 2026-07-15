from __future__ import annotations

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from web import (assets, routes_analyze, routes_config, routes_digest, routes_schedule,
                 routes_settings, routes_sites, routes_stage, routes_results)
from web.user import routes_browse, routes_home, routes_inbox, routes_qualified
from web.context import add_context_middleware, _expected_token
from web.render import _login


def create_app(db_path):
    app = FastAPI(title="TenderEngine Web")
    add_context_middleware(app, db_path)
    app.include_router(assets.router)

    @app.get("/healthz")
    def healthz():
        return JSONResponse({"status": "ok"})

    @app.post("/login")
    def do_login(request: Request, token: str = Form(""), login: str = Form(""),
                 password: str = Form("")):
        from engine import accounts
        conn = request.state.conn
        store = request.state.store
        if accounts.count(conn) > 0:
            ip = request.client.host if request.client else "?"
            if accounts.is_locked(conn, ip):
                return _login(request, "Too many failed attempts. Try again in a few minutes.")
            acct = accounts.authenticate(conn, login, password)
            accounts.record_attempt(conn, ip, bool(acct))
            if not acct:
                return _login(request, "Wrong login or password.")
            days = int(store.get("web.session_days", 30) or 30)
            sid = accounts.new_session(conn, acct["id"], days=days)
            from web.roles import landing_for
            resp = RedirectResponse(landing_for(acct), status_code=303)
            resp.set_cookie("te_session", sid, httponly=True, samesite="lax",
                            max_age=days * 86400,
                            secure=bool(store.get("web.cookie_secure", False)))
            return resp
        expected = _expected_token(store)
        if expected and token == expected:
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie("te_token", token, httponly=True, samesite="lax")
            return resp
        return _login(request, "Wrong token.")

    @app.get("/logout")
    def logout(request: Request):
        from engine import accounts
        sid = request.cookies.get("te_session")
        if sid:
            accounts.end_session(request.state.conn, sid)
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie("te_session")
        resp.delete_cookie("te_token")
        return resp

    app.include_router(routes_digest.router)
    app.include_router(routes_config.router)
    app.include_router(routes_sites.router)
    app.include_router(routes_analyze.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_stage.router)
    app.include_router(routes_results.router)
    app.include_router(routes_schedule.router)
    app.include_router(routes_home.router)
    app.include_router(routes_inbox.router)
    app.include_router(routes_qualified.router)
    app.include_router(routes_browse.router)
    return app
