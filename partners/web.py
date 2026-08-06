from __future__ import annotations

import os
import time

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from partners import store as pstore
from partners import webrender as R
from partners.detect import detect_workbook
from partners.ingest import file_sha256, ingest_workbook
from partners.schema import init_partner_schema
from web.render import _e
from web.user.layout import render

router = APIRouter()

PER_PAGE = 50


def _uploads_dir(request):
    base = os.path.dirname(os.path.abspath(getattr(request.state, "db_path", "."))) or "."
    path = os.path.join(base, "partner_uploads")
    os.makedirs(path, exist_ok=True)
    return path


@router.get("/app/partners")
def pool(request: Request, q: str = "", partner: str = "", ptype: str = "", page: int = 1):
    conn = request.state.conn
    init_partner_schema(conn)
    where, args = ["active = 1"], []
    if partner:
        where.append("partner = ?")
        args.append(partner)
    if ptype:
        where.append("product_type = ?")
        args.append(ptype)
    if q:
        like = f"%{q.strip()}%"
        where.append("(brand LIKE ? OR mpn LIKE ? OR description LIKE ? OR category_path LIKE ?)")
        args += [like, like, like, like]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) c FROM partner_offers {clause}", args).fetchone()["c"]
    page = max(1, page)
    rows = conn.execute(
        f"SELECT * FROM partner_offers {clause} ORDER BY partner, category_path, "
        f"price_usd IS NULL, price_usd LIMIT ? OFFSET ?",
        args + [PER_PAGE, (page - 1) * PER_PAGE]).fetchall()
    partners = pstore.list_partners(conn)
    types = [r["product_type"] for r in conn.execute(
        "SELECT product_type, COUNT(*) n FROM partner_offers WHERE product_type IS NOT NULL "
        "AND active=1 GROUP BY product_type ORDER BY n DESC").fetchall()]
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    pager = ""
    if pages > 1:
        qs = f"q={_e(q)}&partner={_e(partner)}&ptype={_e(ptype)}&"
        prev = (f'<a class="btn ghost sm" href="/app/partners?{qs}page={page - 1}">Previous</a>'
                if page > 1 else "<span></span>")
        nxt = (f'<a class="btn ghost sm" href="/app/partners?{qs}page={page + 1}">Next</a>'
               if page < pages else "<span></span>")
        pager = ('<div class="fb" style="justify-content:space-between;padding:12px 15px;'
                 f'border-top:1px solid var(--line)">{prev}'
                 f'<span class="num">Page {page} of {pages} · {total} products</span>{nxt}</div>')
    body = R.pool_filters(q, partner, partners, ptype, types) + R.offers_table(rows) + pager
    return render(request, "Partners", body, heading="Product pool", heading_icon="archive",
                  lede=f"{total} products from {len(partners)} partner(s)")


@router.get("/app/partners/upload")
def upload_page(request: Request):
    return render(request, "Upload price-list", R.upload_form(),
                  heading="Upload price-list", heading_icon="archive")


@router.post("/app/partners/upload")
async def upload_submit(request: Request, partner: str = Form(...),
                        file: UploadFile = File(...)):
    if request.state.readonly:
        return RedirectResponse("/app/partners", status_code=303)
    data = await file.read()
    safe = "".join(c for c in (file.filename or "upload.xlsx") if c.isalnum() or c in "._-")
    dest = os.path.join(_uploads_dir(request), f"{int(time.time())}_{safe}")
    with open(dest, "wb") as fh:
        fh.write(data)
    detected = detect_workbook(dest)
    sid = pstore.add_staging(request.state.conn, partner.strip(),
                             file.filename or safe, dest, file_sha256(dest), detected)
    return RedirectResponse(f"/app/partners/confirm/{sid}", status_code=303)


@router.get("/app/partners/confirm/{sid}")
def confirm_page(request: Request, sid: int):
    st = pstore.get_staging(request.state.conn, sid)
    if not st:
        return RedirectResponse("/app/partners", status_code=303)
    body = R.confirm_form(sid, st["partner"], st["detected"])
    return render(request, "Confirm columns", body, heading=f"Confirm — {st['partner']}",
                  heading_icon="check-circle",
                  lede="Check the detected columns, fix any that are wrong, then import.")


def _profile_from_form(form, partner, detected):
    sheets = []
    for i, sheet in enumerate(detected.get("sheets", [])):
        name = form.get(f"sheet_{i}") or sheet["name"]
        if not form.get(f"ingest_{i}"):
            sheets.append({"name": name, "ingest": False, "reason": "unchecked at import"})
            continue
        columns, tokens = {}, []
        for field, _label in R.FIELD_LABELS:
            val = (form.get(f"map_{i}_{field}") or "").strip()
            if val:
                columns[field] = val
                if field in ("brand", "mpn", "description"):
                    tokens.append(val)
        sheets.append({"name": name, "ingest": True, "header_tokens": tokens,
                       "columns": columns, "cost_field": "cost", "promo_field": "promo",
                       "cost_currency": form.get(f"cur_{i}") or "USD", "category": "outline"})
    return {"partner": partner, "sheets": sheets}


@router.post("/app/partners/confirm/{sid}")
async def confirm_submit(request: Request, sid: int):
    conn = request.state.conn
    if request.state.readonly:
        return RedirectResponse("/app/partners", status_code=303)
    st = pstore.get_staging(conn, sid)
    if not st:
        return RedirectResponse("/app/partners", status_code=303)
    form = await request.form()
    partner = (form.get("partner") or st["partner"]).strip()
    profile = _profile_from_form(form, partner, st["detected"])
    pstore.save_profile(conn, profile)
    fx = request.state.store.get("suppliers.fx_rates", {}) or {}
    try:
        report = ingest_workbook(conn, st["path"], profile, fx)
        total = sum(v.get("products", 0) for v in report["sheets"].values()
                    if isinstance(v, dict))
        msg = f"imported {total} products"
    except Exception as exc:
        msg = f"already imported or failed: {type(exc).__name__}"
    pstore.drop_staging(conn, sid)
    return RedirectResponse(f"/app/partners?q=&partner={partner}", status_code=303)
