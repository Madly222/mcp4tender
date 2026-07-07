from __future__ import annotations

import datetime as dt
import re

from fastapi import APIRouter, Request

from web.render import _e, _layout, _loose, _vclass, source_url

router = APIRouter()

_STYLE = """
<style>
.res-intro{color:var(--mut);margin:2px 0 14px;max-width:82ch;line-height:1.5}
.sortbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 12px;font-size:12.5px}
.spill{padding:3px 12px;border-radius:999px;background:var(--chip);color:var(--fg);
  box-shadow:inset 0 0 0 1px var(--line);text-decoration:none}
.spill.on{background:var(--accent,#3b82f6);color:#fff;box-shadow:none}
.cpv-h{margin:20px 0 10px;font-size:14px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.cpv-h:first-of-type{margin-top:4px}
.res{margin-bottom:12px}
.res-top{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.rid{color:var(--mut);font-variant-numeric:tabular-nums;font-size:13px;margin-right:6px}
.rtitle{font-size:16px;font-weight:600}
.res-facts{color:var(--mut);font-size:12.5px;margin:8px 0 2px;display:flex;gap:16px;flex-wrap:wrap}
.res-facts b{color:var(--fg);font-weight:500}
.res-cpv{font-size:12px;color:var(--mut);margin:3px 0}
.res-margin{display:inline-block;margin-top:9px;font-size:13px;padding:3px 10px;border-radius:999px;
  background:var(--ok-weak);color:var(--ok);box-shadow:inset 0 0 0 1px rgba(63,185,80,.28)}
.res-reason{margin-top:9px;font-size:12.5px;color:var(--mut);border-left:2px solid var(--line);
  padding-left:11px;line-height:1.5}
.res-docs{margin-top:10px;font-size:12.5px}
.res-docs a{margin-right:14px}
.vtag{padding:3px 11px;border-radius:999px;font-size:12.5px;white-space:nowrap;
  background:var(--chip);box-shadow:inset 0 0 0 1px var(--line)}
.vtag.v-can{background:var(--ok-weak);color:var(--ok);box-shadow:inset 0 0 0 1px rgba(63,185,80,.3)}
.vtag.v-partial{color:var(--warn);box-shadow:inset 0 0 0 1px rgba(210,153,34,.35)}
</style>
"""

_LABEL = {"can": "Can execute", "partial": "Partial fit"}


def _docs_html(nj, surl=None):
    docs = nj.get("documents") or []
    if not isinstance(docs, list):
        docs = []
    links = []
    for d in docs[:12]:
        if not isinstance(d, dict):
            continue
        t = _e(d.get("title") or d.get("type") or "document")
        u = d.get("url")
        if u:
            links.append(f'<a href="{_e(u)}" target=_blank>{t}</a>')
        else:
            links.append(f'<span class="mut">{t}</span>')
    if links:
        return '<div class="res-docs">Documents: ' + " ".join(links) + "</div>"
    return '<div class="res-docs mut">No attached documents (spec is inline).</div>'


def _card(r, portal=None):
    nj = _loose(r["normalized_json"])
    nj = nj if isinstance(nj, dict) else {}
    tid = r["id"]
    title = _e(nj.get("title") or "(untitled)")

    verdict = r["av_verdict"]
    if verdict in _LABEL:
        badge = f'<span class="vtag v-{_e(verdict)}">{_LABEL[verdict]}</span>'
    else:
        badge = '<span class="vtag mut">Relevant · pending analysis</span>'

    cpv = nj.get("cpv") or []
    cpv_txt = ""
    if isinstance(cpv, list) and cpv and isinstance(cpv[0], dict):
        cpv_txt = " ".join(str(x) for x in (cpv[0].get("id"), cpv[0].get("description")) if x)

    pub = nj.get("publication_date")
    sub = nj.get("deadline")
    enq = nj.get("enquiry_deadline")
    ef = _loose(r["ex_fields"]) if r["ex_fields"] else {}
    est = ef.get("data_depunerii") if (isinstance(ef, dict) and not sub) else None
    if sub:
        dl = _e(sub)
    elif est:
        dl = f'{_e(est)} <span class="mut">(AI-estimated)</span>'
    else:
        dl = "—"
    facts = (f'<span><b>Buyer:</b> {_e(nj.get("buyer") or "—")}</span>'
             f'<span><b>Value:</b> {_e(nj.get("value_amount"))} {_e(nj.get("value_currency"))}</span>'
             f'<span><b>Published:</b> {_e(pub or "—")}</span>'
             f'<span><b>Deadline:</b> {dl}</span>'
             f'<span><b>Enquiry:</b> {_e(enq or "—")}</span>')

    margin = ""
    if r["margin"] is not None:
        m = f"{r['margin']*100:.1f}%"
        if r["margin_partial"]:
            m += " (partial)"
        margin = f'<div class="res-margin">Est. margin {m}</div>'

    reason = _loose(r["av_reason"])
    reason_html = ""
    if isinstance(reason, dict) and reason.get("reasoning"):
        reason_html = f'<div class="res-reason">{_e(str(reason["reasoning"])[:400])}</div>'

    surl = source_url(r["source"], r["external_id"], portal)
    src_line = (f'<div class="res-docs"><b>Source:</b> <a href="{_e(surl)}" target=_blank>'
                f'open on portal ↗</a></div>' if surl else "")
    return (
        '<div class="card res">'
        f'<div class="res-top"><div><span class="rid">#{tid}</span>'
        f'<span class="rtitle">{title}</span></div>{badge}</div>'
        f'<div class="res-facts">{facts}</div>'
        + (f'<div class="res-cpv">{_e(cpv_txt)}</div>' if cpv_txt else "")
        + margin + reason_html + _docs_html(nj, surl) + src_line
        + f'<div class="res-docs"><a href="/tender?id={tid}">open full detail →</a></div>'
        + '</div>')


_SORTS = [("deadline", "Deadline"), ("published", "Published"),
          ("enquiry", "Enquiry date"), ("cpv", "CPV code")]
_FIELD = {"deadline": "deadline", "published": "publication_date",
          "enquiry": "enquiry_deadline"}
_DESC = {"published": True}


def _parse_date(s):
    if not s:
        return None
    s = str(s)
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    return None


def _row_nj(r):
    nj = _loose(r["normalized_json"])
    return nj if isinstance(nj, dict) else {}


def _row_date(r, field):
    nj = _row_nj(r)
    if field == "deadline" and not nj.get("deadline") and r["ex_fields"]:
        ef = _loose(r["ex_fields"])
        if isinstance(ef, dict) and ef.get("data_depunerii"):
            return _parse_date(ef.get("data_depunerii"))
    return _parse_date(nj.get(field))


def _row_cpv(r):
    cpv = _row_nj(r).get("cpv") or []
    if isinstance(cpv, list) and cpv and isinstance(cpv[0], dict):
        return (cpv[0].get("id") or "—", cpv[0].get("description") or "")
    return ("—", "")


def _sorted_by_date(rows, sort):
    field = _FIELD[sort]
    desc = _DESC.get(sort, False)
    have = [r for r in rows if _row_date(r, field) is not None]
    none = [r for r in rows if _row_date(r, field) is None]
    have.sort(key=lambda r: _row_date(r, field), reverse=desc)
    return have + none


@router.get("/results")
def results(request: Request, q: str = "", sort: str = "deadline"):
    conn = request.state.conn
    if sort not in _FIELD and sort != "cpv":
        sort = "deadline"
    where = ""
    args = ()
    if q.strip().isdigit():
        where = "AND t.id = ?"
        args = (int(q.strip()),)
    rows = conn.execute(
        "SELECT t.id, t.source, t.external_id, t.normalized_json, av.verdict av_verdict, "
        "av.score av_score, av.reason av_reason, s.margin, s.margin_partial, e.fields_json ex_fields "
        "FROM tenders t "
        "LEFT JOIN verdicts av ON av.tender_id=t.id AND av.stage_name='applicability' "
        "LEFT JOIN verdicts tv ON tv.tender_id=t.id AND tv.stage_name='triage' "
        "LEFT JOIN suppliers s ON s.tender_id=t.id "
        "LEFT JOIN extractions e ON e.tender_id=t.id "
        "WHERE (av.verdict IN ('can','partial') "
        f"      OR (av.verdict IS NULL AND tv.verdict='relevant')) {where} "
        "ORDER BY (av.verdict IS NOT NULL) DESC, COALESCE(av.score,0) DESC, "
        "COALESCE(tv.score,0) DESC, t.id DESC LIMIT 300", args).fetchall()

    portal = (request.state.store.get("sources.mtender", {}) or {}).get("portal_url_template")
    qa = f"&q={_e(q)}" if q else ""
    pills = " ".join(
        f'<a class="spill{" on" if sort == k else ""}" href="/results?sort={k}{qa}">{lbl}</a>'
        for k, lbl in _SORTS)
    sortbar = f'<div class="sortbar"><span class="mut">Sort by:</span> {pills}</div>'

    search = ('<form method=get action="/results" class="row" style="margin:0 0 10px">'
              f'<input type=hidden name=sort value="{_e(sort)}">'
              f'<input type=text name=q value="{_e(q)}" placeholder="find by tender ID…" '
              'style="max-width:220px"><button class="ghost">Search</button>'
              + (' <a class="mut" href="/results">clear</a>' if q else "") + '</form>')

    if not rows:
        cards = ('<div class="card mut">Nothing here yet. Tenders appear once triage marks them '
                 'relevant (and, ideally, applicability judges them can/partial). Run the stages '
                 'from the Analyze tab.</div>')
    elif sort == "cpv":
        groups = {}
        for r in rows:
            groups.setdefault(_row_cpv(r), []).append(r)
        blocks = []
        for (code, desc), grp in sorted(groups.items(), key=lambda kv: str(kv[0][0])):
            hdr = (f'<h3 class="cpv-h">{_e(code)}'
                   f'{(" · " + _e(desc)) if desc else ""} '
                   f'<span class="mut">({len(grp)})</span></h3>')
            blocks.append(hdr + "".join(_card(r, portal) for r in grp))
        cards = "".join(blocks)
    else:
        cards = "".join(_card(r, portal) for r in _sorted_by_date(rows, sort))

    body = (_STYLE
            + '<p class="res-intro">The shortlist — tenders worth acting on, with everything triage '
              'or applicability ruled out already removed. Sort by any date (default) or group them '
              'by CPV code.</p>'
            + sortbar + search
            + f'<p class="mut" style="font-size:12.5px">{len(rows)} tender(s)</p>' + cards)
    return _layout(request, "Results", body)
