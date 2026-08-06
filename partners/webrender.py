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
            cur = _select_currency(f"cur_{i}")
            rows.append(f'<div class="pref-h"><span>Cost currency</span>{cur}</div>')
        rows.append("</div></div>")
    return (
        f'<form method="post" action="/app/partners/confirm/{staging_id}" class="filters">'
        f'<div class="fb" style="flex-direction:column;align-items:stretch;gap:14px">'
        + "".join(rows) +
        '<button class="btn">Confirm &amp; import products</button></div></form>')


def _select_currency(name):
    opts = [f'<option value="{c}"{" selected" if c == "USD" else ""}>{c}</option>'
            for c in CURRENCIES]
    return f'<select name="{_e(name)}">' + "".join(opts) + "</select>"


def pool_filters(q, partner, partners):
    opts = ['<option value="">All partners</option>']
    for name, n in partners:
        sel = " selected" if name == partner else ""
        opts.append(f'<option value="{_e(name)}"{sel}>{_e(name)} ({n})</option>')
    return (
        '<form method="get" action="/app/partners" class="filters">'
        '<div class="fb">'
        f'<input class="grow" type="text" name="q" value="{_e(q)}" '
        'placeholder="brand, article or description">'
        f'<select name="partner">' + "".join(opts) + "</select>"
        '<button class="btn">Search</button>'
        '<a class="btn ghost" href="/app/partners">Clear</a>'
        '<a class="btn" href="/app/partners/upload">Upload price-list</a>'
        '</div></form>')


def offers_table(rows):
    if not rows:
        return '<p class="pref-help">No products yet. Upload a partner price-list to start.</p>'
    out = ['<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Partner</th><th>Brand</th>'
           '<th>Article</th><th>Description</th><th>Category</th><th>Cost</th>'
           '<th>Promo</th></tr></thead><tbody>']
    for r in rows:
        promo = f'${r["promo_usd"]:.2f}' if r["promo_usd"] is not None else ""
        cost = f'${r["price_usd"]:.2f}' if r["price_usd"] is not None else (
            f'{r["price_original"]} {_e(r["currency"] or "")}'
            if r["price_original"] is not None else "")
        out.append(
            f'<tr><td>{_e(r["partner"])}</td><td>{_e(r["brand"] or "")}</td>'
            f'<td class="num">{_e(r["mpn"] or "")}</td>'
            f'<td style="max-width:420px">{_e((r["description"] or "")[:160])}</td>'
            f'<td class="mut">{_e(r["category_path"] or "")}</td>'
            f'<td class="num">{cost}</td><td class="num">{promo}</td></tr>')
    out.append("</tbody></table></div>")
    return "".join(out)
