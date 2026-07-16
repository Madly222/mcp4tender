from __future__ import annotations

from engine.secrets import get_api_key, key_source, mask
from web import settings_ops
from web.render import _e
from web.user.icons import icon

HANDLED = {
    "company": ("capabilities.profile",),
    "relevance": ("triage.keyword_weights",),
    "ai": (),
    "schedule": ("schedule.jobs", "schedule.timezone"),
    "suppliers": ("suppliers.catalog",),
}


def _field(label, help_text, control, unit=""):
    u = f'<span class="mut" style="font-size:12px">{_e(unit)}</span>' if unit else ""
    return ('<div class="pref">'
            f'<div class="pref-h"><label>{_e(label)}</label>{u}</div>'
            f'<div class="pref-b" style="display:block">{control}</div>'
            f'<div class="pref-help">{_e(help_text)}</div></div>')


def _txt(name, value):
    return f'<input class="note-in" type="text" name="{name}" value="{_e(value or "")}">'


def _num(name, value):
    return (f'<input class="note-in" type="number" name="{name}" value="{_e(value or 0)}" '
            'style="max-width:140px">')


def _area(name, lines, rows=4):
    body = "\n".join(lines) if isinstance(lines, list) else (lines or "")
    return f'<textarea class="note-in ta" name="{name}" rows="{rows}">{_e(body)}</textarea>'


def company_form(store):
    p = store.get("capabilities.profile", {}) or {}
    vendors = [f"{k} = {v}" for k, v in (p.get("vendor_partnerships") or {}).items()]
    rows = (
        _field("Company name", "The legal name. The model is told this is the bidder.",
               _txt("company", p.get("company")))
        + _field("Country", "Home country. Helps judge local versus cross-border tenders.",
                 _txt("country", p.get("country")))
        + _field("Years in business", "Signals track record to the model.",
                 _num("experience_years", p.get("experience_years", 0)))
        + _field("EU procurement arm", "A related EU entity used to bid inside the EU, if any.",
                 _txt("eu_arm", p.get("eu_arm")))
        + _field("What you do", "Your areas of work. Every tender is checked against these.",
                 _area("verticals", p.get("verticals") or [], 5), "one per line")
        + _field("Services", "Integration, supply, maintenance and so on.",
                 _area("services", p.get("services") or []), "one per line")
        + _field("Certifications", "ISO and the like. Often a hard qualification criterion.",
                 _area("certifications", p.get("certifications") or []), "one per line")
        + _field("Reference clients", "Who you have delivered to. Strengthens credibility.",
                 _area("references", p.get("references") or []), "one per line")
        + _field("Authorised vendors", "Vendors you are an authorised partner of, with the role.",
                 _area("vendors", vendors), "one per line: Vendor = role")
        + _field("Partner network", "Companies you can subcontract or team with.",
                 _area("partner_network", p.get("partner_network") or []), "one per line")
        + _field("Notes", "Free text the model reads for extra context about how you operate.",
                 _area("notes", p.get("notes") or "", 5))
    )
    return ('<form method="post" action="/app/settings/company/save" class="card">'
            f'<div class="card-h">{icon("shield")}<h2>Your company</h2></div>'
            '<div class="card-b">'
            '<p class="mut" style="margin:0 0 14px;line-height:1.6">This is exactly what the '
            'engine treats as “us” when it decides whether a tender is worth pursuing. '
            'Everything the AI says about fit comes from this page. Keep it accurate.</p>'
            f'{rows}</div>'
            '<div class="fb" style="border-top:1px solid var(--line)">'
            '<button class="btn">Save company</button></div></form>')


def keywords_form(store):
    kw = store.get("triage.keyword_weights", {}) or {}
    pos = sorted([(k, v) for k, v in kw.items() if (v or 0) > 0], key=lambda x: -x[1])
    neg = sorted([(k, v) for k, v in kw.items() if (v or 0) < 0], key=lambda x: x[1])

    def chips(pairs, cls):
        if not pairs:
            return '<span class="t-doc-n">—</span>'
        return "".join(f'<span class="chip {cls}">{_e(k)} '
                       f'<b>{"+" if v > 0 else ""}{_e(v)}</b></span>' for k, v in pairs)

    preview = ('<div class="t-tags" style="margin-bottom:8px">' + chips(pos, "ok") + "</div>"
               '<div class="t-tags">' + chips(neg, "bad") + "</div>")
    rows = []
    idx = 0
    for k, v in sorted(kw.items(), key=lambda x: -x[1]):
        rows.append(f'<div class="kw2"><input class="note-in" type="text" name="kw{idx}" '
                    f'value="{_e(k)}"><input class="note-in" type="number" step="0.5" '
                    f'name="wt{idx}" value="{_e(v)}"></div>')
        idx += 1
    for _ in range(4):
        rows.append(f'<div class="kw2"><input class="note-in" type="text" name="kw{idx}" '
                    f'placeholder="new keyword"><input class="note-in" type="number" step="0.5" '
                    f'name="wt{idx}" placeholder="weight"></div>')
        idx += 1
    return ('<form method="post" action="/app/settings/keywords/save" class="card">'
            f'<div class="card-h">{icon("filter")}<h2>Search keywords</h2></div>'
            '<div class="card-b">'
            '<p class="mut" style="margin:0 0 12px;line-height:1.6">Every tender title, '
            'description and buyer is scored by these words. A <b>positive</b> weight pulls the '
            'tender towards you, a <b>negative</b> one pushes it away. Clear a keyword to delete '
            'it; use the blank rows to add more.</p>'
            f'{preview}<div class="gap"></div>'
            '<div class="kw2 kw2-h"><span>Keyword</span><span>Weight</span></div>'
            + "".join(rows) + "</div>"
            '<div class="fb" style="border-top:1px solid var(--line)">'
            '<button class="btn">Save keywords</button></div></form>')


def apikey_form(store):
    key = get_api_key()
    src = key_source()
    if key:
        state = (f'<span class="chip ok">set</span>'
                 f'<span class="t-doc-n mono">{_e(mask(key))}</span>')
    else:
        state = '<span class="chip bad">missing</span>'
    where = f'<span class="t-doc-n">from {_e(src)}</span>' if src else ""
    last = store.get("llm.last_key_check") or {}
    banner = ""
    if last.get("status") == "ok":
        banner = ('<div class="strip" style="background:var(--ok-weak);'
                  'border:1px solid var(--ok-line);margin-bottom:12px">'
                  f'<div class="ic" style="background:var(--ok)">{icon("check", 3)}</div>'
                  '<div class="tx"><b>Last test passed</b>'
                  f'<span>{_e(last.get("model") or "")}</span></div></div>')
    elif last.get("status"):
        banner = ('<div class="strip bad" style="margin-bottom:12px">'
                  f'<div class="ic">{icon("bang", 3)}</div>'
                  f'<div class="tx"><b>Last test failed: {_e(last.get("code") or "")}</b>'
                  f'<span>{_e((last.get("detail") or "")[:110])}</span></div></div>')
    return ('<form method="post" action="/app/settings/apikey/save" class="card">'
            f'<div class="card-h">{icon("shield")}<h2>Your Anthropic API key</h2>'
            f'<div class="spacer"></div>{state}</div>'
            f'<div class="card-b">{banner}'
            '<p class="mut" style="margin:0 0 12px;line-height:1.6">Analysis runs on your own key '
            'and your own bill. It is written to this instance\'s <span class="mono">.env</span> '
            'and applied without a restart. Leave the field blank to keep the current key and '
            'just re-test it.</p>'
            '<input class="note-in mono" type="password" name="api_key" autocomplete="off" '
            'placeholder="sk-ant-...">'
            f'<div class="pref-help">{where}</div></div>'
            '<div class="fb" style="border-top:1px solid var(--line);gap:8px">'
            '<button class="btn">Save key</button>'
            '<button class="btn ghost" formaction="/app/settings/apikey/test">Test it</button>'
            "</div></form>")


def schedule_form(store):
    job = settings_ops.collect_job(store)
    tz = store.get("schedule.timezone", "") or ""
    on = " checked" if job.get("enabled") else ""
    days = set(job.get("days") or [])
    day_boxes = "".join(
        f'<label class="switch"><input type="checkbox" name="day_{i}"'
        f'{" checked" if i in days else ""}><span>{_e(label)}</span></label>'
        for i, label in settings_ops.DAYS)
    picked = set(job.get("sources") or [])
    src_boxes = "".join(
        f'<label class="switch"><input type="checkbox" name="src_{k}"'
        f'{" checked" if k in picked else ""}><span>{_e(label)}</span></label>'
        for k, label in settings_ops.KNOWN_SOURCES)
    times = ", ".join(job.get("at") or [])
    extra = settings_ops.other_jobs(store)
    extra_note = ""
    if extra:
        extra_note = (f'<div class="pref-help">{len(extra)} other job(s) are configured and are '
                      "left untouched by this form.</div>")
    rows = (
        _field("Scanning is", "Turn this off and nothing is collected automatically.",
               f'<label class="switch"><input type="checkbox" name="enabled"{on}>'
               f'<span>{"On" if on else "Off"}</span></label>')
        + _field("Run at", "Times of day, 24h. Comma separated. Up to 24 a day. Anything that is "
                 "not HH:MM is dropped silently.", _txt("times", times), "e.g. 06:00, 18:00")
        + _field("On these days", "None ticked means every day.",
                 f'<div class="switches">{day_boxes}</div>')
        + _field("Timezone", "IANA name. Empty means the server's local time.",
                 _txt("timezone", tz), "e.g. Europe/Chisinau")
        + _field("Scan these sources", "None ticked means all of them.",
                 f'<div class="switches">{src_boxes}</div>')
        + _field("Analyse after collecting",
                 "Run triage, extraction, applicability and sourcing on whatever was just found. "
                 "This is what spends money on your API key.",
                 '<label class="switch"><input type="checkbox" name="analyze"'
                 f'{" checked" if job.get("analyze") else ""}><span>Yes</span></label>')
    )
    return ('<form method="post" action="/app/settings/schedule/save" class="card">'
            f'<div class="card-h">{icon("clock")}<h2>When we scan</h2></div>'
            f'<div class="card-b">{rows}{extra_note}</div>'
            '<div class="fb" style="border-top:1px solid var(--line)">'
            '<button class="btn">Save schedule</button></div></form>')


def _cat_block(idx, it, currencies):
    it = it or {}
    cur = (it.get("currency") or "MDL").upper()
    opts = "".join(f'<option value="{c}"{" selected" if c == cur else ""}>{c}</option>'
                   for c in sorted(set(currencies) | {cur}))
    rm = ""
    if it:
        rm = (f'<label class="switch"><input type="checkbox" name="cat{idx}_remove">'
              "<span>Remove</span></label>")
    return (f'<div class="catrow">'
            f'<input type="hidden" name="cat{idx}_id" value="{_e(it.get("id") or "")}">'
            '<div class="cat2">'
            f'<div><label class="catl">What it is</label>'
            f'<input class="note-in" type="text" name="cat{idx}_denumire" '
            f'value="{_e(it.get("denumire") or "")}" placeholder="Cameră ANPR 4K edge"></div>'
            f'<div><label class="catl">Model</label>'
            f'<input class="note-in" type="text" name="cat{idx}_model" '
            f'value="{_e(it.get("model") or "")}"></div></div>'
            '<div class="cat2">'
            f'<div><label class="catl">Supplier</label>'
            f'<input class="note-in" type="text" name="cat{idx}_supplier" '
            f'value="{_e(it.get("supplier") or "")}"></div>'
            f'<div><label class="catl">Vendor</label>'
            f'<input class="note-in" type="text" name="cat{idx}_vendor" '
            f'value="{_e(it.get("vendor") or "")}"></div></div>'
            '<div class="cat2">'
            f'<div><label class="catl">Unit price</label>'
            f'<input class="note-in" type="number" step="any" name="cat{idx}_price" '
            f'value="{_e(it.get("price") if it else "")}"></div>'
            f'<div><label class="catl">Currency</label>'
            f'<select name="cat{idx}_currency">{opts}</select></div></div>'
            f'<div><label class="catl">Specs</label>'
            f'<textarea class="note-in" name="cat{idx}_specs" rows="2">'
            f'{_e(it.get("specs") or "")}</textarea></div>'
            f'{rm}</div>')


def catalog_form(store):
    items = store.get("suppliers.catalog", []) or []
    items = [i for i in items if isinstance(i, dict)]
    currencies = settings_ops.catalog_currencies(store)
    rates = store.get("suppliers.fx_rates", {}) or {}
    blocks = [_cat_block(i, it, currencies) for i, it in enumerate(items)]
    blocks += [_cat_block(len(items) + j, None, currencies) for j in range(2)]
    bad = sorted({(it.get("currency") or "").upper() for it in items
                  if not settings_ops._rate_known((it.get("currency") or ""), rates)} - {""})
    warn = ""
    if bad:
        warn = ('<div class="strip bad" style="margin-bottom:12px">'
                f'<div class="ic">{icon("bang", 3)}</div><div class="tx">'
                f'<b>No exchange rate for {_e(", ".join(bad))}</b>'
                "<span>Those line costs cannot be converted, so the margin will be wrong. "
                "Add the rate under suppliers.fx_rates below.</span></div></div>")
    return ('<form method="post" action="/app/settings/catalog/save" class="card">'
            f'<div class="card-h">{icon("check-circle")}<h2>Supplier catalog</h2>'
            f'<div class="spacer"></div><span class="chip num">{len(items)}</span></div>'
            f'<div class="card-b">{warn}'
            '<p class="mut" style="margin:0 0 14px;line-height:1.6">What you can supply and what '
            'it costs you. The engine matches each tender requirement against this list and works '
            'out the margin you see on every card. Prices are yours — cost, not the offer. '
            'Tick <b>Remove</b> or clear the name to delete a line.</p>'
            + "".join(blocks) + "</div>"
            '<div class="fb" style="border-top:1px solid var(--line)">'
            '<button class="btn">Save catalog</button></div></form>')


FORMS = {"company": company_form, "relevance": keywords_form, "ai": apikey_form,
         "schedule": schedule_form, "suppliers": catalog_form}
