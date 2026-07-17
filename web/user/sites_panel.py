from __future__ import annotations

from web.render import _e
from web.sites_common import _bar, _crawl_rows
from web.user.icons import icon

from workflows.collectors.genericweb import api_covered

A = "/app/settings/sites"


def _mini(action, fields, label, title="", cls="btn ghost sm", confirm=""):
    hidden = "".join(f'<input type="hidden" name="{k}" value="{_e(v)}">'
                     for k, v in fields.items())
    onsub = f' onsubmit="return confirm(\'{_e(confirm)}\')"' if confirm else ""
    return (f'<form method="post" action="{A}/{action}" style="display:inline;margin:0"{onsub}>'
            f'{hidden}<button class="{cls}" title="{_e(title)}">{label}</button></form>')


def _site_card(s, cs, ro):
    sid = s.get("id", "")
    covered = api_covered(s.get("url"))
    url = s.get("url") or ""
    step = int(s.get("batch_size", 30) or 30)
    collected = (cs["total_collected"] if cs else 0) or 0
    est = cs["total_estimate"] if cs else None
    detected = (cs["detected_count"] if (cs and "detected_count" in cs.keys()) else None)
    on = bool(s.get("enabled", True))

    meta = []
    if covered:
        meta.append('<div class="strip bad" style="width:100%">'
                    f'<div class="ic">{icon("bang", 3)}</div><div class="tx">'
                    "<b>Already collected through its API</b>"
                    "<span>Scanning this site by reading its pages spends tokens on your key "
                    "for data we already get free and complete from the API above — and the "
                    "scraped copy has no status, so it would slip past the inbox filter. "
                    "Remove it.</span></div></div>")
    meta.append(_bar(collected, est, detected))
    if s.get("feed_url"):
        meta.append(f'<a class="chip acc" href="{_e(s["feed_url"])}" target=_blank '
                    f'title="{_e(s.get("feed_note") or "")}">'
                    f'{_e(s.get("feed_kind") or "feed")} available</a>')
    elif "feed_kind" in s:
        meta.append('<span class="chip plain" title="probed and found nothing — '
                    'this site is read page by page">no feed</span>')
    if cs and cs["exhausted"]:
        meta.append('<span class="chip ok">all collected</span>')
    if cs and "note" in cs.keys() and cs["note"]:
        meta.append(f'<div class="pref-help" style="margin:0">{_e(cs["note"])}</div>')
    if s.get("engine"):
        meta.append(f'<span class="chip plain">engine: {_e(s["engine"])}</span>')
    has_auth = bool(cs and cs["auth_json"])

    head = (f'<div class="site-h"><div class="site-t">'
            f'<b>{_e(s.get("label") or url)}</b>'
            f'<a href="{_e(url)}" target=_blank class="t-doc-n">{_e(url)}</a></div>'
            f'<span class="chip {"ok" if on else "plain"}">{"on" if on else "off"}</span>'
            f'<span class="chip {"acc" if has_auth else "plain"}">'
            f'{"login set" if has_auth else "no login"}</span></div>')

    if ro:
        return f'<div class="catrow">{head}<div class="site-m">{"".join(meta)}</div></div>'

    controls = (
        f'<form method="post" action="{A}/settings" class="site-row">'
        f'<input type="hidden" name="id" value="{_e(sid)}">'
        f'<label class="catl" style="margin:0">Per batch</label>'
        f'<input class="note-in" type="number" min="1" max="1000" name="batch_size" '
        f'value="{step}" style="max-width:90px">'
        '<button class="btn ghost sm">Set</button></form>'
        f'<form method="post" action="{A}/auth" class="site-row">'
        f'<input type="hidden" name="id" value="{_e(sid)}">'
        '<input class="note-in" type="text" name="login" placeholder="login" '
        'style="max-width:150px">'
        '<input class="note-in" type="password" name="password" placeholder="password" '
        'style="max-width:150px">'
        '<button class="btn ghost sm">Save login</button></form>')

    acts = " ".join([
        _mini("collect-batch", {"site_id": sid}, f"Collect next {step}",
              "fetch the next batch from this site now", cls="btn sm"),
        _mini("estimate", {"id": sid}, "Estimate", "re-count how many tenders this site has"),
        _mini("probe", {"id": sid}, "Find feed",
              "look for an RSS feed, a WordPress API or a sitemap on this site"),
        _mini("preview", {"id": sid}, "Test", "fetch this page now and show what is found"),
        _mini("analyze", {"id": sid}, "Analyse", "profile this site: are there tenders, how to reach them"),
        _mini("render-toggle", {"id": sid}, f'JS: {"on" if s.get("render") else "off"}',
              "render with a headless browser (for JavaScript sites)"),
        _mini("reset-cursor", {"id": sid}, "Reset", "start crawling this site from the beginning",
              confirm="Reset crawl position to the start?"),
        _mini("toggle", {"id": sid}, "Off" if on else "On", "stop or resume scanning this site"),
        _mini("remove", {"kind": "tenders", "id": sid}, "Remove", "forget this site",
              cls="btn ghost sm danger", confirm="Remove this site?"),
    ])
    return (f'<div class="catrow">{head}'
            f'<div class="site-m">{"".join(meta)}</div>'
            f'<div class="site-c">{controls}</div>'
            f'<div class="acts" style="flex-wrap:wrap">{acts}</div></div>')


def _mtender_card(store, conn, ro):
    cfg = store.get("sources.mtender", {}) or {}
    on = bool(cfg.get("enabled", False))
    n = conn.execute("SELECT COUNT(*) c FROM tenders WHERE source='mtender'").fetchone()["c"]
    acts = ""
    if not ro:
        acts = ('<div class="acts" style="flex-wrap:wrap">'
                + _mini("mtender-toggle", {}, "Off" if on else "On",
                        "stop or resume scanning MTender")
                + " " + _mini("collect-mtender", {}, "Collect now",
                              "fetch new MTender tenders right now", cls="btn sm")
                + " " + _mini("dedupe-mtender", {}, "Dedupe",
                              "merge duplicate MTender records")
                + "</div>")
    return ('<div class="card"><div class="card-h">'
            f'{icon("search")}<h2>MTender</h2><div class="spacer"></div>'
            f'<span class="chip {"ok" if on else "plain"}">{"on" if on else "off"}</span>'
            f'<span class="chip num">{n}</span></div>'
            '<div class="card-b">'
            '<p class="mut" style="margin:0 0 12px;line-height:1.6">The national procurement '
            'portal. Reading it is free — no tokens are spent collecting from here, so there is '
            'rarely a reason to turn it off.</p>'
            f'{acts}</div></div>')


def sites_panel(store, request):
    conn = request.state.conn
    ro = bool(store.get("web.read_only"))
    all_t = store.get("sites.tenders", []) or []
    tenders = list(all_t)
    partners = store.get("sites.partners", []) or []
    gw = store.get("sources.genericweb", {}) or {}
    gw_on = bool(gw.get("enabled", False))
    crawl = _crawl_rows(conn, [s.get("id") for s in tenders])

    cards = "".join(_site_card(s, crawl.get(s.get("id", "")), ro) for s in tenders)
    if not cards:
        cards = ('<div class="empty">No tender sites yet. MTender above works on its own; '
                 "add a site here only if it publishes tenders MTender does not.</div>")

    add = ""
    if not ro:
        add = (f'<form method="post" action="{A}/add" class="catrow">'
               '<input type="hidden" name="kind" value="tenders">'
               '<div class="cat2">'
               '<div><label class="catl">Name</label>'
               '<input class="note-in" type="text" name="label" placeholder="Primaria Chisinau">'
               "</div>"
               '<div><label class="catl">Tender list URL</label>'
               '<input class="note-in" type="text" name="url" '
               'placeholder="https://site.md/achizitii"></div></div>'
               '<div class="cat2">'
               '<div><label class="catl">Login (optional)</label>'
               '<input class="note-in" type="text" name="login"></div>'
               '<div><label class="catl">Password (optional)</label>'
               '<input class="note-in" type="password" name="password"></div></div>'
               '<div class="site-row"><label class="catl" style="margin:0">Per batch</label>'
               '<input class="note-in" type="number" min="1" max="1000" name="batch_size" '
               'value="30" style="max-width:90px">'
               '<button class="btn">Add site</button></div></form>')

    gw_acts = ""
    if not ro:
        gw_acts = ('<div class="acts" style="flex-wrap:wrap;margin-bottom:12px">'
                   + _mini("engine-toggle", {}, f'Engine: {_e(gw.get("engine", "builtin"))}',
                           "switch the page fetcher")
                   + " " + _mini("search-toggle", {}, "Search discovery",
                                 "let the engine look for tender pages by itself")
                   + " " + _mini("dedupe-docs", {}, "Dedupe documents",
                                 "merge duplicate documents across tenders")
                   + "</div>")

    web = ('<div class="card"><div class="card-h">'
           f'{icon("search")}<h2>Other tender sites</h2><div class="spacer"></div>'
           f'<span class="chip {"ok" if gw_on else "plain"}">{"on" if gw_on else "off"}</span>'
           f'<span class="chip num">{len(tenders)}</span></div>'
           '<div class="card-b">'
           '<p class="mut" style="margin:0 0 12px;line-height:1.6">Sites scanned by reading their '
           'pages. Unlike MTender this <b>spends tokens on your key</b>, because every page goes '
           'through a model. Collect in batches and watch the numbers.</p>'
           f'{gw_acts}{cards}{add}</div></div>')

    prows = ""
    for s in partners:
        rm = "" if ro else _mini("remove", {"kind": "partners", "id": s.get("id", "")},
                                 "Remove", "", cls="btn ghost sm danger")
        prows += (f'<div class="site-h" style="padding:9px 0;border-bottom:1px solid var(--line)">'
                  f'<div class="site-t"><b>{_e(s.get("label") or "")}</b>'
                  f'<a href="{_e(s.get("url") or "")}" target=_blank class="t-doc-n">'
                  f'{_e(s.get("url") or "")}</a></div>'
                  f'<span class="chip plain">{_e(s.get("category") or "—")}</span>{rm}</div>')
    padd = ""
    if not ro:
        padd = (f'<form method="post" action="{A}/add" class="site-row" style="margin-top:12px">'
                '<input type="hidden" name="kind" value="partners">'
                '<input class="note-in" type="text" name="label" placeholder="name" '
                'style="max-width:170px">'
                '<input class="note-in" type="text" name="url" placeholder="https://vendor.com">'
                '<input class="note-in" type="text" name="category" placeholder="category" '
                'style="max-width:150px">'
                '<button class="btn ghost">Add</button></form>')
    part = ('<div class="card"><div class="card-h">'
            f'{icon("check-circle")}<h2>Partner sites</h2><div class="spacer"></div>'
            f'<span class="chip num">{len(partners)}</span></div>'
            '<div class="card-b">'
            '<p class="mut" style="margin:0 0 12px;line-height:1.6">Vendors and partners kept for '
            'reference. These are not scanned for tenders.</p>'
            f'{prows or "<div class=empty>None yet.</div>"}{padd}</div></div>')

    return (_mtender_card(store, conn, ro) + '<div class="gap"></div>' + web
            + '<div class="gap"></div>' + part)
