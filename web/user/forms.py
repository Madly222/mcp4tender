from __future__ import annotations

from engine.secrets import get_api_key, key_source, mask
from web.render import _e
from web.user.icons import icon

HANDLED = {
    "company": ("capabilities.profile",),
    "relevance": ("triage.keyword_weights",),
    "ai": (),
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


FORMS = {"company": company_form, "relevance": keywords_form, "ai": apikey_form}
