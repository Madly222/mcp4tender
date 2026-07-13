from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from engine.dateparse import humanize, parse_date
from web.render import _e, _layout, _loose, source_url
from workflows.segments import partition, read_thresholds

router = APIRouter()

DASH = "—"

_STYLE = """
<style>
.res-intro{color:var(--mut);margin:2px 0 14px;max-width:82ch;line-height:1.5}
.tabbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 10px}
.tab{padding:5px 14px;border-radius:999px;background:var(--chip);color:var(--fg);
  box-shadow:inset 0 0 0 1px var(--line);text-decoration:none;font-size:13px}
.tab.on{background:var(--acc,#3b82f6);color:#fff;box-shadow:none}
.tab .cnt{opacity:.7;margin-left:6px;font-variant-numeric:tabular-nums}
.newdays{display:flex;align-items:center;gap:8px;margin:0 0 12px;font-size:12.5px;color:var(--mut)}
.newdays input{max-width:70px}
.sortbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 12px;font-size:12.5px}
.spill{padding:3px 12px;border-radius:999px;background:var(--chip);color:var(--fg);
  box-shadow:inset 0 0 0 1px var(--line);text-decoration:none}
.spill.on{background:var(--acc,#3b82f6);color:#fff;box-shadow:none}
.cpv-h{margin:20px 0 10px;font-size:14px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.cpv-h:first-of-type{margin-top:4px}
.res{margin-bottom:12px}
.res-top{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.rid{color:var(--mut);font-variant-numeric:tabular-nums;font-size:13px;margin-right:6px}
.rtitle{font-size:16px;font-weight:600}
.res-facts{color:var(--mut);font-size:12.5px;margin:8px 0 2px;display:flex;gap:16px;flex-wrap:wrap}
.res-facts b{color:var(--fg);font-weight:500}
.res-facts .dt{font-variant-numeric:tabular-nums;white-space:nowrap}
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

_TABS = [("new", "New"), ("general", "General relevant"),
         ("archive", "Archive"), ("all", "Base of all found")]
_SEG_FOR_TAB = {"new": "new", "general": "history", "archive": "archive"}

_INTRO = {
    "new": "Freshly found tenders from the daily checks, still within their new window. "
           "Only daily (incremental) finds appear here; historical ones go straight to General.",
    "general": "The working shortlist: relevant tenders that outlived the new window plus "
               "everything pulled from a site's history - all still live (not archived).",
    "archive": "Relevant tenders that aged past the archive limit or whose deadline has passed. "
               "Kept for reference, never deleted.",
    "all": "Every tender ever collected - relevant or not, live or archived. The raw base.",
}


def pub_value(nj):
    return nj.get("publication_date") or nj.get("published")


def show_date(raw, with_time=True):
    if not raw:
        return DASH
    pretty = humanize(raw, with_time=with_time)
    if pretty:
        return _e(pretty)
    return _e(str(raw))


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


def _badge(r, plain):
    av = r["av_verdict"]
    if av in _LABEL:
        return f'<span class="vtag v-{_e(av)}">{_LABEL[av]}</span>'
    if plain:
        tv = r["tv_verdict"]
        if av == "cannot":
            label = "Not a fit"
        elif av == "unknown":
            label = "Analyzed"
        elif tv == "relevant":
            label = "Relevant - pending"
        elif tv == "gray":
            label = "Gray zone"
        elif tv == "out":
            label = "Filtered out"
        else:
            label = "Collected"
        return f'<span class="vtag mut">{_e(label)}</span>'
    return '<span class="vtag mut">Relevant - pending analysis</span>'


def _card(r, portal=None, plain=False):
    nj = _loose(r["normalized_json"])
    nj = nj if isinstance(nj, dict) else {}
    tid = r["id"]
    title = _e(nj.get("title") or "(untitled)")
    badge = _badge(r, plain)

    cpv = nj.get("cpv") or []
    cpv_txt = ""
    if isinstance(cpv, list) and cpv and isinstance(cpv[0], dict):
        cpv_txt = " ".join(str(x) for x in (cpv[0].get("id"), cpv[0].get("description")) if x)

    sub = nj.get("deadline")
    ef = _loose(r["ex_fields"]) if r["ex_fields"] else {}
    est = ef.get("data_depunerii") if (isinstance(ef, dict) and not sub) else None
    if sub:
        dl = show_date(sub)
    elif est:
        dl = show_date(est) + ' <span class="mut">(AI-estimated)</span>'
    else:
        dl = DASH

    buyer = _e(nj.get("buyer") or DASH)
    amount = _e(nj.get("value_amount"))
    currency = _e(nj.get("value_currency"))
    pub_txt = show_date(pub_value(nj), with_time=False)
    enq_txt = show_date(nj.get("enquiry_deadline"))
    facts = (f'<span><b>Buyer:</b> {buyer}</span>'
             f'<span><b>Value:</b> {amount} {currency}</span>'
             f'<span class="dt"><b>Published:</b> {pub_txt}</span>'
             f'<span class="dt"><b>Deadline:</b> {dl}</span>'
             f'<span class="dt"><b>Enquiry:</b> {enq_txt}</span>')

    margin = ""
    if r["margin"] is not None:
        pct = r["margin"] * 100
        m = f"{pct:.1f}%"
        if r["margin_partial"]:
            m += " (partial)"
        margin = f'<div class="res-margin">Est. margin {m}</div>'

    reason = _loose(r["av_reason"])
    reason_html = ""
    if isinstance(reason, dict) and reason.get("reasoning"):
        txt = _e(str(reason["reasoning"])[:400])
        reason_html = f'<div class="res-reason">{txt}</div>'

    surl = source_url(r["source"], r["external_id"], portal)
    src_line = ""
    if surl:
        src_line = (f'<div class="res-docs"><b>Source:</b> <a href="{_e(surl)}" target=_blank>'
                    'open on portal</a></div>')
    cpv_html = f'<div class="res-cpv">{_e(cpv_txt)}</div>' if cpv_txt else ""
    return (
        '<div class="card res">'
        f'<div class="res-top"><div><span class="rid">#{tid}</span>'
        f'<span class="rtitle">{title}</span></div>{badge}</div>'
        f'<div class="res-facts">{facts}</div>'
        + cpv_html + margin + reason_html + _docs_html(nj, surl) + src_line
        + f'<div class="res-docs"><a href="/tender?id={tid}">open full detail</a></div>'
        + '</div>')


_SORTS = [("deadline", "Deadline"), ("published", "Published"),
          ("enquiry", "Enquiry date"), ("cpv", "CPV code")]
_FIELD = {"deadline": "deadline", "published": "publication_date",
          "enquiry": "enquiry_deadline"}
_DESC = {"published": True}


def _row_nj(r):
    nj = _loose(r["normalized_json"])
    return nj if isinstance(nj, dict) else {}


def _row_date(r, field):
    nj = _row_nj(r)
    if field == "publication_date":
        return parse_date(pub_value(nj))
    if field == "deadline" and not nj.get("deadline") and r["ex_fields"]:
        ef = _loose(r["ex_fields"])
        if isinstance(ef, dict) and ef.get("data_depunerii"):
            return parse_date(ef.get("data_depunerii"))
    return parse_date(nj.get(field))


def _row_cpv(r):
    cpv = _row_nj(r).get("cpv") or []
    if isinstance(cpv, list) and cpv and isinstance(cpv[0], dict):
        return (cpv[0].get("id") or DASH, cpv[0].get("description") or "")
    return (DASH, "")


def _sorted_by_date(rows, sort):
    field = _FIELD[sort]
    desc = _DESC.get(sort, False)
    have = [r for r in rows if _row_date(r, field) is not None]
    none = [r for r in rows if _row_date(r, field) is None]
    have.sort(key=lambda r: _row_date(r, field), reverse=desc)
    return have + none


_SELECT = (
    "SELECT t.id, t.source, t.external_id, t.normalized_json, t.origin, t.created_at, "
    "av.verdict av_verdict, av.score av_score, av.reason av_reason, tv.verdict tv_verdict, "
    "s.margin, s.margin_partial, e.fields_json ex_fields "
    "FROM tenders t "
    "LEFT JOIN verdicts av ON av.tender_id=t.id AND av.stage_name='applicability' "
    "LEFT JOIN verdicts tv ON tv.tender_id=t.id AND tv.stage_name='triage' "
    "LEFT JOIN suppliers s ON s.tender_id=t.id "
    "LEFT JOIN extractions e ON e.tender_id=t.id ")

_RELEVANT_WHERE = ("(av.verdict IN ('can','partial') "
                   "OR (av.verdict IS NULL AND tv.verdict='relevant')) ")


@router.post("/results/settings")
def results_settings(request: Request, new_days: str = Form("7")):
    if request.state.readonly:
        return RedirectResponse("/results?tab=new", status_code=303)
    try:
        n = max(0, int(new_days))
    except ValueError:
        n = 7
    request.state.store.set("results.new_days", n, actor="web", note="results.new_days")
    return RedirectResponse("/results?tab=new", status_code=303)


@router.get("/results")
def results(request: Request, tab: str = "new", q: str = "", sort: str = "deadline"):
    conn = request.state.conn
    store = request.state.store
    if tab not in _SEG_FOR_TAB and tab != "all":
        tab = "new"
    if sort not in _FIELD and sort != "cpv":
        sort = "deadline"
    idq = q.strip() if q.strip().isdigit() else ""

    rel_rows = conn.execute(
        _SELECT + "WHERE " + _RELEVANT_WHERE
        + "ORDER BY (av.verdict IS NOT NULL) DESC, COALESCE(av.score,0) DESC, "
        "COALESCE(tv.score,0) DESC, t.id DESC LIMIT 3000").fetchall()
    buckets = partition(rel_rows, store)
    counts = {"new": len(buckets["new"]), "general": len(buckets["history"]),
              "archive": len(buckets["archive"])}
    counts["all"] = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]

    if tab == "all":
        where = "WHERE t.id = ?" if idq else ""
        rows = conn.execute(
            _SELECT + where + " ORDER BY t.id DESC LIMIT 300",
            (int(idq),) if idq else ()).fetchall()
    else:
        rows = buckets[_SEG_FOR_TAB[tab]]
        if idq:
            rows = [r for r in rows if str(r["id"]) == idq]

    portal = (store.get("sources.mtender", {}) or {}).get("portal_url_template")
    plain = tab == "all"

    tab_links = []
    for k, lbl in _TABS:
        on = " on" if tab == k else ""
        cnt = counts[k]
        tab_links.append(f'<a class="tab{on}" href="/results?tab={k}">{_e(lbl)}'
                         f'<span class="cnt">{cnt}</span></a>')
    tabbar = '<div class="tabbar">' + "".join(tab_links) + "</div>"

    new_days = read_thresholds(store)[0]
    if request.state.readonly:
        newday_ctl = ('<div class="newdays">A tender counts as New for '
                      f'<b>{new_days}</b> days after it is found.</div>')
    else:
        newday_ctl = (
            '<form method=post action="/results/settings" class="newdays">'
            'A tender counts as New for '
            f'<input type=number name=new_days min=0 value="{new_days}"> days after it is found.'
            ' <button class="ghost">Save</button></form>')

    qa = f"&q={_e(q)}" if idq else ""
    sort_links = []
    for k, lbl in _SORTS:
        on = " on" if sort == k else ""
        sort_links.append(f'<a class="spill{on}" href="/results?tab={tab}&sort={k}{qa}">{lbl}</a>')
    pills = " ".join(sort_links)
    sortbar = f'<div class="sortbar"><span class="mut">Sort by:</span> {pills}</div>'

    clear_link = f' <a class="mut" href="/results?tab={tab}">clear</a>' if idq else ""
    search = ('<form method=get action="/results" class="row" style="margin:0 0 10px">'
              f'<input type=hidden name=tab value="{_e(tab)}">'
              f'<input type=hidden name=sort value="{_e(sort)}">'
              f'<input type=text name=q value="{_e(q)}" placeholder="find by tender ID" '
              'style="max-width:220px"><button class="ghost">Search</button>'
              + clear_link + '</form>')

    if not rows:
        cards = '<div class="card mut">Nothing in this tab yet.</div>'
    elif sort == "cpv":
        groups = {}
        for r in rows:
            groups.setdefault(_row_cpv(r), []).append(r)
        blocks = []
        for (code, desc), grp in sorted(groups.items(), key=lambda kv: str(kv[0][0])):
            suffix = (" - " + _e(desc)) if desc else ""
            n = len(grp)
            hdr = (f'<h3 class="cpv-h">{_e(code)}{suffix} '
                   f'<span class="mut">({n})</span></h3>')
            blocks.append(hdr + "".join(_card(r, portal, plain) for r in grp))
        cards = "".join(blocks)
    else:
        cards = "".join(_card(r, portal, plain) for r in _sorted_by_date(rows, sort))

    intro = _e(_INTRO[tab])
    shown = len(rows)
    body = (_STYLE
            + f'<p class="res-intro">{intro}</p>'
            + tabbar + newday_ctl + sortbar + search
            + f'<p class="mut" style="font-size:12.5px">{shown} shown</p>' + cards)
    return _layout(request, "Results", body)
