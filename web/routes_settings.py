from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from web.render import _e, _layout

router = APIRouter()

_STYLE = """
<style>
.us-intro{color:var(--mut);margin:2px 0 18px;max-width:74ch;line-height:1.5}
.us-sect{margin-bottom:16px}
.us-sect h3{margin:0 0 3px;font-size:15px}
.us-sect .sub{color:var(--mut);font-size:12.5px;margin:0 0 6px;line-height:1.5;max-width:80ch}
.opt{display:grid;grid-template-columns:270px 1fr;gap:18px;align-items:start;
  padding:13px 0;border-bottom:1px solid var(--line)}
.opt:last-of-type{border-bottom:none}
.opt-l{display:flex;align-items:center;gap:7px;padding-top:7px}
.opt-l .name{font-size:13.5px}
.opt-f input[type=text],.opt-f input[type=number],.opt-f textarea{width:100%;max-width:540px;box-sizing:border-box}
.opt-f textarea{min-height:66px;font-family:inherit;font-size:13px;line-height:1.55}
.opt-f .u{color:var(--mut);font-size:11.5px;margin:4px 0 0}
.help{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;
  border-radius:999px;font-size:11px;cursor:help;background:var(--chip);color:var(--mut);
  box-shadow:inset 0 0 0 1px var(--line)}
.kwrow{display:grid;grid-template-columns:1fr 92px;gap:9px 12px;max-width:470px;align-items:center;margin-bottom:8px}
.kwrow .hd{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px}
.kwview{margin:2px 0 12px}
.tag{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-size:12.5px;
  margin:0 5px 5px 0;background:var(--chip);box-shadow:inset 0 0 0 1px var(--line)}
.tag .w{font-size:11px;opacity:.75;font-variant-numeric:tabular-nums}
.tag.pos{background:var(--ok-weak);color:var(--ok);box-shadow:inset 0 0 0 1px rgba(63,185,80,.28)}
.tag.neg{background:rgba(248,81,73,.10);color:var(--bad);box-shadow:inset 0 0 0 1px rgba(248,81,73,.28)}
.save-row{margin-top:14px}
</style>
"""


def _opt(name, help_text, field, unit=""):
    u = f'<p class="u">{_e(unit)}</p>' if unit else ""
    return (f'<div class="opt"><div class="opt-l"><span class="name">{_e(name)}</span>'
            f'<span class="help" title="{_e(help_text)}">?</span></div>'
            f'<div class="opt-f">{field}{u}</div></div>')


def _txt(name, value, ph=""):
    return f'<input type=text name="{name}" value="{_e(value or "")}" placeholder="{_e(ph)}">'


def _num(name, value, step="1"):
    return f'<input type=number step="{step}" name="{name}" value="{_e(value)}">'


def _area(name, lines):
    body = "\n".join(str(x) for x in lines) if isinstance(lines, list) else str(lines or "")
    return f'<textarea name="{name}" spellcheck="false">{_e(body)}</textarea>'


def _lines(text):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _company_section(p, ro):
    dis = ro
    rows = (
        _opt("Company name", "The legal name of your company. Shown to the model as the bidder.",
             _txt("company", p.get("company")))
        + _opt("Country", "Home country. Helps judge local vs cross-border tenders.",
               _txt("country", p.get("country")))
        + _opt("Years of experience", "How long the company has operated. Signals track record.",
               _num("experience_years", p.get("experience_years", 0)))
        + _opt("EU procurement arm", "Related EU entity used to buy/bid inside the EU, if any.",
               _txt("eu_arm", p.get("eu_arm")))
        + _opt("What we do (verticals)",
               "Your areas of work — one per line. The model checks a tender against these to "
               "decide if it fits you.", _area("verticals", p.get("verticals") or []),
               "one per line")
        + _opt("Services", "Services you provide (integration, supply, maintenance…). One per line.",
               _area("services", p.get("services") or []), "one per line")
        + _opt("Certifications", "Certifications you hold (ISO…). One per line.",
               _area("certifications", p.get("certifications") or []), "one per line")
        + _opt("Reference clients", "Notable clients you've delivered to. Strengthens credibility. "
               "One per line.", _area("references", p.get("references") or []), "one per line")
        + _opt("Authorised vendors",
               "Vendors you're an authorised partner of, with the role. One per line as "
               "'Vendor = role'.",
               _area("vendors", [f"{k} = {v}" for k, v in (p.get("vendor_partnerships") or {}).items()]),
               "one per line: Vendor = role")
        + _opt("Partner network", "Other companies you can subcontract or team with. One per line.",
               _area("partner_network", p.get("partner_network") or []), "one per line")
        + _opt("Notes", "Free text the model reads for extra context about how you operate.",
               _area("notes", p.get("notes") or ""))
    )
    save = "" if dis else '<div class="save-row"><button>Save company</button></div>'
    return ('<div class="card us-sect"><h3>Your company</h3>'
            '<p class="sub">This is exactly what the engine treats as “us” when it decides whether '
            'a tender is worth pursuing. Keep it accurate.</p>'
            '<form method=post action="/user-settings/company">' + rows + save + '</form></div>')


def _keywords_section(kw, ro):
    pos = sorted([(k, v) for k, v in kw.items() if (v or 0) > 0], key=lambda x: -x[1])
    neg = sorted([(k, v) for k, v in kw.items() if (v or 0) < 0], key=lambda x: x[1])

    def chips(pairs, cls):
        return "".join(f'<span class="tag {cls}">{_e(k)}<span class="w">'
                       f'{"+" if v>0 else ""}{_e(v)}</span></span>' for k, v in pairs) or \
            '<span class="mut" style="font-size:12.5px">—</span>'

    view = ('<div class="kwview"><div style="margin-bottom:7px">' + chips(pos, "pos") + '</div>'
            '<div>' + chips(neg, "neg") + '</div></div>')

    if ro:
        return ('<div class="card us-sect"><h3>Search keywords</h3>'
                '<p class="sub">Words scored in each tender title.</p>' + view + '</div>')

    ordered = sorted(kw.items(), key=lambda x: -x[1])
    rows = '<div class="kwrow"><span class="hd">Keyword</span><span class="hd">Weight</span></div>'
    idx = 0
    for k, v in ordered:
        rows += (f'<div class="kwrow"><input type=text name="kw{idx}" value="{_e(k)}">'
                 f'<input type=number step="0.5" name="wt{idx}" value="{_e(v)}"></div>')
        idx += 1
    for j in range(4):
        rows += (f'<div class="kwrow"><input type=text name="kw{idx}" placeholder="new keyword">'
                 f'<input type=number step="0.5" name="wt{idx}" placeholder="weight"></div>')
        idx += 1

    return ('<div class="card us-sect"><h3>Search keywords</h3>'
            '<p class="sub">Every tender title is scored by these words. A <b>positive</b> weight '
            'raises relevance, a <b>negative</b> one pushes the tender out. Clear a keyword to '
            'remove it; use the blank rows to add new ones.</p>' + view
            + '<form method=post action="/user-settings/keywords">' + rows
            + '<div class="save-row"><button>Save keywords</button></div></form></div>')


def _tuning_section(bt, vb, max_age, batch, ro):
    if ro:
        return ""
    rows = (
        _opt("Relevant if score ≥",
             "A tender scoring at or above this is treated as clearly relevant.",
             _num("relevant", bt.get("relevant", 3), "0.5"))
        + _opt("Borderline (gray) if score ≥",
               "Below relevant but at or above this = borderline, worth a second look.",
               _num("gray", bt.get("gray", 0.5), "0.5"))
        + _opt("Minimum tender value",
               "Tenders worth less than this are penalised as likely too small.",
               _num("value_min", vb.get("min", 5000)))
        + _opt("Penalty below minimum",
               "Score adjustment applied when a tender is under the minimum value.",
               _num("value_pen", vb.get("weight_below_min", -1), "0.5"))
        + _opt("Max tender age (days)",
               "Searching stops at tenders older than this many days.",
               _num("max_age", max_age))
        + _opt("Analysis batch size",
               "How many tenders each analysis step handles per press. Smaller = faster feedback.",
               _num("batch", batch))
    )
    return ('<div class="card us-sect"><h3>Relevance &amp; search tuning</h3>'
            '<p class="sub">The dials that decide which tenders count as relevant, how far back '
            'to look, and how much is processed at a time.</p>'
            '<form method=post action="/user-settings/tuning">' + rows
            + '<div class="save-row"><button>Save tuning</button></div></form></div>')


@router.get("/user-settings")
def user_settings(request: Request, msg: str = "", err: str = ""):
    store = request.state.store
    ro = request.state.readonly
    p = store.get("capabilities.profile", {}) or {}
    kw = store.get("triage.keyword_weights", {}) or {}
    bt = store.get("triage.bucket_thresholds", {}) or {}
    vb = store.get("triage.value_band", {}) or {}
    max_age = store.get("collect.max_age_days", 90)
    batch = store.get("analyze.batch_size", 50)

    banner = ""
    if msg:
        banner += f'<div class="ok">{_e(msg)}</div>'
    if err:
        banner += f'<div class="err">{_e(err)}</div>'
    if ro:
        banner += '<div class="ok">read-only mode — editing is disabled</div>'

    body = (_STYLE + banner
            + '<p class="us-intro">Everything here shapes what the engine finds and how it decides '
              'a tender is worth your time. Hover the “?” on any option for what it does.</p>'
            + _company_section(p, ro)
            + _keywords_section(kw, ro)
            + _tuning_section(bt, vb, max_age, batch, ro))
    return _layout(request, "User Settings", body)


def _redir(msg="", err=""):
    q = ("?msg=" + quote(msg)) if msg else ("?err=" + quote(err)) if err else ""
    return RedirectResponse("/user-settings" + q, status_code=303)


def _numval(v, default):
    try:
        f = float(v)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return default


@router.post("/user-settings/company")
async def save_company(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    f = await request.form()
    store = request.state.store
    p = dict(store.get("capabilities.profile", {}) or {})
    p["company"] = (f.get("company") or "").strip()
    p["country"] = (f.get("country") or "").strip()
    p["experience_years"] = int(_numval(f.get("experience_years"), 0))
    p["eu_arm"] = (f.get("eu_arm") or "").strip()
    p["verticals"] = _lines(f.get("verticals"))
    p["services"] = _lines(f.get("services"))
    p["certifications"] = _lines(f.get("certifications"))
    p["references"] = _lines(f.get("references"))
    p["partner_network"] = _lines(f.get("partner_network"))
    p["notes"] = (f.get("notes") or "").strip()
    vendors = {}
    for ln in _lines(f.get("vendors")):
        k, sep, v = ln.partition("=")
        if k.strip():
            vendors[k.strip()] = v.strip()
    p["vendor_partnerships"] = vendors
    store.set("capabilities.profile", p, actor="web", note="edit company (user settings)")
    return _redir(msg="company saved")


@router.post("/user-settings/keywords")
async def save_keywords(request: Request):
    if request.state.readonly:
        return _redir(err="read-only mode")
    f = await request.form()
    weights = {}
    i = 0
    while f"kw{i}" in f:
        k = (f.get(f"kw{i}") or "").strip().lower()
        w = f.get(f"wt{i}")
        i += 1
        if not k or w in (None, ""):
            continue
        try:
            wv = float(w)
        except (TypeError, ValueError):
            continue
        weights[k] = int(wv) if wv == int(wv) else wv
    if not weights:
        return _redir(err="no keywords to save")
    request.state.store.set("triage.keyword_weights", weights, actor="web",
                            note="edit keywords (user settings)")
    return _redir(msg=f"saved {len(weights)} keyword(s)")


@router.post("/user-settings/tuning")
def save_tuning(request: Request, relevant: str = Form("3"), gray: str = Form("0.5"),
                value_min: str = Form("5000"), value_pen: str = Form("-1"),
                max_age: str = Form("90"), batch: str = Form("50")):
    if request.state.readonly:
        return _redir(err="read-only mode")
    store = request.state.store
    store.set("triage.bucket_thresholds",
              {"relevant": _numval(relevant, 3), "gray": _numval(gray, 0.5)},
              actor="web", note="edit thresholds (user settings)")
    store.set("triage.value_band",
              {"min": _numval(value_min, 5000), "weight_below_min": _numval(value_pen, -1)},
              actor="web", note="edit value band (user settings)")
    store.set("collect.max_age_days", max(1, int(_numval(max_age, 90))),
              actor="web", note="edit age (user settings)")
    store.set("analyze.batch_size", max(1, int(_numval(batch, 50))),
              actor="web", note="edit batch (user settings)")
    return _redir(msg="tuning saved")
