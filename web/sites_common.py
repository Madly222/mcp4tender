from __future__ import annotations

import json
from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from web.render import _e

router = APIRouter()


def _redir_sites(msg="", err=""):
    from urllib.parse import urlencode
    q = urlencode({k: v for k, v in (("msg", msg), ("err", err)) if v})
    return RedirectResponse("/app/settings/sources" + ("?" + q if q else ""),
                            status_code=303)


def _validate_url(url):
    from urllib.parse import urlparse
    u = (url or "").strip()
    if not u:
        return False, "empty URL"
    if " " in u:
        return False, "URL contains spaces"
    p = urlparse(u)
    if p.scheme not in ("http", "https"):
        return False, "missing http:// or https://"
    if not p.netloc:
        return False, "missing domain name"
    return True, ""


def _probe_url(url):
    from engine.http import get_text
    try:
        get_text(url, timeout=8, retries=0)
        return True, ""
    except Exception as exc:
        msg = str(exc)
        return False, msg.split(":", 2)[-1].strip() if ":" in msg else msg


def _crawl_rows(conn, site_ids):
    out = {}
    ids = [s for s in site_ids if s]
    if not ids:
        return out
    qs = ",".join("?" * len(ids))
    for r in conn.execute(
        f"SELECT site_id, next_url, auth_json, total_collected, exhausted, total_estimate, "
        f"note, detected_count FROM crawl_state WHERE site_id IN ({qs})", ids).fetchall():
        out[r["site_id"]] = r
    return out


def _set_auth(conn, site_id, auth):
    payload = json.dumps(auth) if auth else None
    conn.execute(
        "INSERT INTO crawl_state(site_id, auth_json) VALUES(?,?) "
        "ON CONFLICT(site_id) DO UPDATE SET auth_json=excluded.auth_json",
        (site_id, payload))
    conn.commit()


def _bar(collected, est, detected=None):
    if est and est > 0:
        pct = min(100, round(collected / est * 100))
        label = f"{collected} / {est} ({pct}%)"
    elif detected and detected > 0:
        pct = 0
        label = f"{collected} collected · {detected}+ found on site"
    else:
        pct = 0
        label = f"{collected} collected · est. unknown"
    return (f'<div style="min-width:150px">'
            f'<div style="background:var(--chip);border:1px solid var(--line);'
            f'border-radius:6px;height:9px;overflow:hidden">'
            f'<div style="background:var(--acc);height:100%;width:{pct}%"></div></div>'
            f'<div class="mut" style="font-size:11px;margin-top:4px">{_e(label)}</div></div>')
