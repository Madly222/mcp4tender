from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent / "static"
_CACHE = {}


def _load(rel):
    hit = _CACHE.get(rel)
    if hit is not None:
        return hit
    target = (STATIC_DIR / rel).resolve()
    try:
        target.relative_to(STATIC_DIR)
    except ValueError:
        return None
    if not target.is_file():
        return None
    data = target.read_bytes()
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    etag = '"%s"' % hashlib.sha1(data).hexdigest()[:16]
    _CACHE[rel] = (data, ctype, etag)
    return _CACHE[rel]


def asset_version(rel):
    hit = _load(rel)
    return hit[2].strip('"') if hit else "0"


@router.get("/static/{rel:path}")
def static(request: Request, rel: str):
    hit = _load(rel)
    if hit is None:
        return Response(status_code=404)
    data, ctype, etag = hit
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(data, media_type=ctype,
                    headers={"ETag": etag, "Cache-Control": "public, max-age=300"})
