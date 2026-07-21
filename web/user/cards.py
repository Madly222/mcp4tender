from __future__ import annotations

import datetime as dt

from engine.dateparse import day_end_ts, humanize, parse_date
from web.render import _e, _loose, source_url
from web.user.icons import icon
from workflows import work

DASH = "—"

VERDICT_LABEL = {"can": "Full fit", "partial": "Partial fit", "cannot": "Not our work"}
VERDICT_CHIP = {"can": "ok", "partial": "warn", "cannot": "bad"}
VERDICT_CLASS = {"can": "m-can", "partial": "m-part", "cannot": "m-cannot"}


def portal_of(store):
    return (store.get("sources.mtender", {}) or {}).get("portal_url_template")


def source_label(row, nj):
    src = row["source"] or ""
    if src == "genericweb":
        return (nj or {}).get("source_site") or "web"
    return src


def tender_link(row, nj, portal=None):
    url = source_url(row["source"], row["external_id"], portal)
    if url:
        return url
    u = (nj or {}).get("url")
    if isinstance(u, str) and u.startswith(("http://", "https://")):
        return u
    return None


def nj_of(row):
    nj = _loose(row["normalized_json"])
    return nj if isinstance(nj, dict) else {}


def deadline_of(row, nj):
    raw = nj.get("deadline")
    if raw:
        return raw, False
    ef = _loose(row["ex_fields"]) if row["ex_fields"] else {}
    if isinstance(ef, dict) and ef.get("data_depunerii"):
        return ef["data_depunerii"], True
    return None, False


def _stamp(when):
    if isinstance(when, dt.datetime):
        return when.timestamp()
    if isinstance(when, dt.date):
        return dt.datetime.combine(when, dt.time()).timestamp()
    return None


def _left(raw, now):
    ts = day_end_ts(raw)
    if ts is None:
        return ""
    days = int((ts - now) // 86400)
    if days < 0:
        return '<div class="t-left bad">closed</div>'
    if days == 0:
        return '<div class="t-left bad">today</div>'
    if days == 1:
        return '<div class="t-left bad">tomorrow</div>'
    cls = "warn" if days <= 10 else ""
    return f'<div class="t-left {cls}">{days} days left</div>'


def cell_when(row, nj, now):
    raw, estimated = deadline_of(row, nj)
    if not raw:
        return f'<td class="t-when"><b>{DASH}</b></td>'
    pretty = humanize(raw) or str(raw)
    est = '<div style="margin-top:5px"><span class="chip plain">estimated</span></div>' \
        if estimated else ""
    return f'<td class="t-when"><b class="num">{_e(pretty)}</b>{_left(raw, now)}{est}</td>'


def cell_ref(row, nj=None):
    nj = nj if nj is not None else nj_of(row)
    ext = _e(row["external_id"] or DASH)
    src = _e(source_label(row, nj))
    return f'<td><span class="t-ref">{ext}</span><span class="chip plain">{src}</span></td>'


def cell_tender(row, nj, portal=None, extra=""):
    url = tender_link(row, nj, portal)
    title = _e(nj.get("title") or "(untitled)")
    href = f' href="/app/tender/{row["id"]}"'
    tags = []
    if extra:
        tags.append(extra)
    if url:
        tags.append(f'<a class="chip plain" href="{_e(url)}" target=_blank>portal</a>')
    cpv = nj.get("cpv") or []
    if isinstance(cpv, list) and cpv and isinstance(cpv[0], dict):
        txt = " ".join(str(x) for x in (cpv[0].get("id"), cpv[0].get("description")) if x)
        if txt:
            tags.append(f'<span class="chip">{_e(txt[:48])}</span>')
    if row["margin"] is not None:
        pct = row["margin"] * 100
        cls = "ok" if pct >= 12 else "warn"
        extra = " · partial" if row["margin_partial"] else ""
        tags.append(f'<span class="chip {cls}">Margin {pct:.0f}%{_e(extra)}</span>')
    return (f'<td><a class="t-title"{href}>{title}</a>'
            f'<div class="t-buyer">{_e(nj.get("buyer") or DASH)}</div>'
            f'<div class="t-tags">{"".join(tags)}</div></td>')


def cell_value(nj):
    amount = nj.get("value_amount")
    if amount in (None, "", 0):
        return f'<td><div class="t-val num">{DASH}<small>not stated</small></div></td>'
    try:
        pretty = f"{float(amount):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        pretty = str(amount)
    cur = _e(nj.get("value_currency") or "")
    return f'<td><div class="t-val num">{_e(pretty)}<small>{cur}</small></div></td>'


def cell_docs(nj):
    docs = nj.get("documents") or []
    if not isinstance(docs, list):
        docs = []
    docs = [d for d in docs if isinstance(d, dict)]
    if not docs:
        return '<td><div class="t-doc-n">No documents — spec is inline</div></td>'
    links = []
    for d in docs[:2]:
        t = _e((d.get("title") or d.get("type") or "document")[:26])
        u = d.get("url")
        inner = f'<a href="{_e(u)}" target=_blank>{t}</a>' if u else f"<span>{t}</span>"
        links.append(f'<div class="t-doc">{icon("download")}{inner}</div>')
    more = f' <span class="t-doc-n">+{len(docs) - 2}</span>' if len(docs) > 2 else ""
    plural = "s" if len(docs) != 1 else ""
    return (f'<td><div class="t-doc-n">{len(docs)} document{plural}</div>'
            f'{"".join(links)}{more}</td>')


def cell_match(row):
    v = row["av_verdict"]
    if not v:
        return ('<td><div class="match m-none"><span class="sc">Not scored</span></div>'
                '<div style="margin-top:7px"><span class="chip">Queued</span></div></td>')
    score = row["av_score"] or 0
    out_of_ten = round(score / 10)
    cls = VERDICT_CLASS.get(v, "m-none")
    chip = VERDICT_CHIP.get(v, "")
    label = VERDICT_LABEL.get(v, v)
    return (f'<td><div class="match {cls}"><div class="bar"><i style="width:{score}%"></i></div>'
            f'<span class="sc num">{out_of_ten}/10</span></div>'
            f'<div style="margin-top:7px"><span class="chip {chip}">{_e(label)}</span></div></td>')


def cell_stage(info):
    stage = info["stage"] if info else "inbox"
    return f'<td><span class="chip {work.CHIP.get(stage, "")}">{_e(work.LABELS[stage])}</span></td>'


def cell_decide(row, back):
    tid = row["id"]
    return ('<td><div class="acts">'
            f'<form method="post" action="/app/inbox/{tid}/stage" style="display:contents">'
            f'<input type="hidden" name="back" value="{_e(back)}">'
            f'<button class="icon-btn good" name="stage" value="qualified" '
            f'title="Keep — move to Qualified">{icon("check", 2.5)}</button>'
            f'<button class="icon-btn no" name="stage" value="skipped" '
            f'title="Skip">{icon("x", 2.5)}</button></form>'
            "</div></td>")


def since_of(info, now):
    if not info or not info.get("updated_at"):
        return ""
    days = int((now - info["updated_at"]) // 86400)
    if days <= 0:
        return '<div class="t-doc-n" style="margin-top:6px">today</div>'
    unit = "day" if days == 1 else "days"
    return f'<div class="t-doc-n" style="margin-top:6px">{days} {unit} ago</div>'


def cell_stage_since(info, now):
    stage = info["stage"] if info else "inbox"
    return (f'<td><span class="chip {work.CHIP.get(stage, "")}">{_e(work.LABELS[stage])}</span>'
            f"{since_of(info, now)}</td>")


def cell_note(info):
    note = (info or {}).get("note") or ""
    return ('<td><input type="text" name="note" class="note-in" '
            f'value="{_e(note)}" placeholder="Add a note"></td>')


def cell_move(row, info, back):
    stage = (info or {}).get("stage") or "inbox"
    opts = "".join(
        f'<option value="{s}"{" selected" if s == stage else ""}>{_e(work.LABELS[s])}</option>'
        for s in work.STAGES)
    return ('<td><div class="acts">'
            f'<select name="stage">{opts}</select>'
            f'<button class="btn sm" name="save" value="1">Save</button>'
            f'<input type="hidden" name="back" value="{_e(back)}">'
            "</div></td>")
