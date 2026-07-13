from __future__ import annotations

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from web import (routes_analyze, routes_config, routes_digest, routes_schedule,
                 routes_settings, routes_sites, routes_stage, routes_results)
from web.context import add_context_middleware, _expected_token
from web.render import _login


def create_app(db_path):
    app = FastAPI(title="TenderEngine Web")
    add_context_middleware(app, db_path)

    @app.get("/healthz")
    def healthz():
        return JSONResponse({"status": "ok"})

    @app.post("/login")
    def login(request: Request, token: str = Form("")):
        expected = _expected_token(request.state.store)
        if expected and token == expected:
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie("te_token", token, httponly=True, samesite="lax")
            return resp
        return _login(request, "Wrong token.")

    app.include_router(routes_digest.router)
    app.include_router(routes_config.router)
    app.include_router(routes_sites.router)
    app.include_router(routes_analyze.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_stage.router)
    app.include_router(routes_results.router)
    app.include_router(routes_schedule.router)
    return app
