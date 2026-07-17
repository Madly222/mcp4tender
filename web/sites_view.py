from __future__ import annotations

import json
import uuid

from fastapi import Form, Request

from web.render import _e, _layout, _table
from web.sites_common import (_bar, _crawl_rows, _probe_url, _redir_sites,
                              _set_auth, _validate_url, router)

_API_ONLY_HOSTS = ("mtender.md", "www.mtender.md")


def _api_only_site(url):
    u = (url or "").lower()
    return any(("//" + h) in u or u.endswith(h) or ("//" + h + "/") in u
               for h in _API_ONLY_HOSTS)


def _retired_admin_sites(request: Request, msg: str = "", err: str = ""):
    store = request.state.store
    conn = request.state.conn
    ro = request.state.readonly
    all_tenders = store.get("sites.tenders", []) or []
    tenders_list = [s for s in all_tenders if not _api_only_site(s.get("url"))]
    partners = store.get("sites.partners", []) or []
    gw_enabled = bool(store.get("sources.genericweb", {}).get("enabled", False))
    engine = str(store.get("sources.genericweb", {}).get("engine", "builtin")).lower()
    try:
        from engine.crawl4ai_fetch import crawl4ai_available
        c4_ok = crawl4ai_available()
    except Exception:
        c4_ok = False
    mt_enabled = bool(store.get("sources.mtender", {}).get("enabled", False))
    mt_count = conn.execute("SELECT COUNT(*) c FROM tenders WHERE source='mtender'").fetchone()["c"]
    crawl = _crawl_rows(conn, [s.get("id") for s in tenders_list])
    banner = ""
    if msg:
        banner += f'<div class="ok">{_e(msg)}</div>'
    if err:
        banner += f'<div class="err">{_e(err)}</div>'

    def rm_btn(kind, sid):
        if ro:
            return ""
        return (f'<form method=post action="/sites/remove" style="margin:0">'
                f'<input type=hidden name=kind value="{kind}">'
                f'<input type=hidden name=id value="{_e(sid)}">'
                f'<button class="ghost danger">×</button></form>')

    trows = []
    for s in tenders_list:
        sid = s.get("id", "")
        cs = crawl.get(sid)
        collected = (cs["total_collected"] if cs else 0) or 0
        est = (cs["total_estimate"] if cs else None)
        detected = (cs["detected_count"] if (cs and "detected_count" in cs.keys()) else None)
        exhausted = bool(cs and cs["exhausted"])
        bar = _bar(collected, est, detected)
        if exhausted:
            bar += '<div class="v-ok" style="font-size:11px">all collected</div>'
        note = cs["note"] if (cs and "note" in cs.keys() and cs["note"]) else ""
        if note:
            bar += f'<div class="mut" style="font-size:11px;max-width:240px">{_e(note)}</div>'
        site_engine = s.get("engine")
        if site_engine:
            bar += f'<div class="mut" style="font-size:11px">engine: {_e(site_engine)}</div>'
        has_auth = bool(cs and cs["auth_json"])
        auth_lbl = '🔒 set' if has_auth else '<span class="mut">—</span>'
        step = int(s.get("batch_size", 30) or 30)

        if not ro:
            toggle = (f'<form method=post action="/sites/toggle" style="margin:0">'
                      f'<input type=hidden name=id value="{_e(sid)}">'
                      f'<button class="ghost">{"on" if s.get("enabled", True) else "off"}</button></form>')
            step_cell = (f'<form method=post action="/sites/settings" style="margin:0" class="row">'
                         f'<input type=hidden name=id value="{_e(sid)}">'
                         f'<input type=number min=1 max=1000 name=batch_size value="{step}" '
                         f'style="width:62px" title="tenders to collect per batch"> tenders'
                         f'<button class="ghost">set</button></form>')
            actions = (f'<form method=post action="/sites/collect-batch" style="margin:0;display:inline">'
                       f'<input type=hidden name=site_id value="{_e(sid)}">'
                       f'<button title="collect the next {step} tenders from this site">next {step} ▸</button></form> '
                       f'<form method=post action="/sites/estimate" style="margin:0;display:inline">'
                       f'<input type=hidden name=id value="{_e(sid)}">'
                       f'<button class="ghost" title="re-estimate how many tenders this site has">estimate</button></form> '
                       f'<form method=post action="/sites/reset-cursor" style="margin:0;display:inline" '
                       f'onsubmit="return confirm(\'Reset crawl position to the start?\')">'
                       f'<input type=hidden name=id value="{_e(sid)}">'
                       f'<button class="ghost">reset</button></form> '
                       f'<form method=post action="/sites/preview" style="margin:0;display:inline">'
                       f'<input type=hidden name=id value="{_e(sid)}">'
                       f'<button class="ghost" title="fetch this page now and show what is found">test</button></form> '
                       f'<form method=post action="/sites/analyze" style="margin:0;display:inline">'
                       f'<input type=hidden name=id value="{_e(sid)}">'
                       f'<button class="ghost" title="profile this site: are there tenders and how to reach them">analyze</button></form> '
                       f'<form method=post action="/sites/render-toggle" style="margin:0;display:inline">'
                       f'<input type=hidden name=id value="{_e(sid)}">'
                       f'<button class="ghost" title="render the page with a headless browser (for JS sites)">'
                       f'JS:{"on" if s.get("render") else "off"}</button></form>')
        else:
            toggle = "on" if s.get("enabled", True) else "off"
            step_cell = f"{step} tenders"
            actions = ""
        url = _e(s.get("url"))
        trows.append([_e(s.get("label")),
                      f'<a href="{url}" target="_blank">{url}</a>',
                      step_cell, bar, auth_lbl, actions, toggle, rm_btn("tenders", sid)])

    prows = []
    for s in partners:
        url = _e(s.get("url"))
        prows.append([_e(s.get("label")),
                      f'<a href="{url}" target="_blank">{url}</a>',
                      _e(s.get("category")), _e(s.get("notes")),
                      rm_btn("partners", s.get("id", ""))])

    add_t = add_p = ""
    if not ro:
        add_t = (
            '<form method=post action="/sites/add"><div class="card">'
            '<input type=hidden name=kind value="tenders"><div class=row>'
            '<input type=text name=label placeholder="name" style="max-width:160px">'
            '<input type=text name=url placeholder="https://site.md/tenders (base URL only)" style="flex:1;min-width:240px">'
            '<input type=number min=1 max=1000 name=batch_size value="30" style="width:80px" title="tenders per batch"> tenders'
            '</div><div class=row style="margin-top:8px">'
            '<input type=text name=login placeholder="login (optional)" style="max-width:200px">'
            '<input type=password name=password placeholder="password (optional)" style="max-width:200px">'
            '<label class="mut" style="font-size:13px"><input type=checkbox name=render value="1"> needs JavaScript</label>'
            '<button>+ add site</button> '
            '<button class="ghost" formaction="/sites/detect" '
            'title="fetch one test page and auto-pick the cheapest method that works: '
            'plain HTML → JS render → crawl4ai">detect &amp; add</button></div>'
            '<p class="hint">Give only the base listing URL. "detect &amp; add" fetches one test '
            'page with increasingly capable methods and keeps the cheapest one that actually finds '
            'tenders — no need to guess the JS toggle yourself. "Batch" = how many tenders to pull '
            'per run; press "next N ▸" to take the next batch — progress is tracked per site. '
            'Login is HTTP Basic only.</p>'
            '</div></form>')
        add_p = (
            '<form method=post action="/sites/add"><div class="card">'
            '<input type=hidden name=kind value="partners"><div class=row>'
            '<input type=text name=label placeholder="partner" style="max-width:200px">'
            '<input type=text name=url placeholder="https://partener.com" style="flex:1;min-width:240px">'
            '<input type=text name=category placeholder="category" style="max-width:160px">'
            '<input type=text name=notes placeholder="note" style="max-width:200px">'
            '<button>+ add partner</button></div></div></form>')

    controls = ""
    if not ro:
        controls = (
            f'<form method=post action="/sites/search-toggle" style="margin:0">'
            f'<button class="{"" if gw_enabled else "ghost"}">'
            f'web search: {"ON" if gw_enabled else "off"}</button></form>'
            f'<form method=post action="/sites/collect" style="margin:0">'
            f'<button class="ghost" title="check all sites for new tenders (front pages)">Check new</button></form>'
            f'<form method=post action="/sites/collect-batch" style="margin:0">'
            f'<button title="collect the next step from every site">Collect next step ▸</button></form>'
            f'<form method=post action="/sites/estimate" style="margin:0">'
            f'<button class="ghost" title="estimate totals for all sites">Estimate all</button></form>'
            f'<form method=post action="/sites/engine-toggle" style="margin:0">'
            f'<button class="{"" if engine == "crawl4ai" else "ghost"}" '
            f'title="switch the collection engine">engine: {_e(engine)}</button></form>'
            f'<form method=post action="/sites/wipe" style="margin:0" '
            f'onsubmit="return confirm(\'Delete ALL tenders collected from sites and reset all progress? '
            f'This is for testing a clean re-run.\')">'
            f'<button class="ghost danger" title="wipe everything collected via site search (test reset)">Clear ALL collected</button></form>')

    body = (
        banner +
        f'<div class="card"><div class=row>{controls}'
        f'<span class=mut>"Check new" scans front pages (daily). "Collect next step" pulls each '
        f'site\'s chosen batch and remembers the position. Collecting only stores tenders — run the '
        f'analysis separately on the <a href="/analyze">Analyze</a> page.</span>'
        + ('<div class="err" style="margin-top:8px">Engine is set to <b>crawl4ai</b> but the '
           'library is not installed. Run <span class=mono>pip install crawl4ai</span> in the '
           'venv (and <span class=mono>playwright install chromium</span>), or switch engine back '
           'to builtin.</div>' if (engine == "crawl4ai" and not c4_ok) else
           ('<div class="ok" style="margin-top:8px">Crawl4AI engine active — pages are rendered '
            'and cleaned by the library.</div>' if engine == "crawl4ai" else ''))
        + f'<div class=row style="margin-top:8px">'
        f'<form method=post action="/sites/preview" class=row style="margin:0;flex:1">'
        f'<input type=text name=url placeholder="test any URL before adding (https://bank.md/achizitii)" style="flex:1;min-width:260px">'
        f'<label class="mut" style="font-size:13px"><input type=checkbox name=render value="1"> JS</label>'
        f'<button class="ghost">Test URL</button>'
        f'<button class="ghost" formaction="/sites/analyze">Analyze site</button></form></div></div>'
        f'<div class="card"><div class=row>'
        f'<form method=post action="/sites/mtender-toggle" style="margin:0">'
        f'<button class="{"" if mt_enabled else "ghost"}">MTender API: {"ON" if mt_enabled else "off"}</button></form>'
        f'<form method=post action="/sites/collect-mtender" style="margin:0">'
        f'<button class="ghost" title="collect a batch from the official MTender OCDS API">Collect MTender ▸</button></form>'
        f'<form method=post action="/sites/dedupe-mtender" style="margin:0" '
        f'onsubmit="return confirm(\'Merge MTender tenders that are stage-copies of the same '
        f'procurement (same base OCID) into one? Duplicates and their analysis are removed.\')">'
        f'<button class="ghost" title="collapse duplicate stage-copies of the same MTender procurement">Dedupe MTender</button></form>'
        f'<form method=post action="/sites/dedupe-docs" style="margin:0" '
        f'onsubmit="return confirm(\'Remove repeated attachments inside MTender tenders '
        f'(same filename re-uploaded across procurement stages)? The newest copy of each file is kept.\')">'
        f'<button class="ghost" title="remove duplicate attachments; keeps the newest version of each file">Dedupe documents</button></form>'
        f'<span class=mut>MTender (mtender.md) is a JavaScript site — the generic crawler cannot read it. '
        f'Use this official API source instead; it returns real tenders reliably ({mt_count} collected so far).</span>'
        f'</div></div>'
        f'<h2>Tender sites ({len(tenders_list)})</h2>'
        + _table(["Name", "URL", "Batch", "Progress", "Login", "Actions", "Active", ""], trows) + add_t +
        f'<h2>Partner sites ({len(partners)})</h2>'
        + _table(["Partner", "URL", "Category", "Notes", ""], prows) + add_p +
        '<p class="hint">Login note: only HTTP Basic auth is supported. Most portals use form '
        'logins (username+password posted to a page), which a simple fetcher cannot do — those '
        'need a browser-based login. Ask to add session-cookie or browser login if needed.</p>')
    return _layout(request, "Sites", body)
