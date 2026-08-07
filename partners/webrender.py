from __future__ import annotations

from web.render import _e

FIELD_LABELS = (
    ("brand", "Brand"),
    ("mpn", "Article / P/N"),
    ("description", "Description"),
    ("cost", "Our cost (price we pay)"),
    ("promo", "Promo price"),
    ("price_lei", "Retail, local currency"),
    ("retail_usd", "Retail, USD"),
    ("warranty", "Warranty"),
    ("stock", "Stock"),
)

CURRENCIES = ("USD", "EUR", "MDL", "RON")


def upload_form():
    return (
        '<form method="post" action="/app/partners/upload" enctype="multipart/form-data" '
        'class="filters" style="max-width:620px">'
        f'<div class="fh">Upload a partner price-list</div><div class="fb" '
        'style="flex-direction:column;align-items:stretch;gap:12px">'
        '<label class="pref-h"><span>Partner name</span>'
        '<input class="grow" type="text" name="partner" required '
        'placeholder="e.g. Accent"></label>'
        '<label class="pref-h"><span>Excel file (.xlsx)</span>'
        '<input type="file" name="file" accept=".xlsx" required></label>'
        '<button class="btn">Upload &amp; detect columns</button>'
        '</div></form>'
        '<p class="pref-help">The columns are detected automatically; you confirm the '
        'mapping on the next screen. Images in the file are ignored.</p>')


def _select(name, options, chosen):
    opts = ['<option value="">— none —</option>']
    for label in options:
        sel = " selected" if label == chosen else ""
        opts.append(f'<option value="{_e(label)}"{sel}>{_e(label)}</option>')
    return f'<select name="{_e(name)}">' + "".join(opts) + "</select>"


def edit_form(partner, detected, saved_profile):
    saved = {s["name"]: s for s in (saved_profile or {}).get("sheets", [])}
    rows = [f'<input type="hidden" name="partner" value="{_e(partner)}">']
    for i, sheet in enumerate(detected.get("sheets", [])):
        name = sheet["name"]
        det = sheet.get("detected")
        labels = [x for x in (det["labels"] if det else []) if x]
        scfg = saved.get(name, {})
        cols = dict((det.get("columns") if det else {}) or {})
        cols.update(scfg.get("columns", {}) or {})
        cur_ccy = scfg.get("cost_currency") or (det.get("cost_currency", "USD") if det else "USD")
        checked = " checked" if scfg.get("ingest", sheet.get("ingest")) else ""
        rows.append(f'<input type="hidden" name="sheet_{i}" value="{_e(name)}">')
        head = (f'header row {det["header_row"]}' if det else "no header found")
        rows.append(
            f'<div class="card" style="margin-bottom:14px"><div class="card-h">'
            f'<h2>{_e(name)}</h2><span class="mut">{_e(head)} &middot; '
            f'{sheet.get("rows", 0)} rows</span></div><div class="card-b">'
            f'<label class="pref-h"><span>Import this sheet</span>'
            f'<input type="checkbox" name="ingest_{i}"{checked}></label>')
        if det:
            for field, flabel in FIELD_LABELS:
                rows.append(
                    f'<div class="pref-h"><span>{_e(flabel)}</span>'
                    f'{_select(f"map_{i}_{field}", labels, cols.get(field, ""))}</div>')
            rows.append(f'<div class="pref-h"><span>Cost currency</span>'
                        f'{_select_currency(f"cur_{i}", cur_ccy)}</div>')
        rows.append("</div></div>")
    return (
        f'<form method="post" action="/app/partners/profile/{_e(partner)}" class="filters">'
        f'<div class="fb" style="flex-direction:column;align-items:stretch;gap:14px">'
        + "".join(rows) +
        '<button class="btn">Save mapping &amp; re-import</button></div></form>'
        '<p class="pref-help">Re-import reparses the last file you uploaded for this partner '
        'with the corrected columns — no need to upload it again.</p>')


def confirm_form(staging_id, partner, detected):
    rows = [f'<input type="hidden" name="partner" value="{_e(partner)}">']
    for i, sheet in enumerate(detected.get("sheets", [])):
        name = sheet["name"]
        det = sheet.get("detected")
        labels = [x for x in (det["labels"] if det else []) if x]
        rows.append(f'<input type="hidden" name="sheet_{i}" value="{_e(name)}">')
        head = (f'header row {det["header_row"]}' if det else "no header found")
        checked = " checked" if sheet.get("ingest") else ""
        rows.append(
            f'<div class="card" style="margin-bottom:14px"><div class="card-h">'
            f'<h2>{_e(name)}</h2><span class="mut">{_e(head)} &middot; '
            f'{sheet.get("rows", 0)} rows</span></div><div class="card-b">'
            f'<label class="pref-h"><span>Import this sheet</span>'
            f'<input type="checkbox" name="ingest_{i}"{checked}></label>')
        if det:
            cols = det.get("columns", {})
            for field, flabel in FIELD_LABELS:
                rows.append(
                    f'<div class="pref-h"><span>{_e(flabel)}</span>'
                    f'{_select(f"map_{i}_{field}", labels, cols.get(field, ""))}</div>')
            cur = _select_currency(f"cur_{i}", det.get("cost_currency", "USD"))
            rows.append(f'<div class="pref-h"><span>Cost currency</span>{cur}</div>')
        rows.append("</div></div>")
    return (
        f'<form method="post" action="/app/partners/confirm/{staging_id}" class="filters">'
        f'<div class="fb" style="flex-direction:column;align-items:stretch;gap:14px">'
        + "".join(rows) +
        '<button class="btn">Confirm &amp; import products</button></div></form>')


def _select_currency(name, chosen="USD"):
    opts = [f'<option value="{c}"{" selected" if c == chosen else ""}>{c}</option>'
            for c in CURRENCIES]
    return f'<select name="{_e(name)}">' + "".join(opts) + "</select>"


def pool_filters(q, partner, partners, ptype="", types=()):
    popts = ['<option value="">All partners</option>']
    for name, n in partners:
        sel = " selected" if name == partner else ""
        popts.append(f'<option value="{_e(name)}"{sel}>{_e(name)} ({n})</option>')
    topts = ['<option value="">All types</option>']
    for t in types:
        sel = " selected" if t == ptype else ""
        topts.append(f'<option value="{_e(t)}"{sel}>{_e(t)}</option>')
    return (
        '<form method="get" action="/app/partners" class="filters">'
        '<div class="fb">'
        f'<input class="grow" type="text" name="q" value="{_e(q)}" '
        'placeholder="brand, article or description">'
        '<select name="partner">' + "".join(popts) + "</select>"
        '<select name="ptype">' + "".join(topts) + "</select>"
        '<button class="btn">Search</button>'
        '<a class="btn ghost" href="/app/partners">Clear</a>'
        '<a class="btn ghost" href="/app/partners/compare">Compare across partners</a>'
        + (f'<a class="btn ghost" href="/app/partners/profile/{_e(partner)}">'
           'Edit mapping</a>' if partner else "") +
        '<a class="btn" href="/app/partners/upload">Upload price-list</a>'
        '</div></form>')


def _usd(v):
    return f"${v:.2f}" if v is not None else "—"


def compare_view(offers):
    if not offers:
        return ('<p class="pref-help">No offers found for this product, or only one partner '
                'carries it. Load another partner\'s price-list to compare.</p>')
    head = offers[0]
    ident = (f'<div class="card" style="margin-bottom:16px"><div class="card-b">'
             f'<div><b>{_e(head["brand"] or "")}</b> · '
             f'<span class="num">{_e(head["mpn"] or "")}</span></div>'
             f'<div class="mut">{_e((head["description"] or "")[:200])}</div>'
             f'<div class="mut">{_e(head["product_type"] or "")}</div></div></div>')
    cheapest = offers[0]["price_usd"]
    second = offers[1]["price_usd"] if len(offers) > 1 else None
    rows = ['<div class="tbl-wrap"><table class="tbl"><thead><tr><th>#</th><th>Partner</th>'
            '<th>Dealer price</th><th>Promo</th><th>Warranty</th><th>Stock</th>'
            '<th>vs cheapest</th></tr></thead><tbody>']
    for i, o in enumerate(offers, start=1):
        promo = _usd(o["promo_usd"]) if o["promo_usd"] is not None else ""
        delta = ""
        if o["price_usd"] is not None and cheapest is not None and i > 1:
            delta = f'+{_usd(o["price_usd"] - cheapest)}'
        win = ' style="background:var(--ok-weak)"' if i == 1 else ""
        rows.append(
            f'<tr{win}><td class="num">{i}</td><td><b>{_e(o["partner"])}</b></td>'
            f'<td class="num">{_usd(o["price_usd"])}</td><td class="num mut">{promo}</td>'
            f'<td>{_e(o["warranty"] or "")}</td><td>{_e(o["stock"] or "")}</td>'
            f'<td class="num">{delta}</td></tr>')
    rows.append("</tbody></table></div>")
    save = ""
    if cheapest is not None and second is not None and second > cheapest:
        save = (f'<p class="pref-help">Cheapest is <b>{_e(offers[0]["partner"])}</b> at '
                f'{_usd(cheapest)} — {_usd(second - cheapest)} below the next partner.</p>')
    return ident + "".join(rows) + save


def multi_partner_list(rows, q="", ptype=""):
    header = (
        '<form method="get" action="/app/partners/compare" class="filters">'
        '<div class="fb">'
        f'<input class="grow" type="text" name="q" value="{_e(q)}" '
        'placeholder="brand, article or description">'
        f'<input type="hidden" name="ptype" value="{_e(ptype)}">'
        '<button class="btn">Find</button>'
        '<a class="btn ghost" href="/app/partners">Back to pool</a>'
        '</div></form>')
    if not rows:
        return header + ('<p class="pref-help">No products are carried by more than one '
                         'partner yet. Load another partner\'s price-list, then the same '
                         'article from two partners will show up here to compare.</p>')
    out = [header, '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Brand</th>'
           '<th>Article</th><th>Description</th><th>Type</th><th>Partners</th>'
           '<th>Best</th><th></th></tr></thead><tbody>']
    for r in rows:
        out.append(
            f'<tr><td>{_e(r["brand"] or "")}</td>'
            f'<td class="num">{_e(r["mpn_norm"])}</td>'
            f'<td style="max-width:360px">{_e((r["description"] or "")[:140])}</td>'
            f'<td>{_e(r["product_type"] or "")}</td>'
            f'<td class="num">{r["partners"]}</td>'
            f'<td class="num">{_usd(r["best_usd"])}</td>'
            f'<td><a class="btn ghost sm" href="/app/partners/compare?mpn={_e(r["mpn_norm"])}">'
            'Compare</a></td></tr>')
    out.append("</tbody></table></div>")
    return "".join(out)


def offers_table(rows):
    if not rows:
        return '<p class="pref-help">No products yet. Upload a partner price-list to start.</p>'
    out = ['<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Partner</th><th>Brand</th>'
           '<th>Article</th><th>Description</th><th>Type</th><th>Cost</th>'
           '<th>Promo</th></tr></thead><tbody>']
    for r in rows:
        promo = f'${r["promo_usd"]:.2f}' if r["promo_usd"] is not None else ""
        cost = f'${r["price_usd"]:.2f}' if r["price_usd"] is not None else (
            f'{r["price_original"]} {_e(r["currency"] or "")}'
            if r["price_original"] is not None else "")
        ptype = r["product_type"] or ""
        soft = ' style="opacity:.6"' if r["type_source"] == "path" else ""
        mpn = r["mpn"] or ""
        art = (f'<a href="/app/partners/compare?mpn={_e(r["mpn_norm"])}">{_e(mpn)}</a>'
               if r["mpn_norm"] else _e(mpn))
        out.append(
            f'<tr><td>{_e(r["partner"])}</td><td>{_e(r["brand"] or "")}</td>'
            f'<td class="num">{art}</td>'
            f'<td style="max-width:380px">{_e((r["description"] or "")[:150])}</td>'
            f'<td{soft}>{_e(ptype)}</td>'
            f'<td class="num">{cost}</td><td class="num">{promo}</td></tr>')
    out.append("</tbody></table></div>")
    return "".join(out)
