from __future__ import annotations

from web.config_meta import CONFIG_META
from web.render import _e
from web.user.icons import icon
from web.user.labels import label_of

SPECS = {
    "triage.cpv_weights": {
        "kind": "pairs", "title": "CPV weights", "icon": "filter",
        "key": "CPV prefix", "val": "Weight", "num": True, "key_ph": "32",
        "blurb": "Score added when a tender's CPV code starts with this prefix. The longest "
                 "matching prefix wins. Positive pulls the tender in, negative pushes it out.",
    },
    "triage.value_band": {
        "kind": "fields", "title": "Value band", "icon": "filter",
        "labels": {"min": "Tenders below this value are penalised",
                   "weight_below_min": "Penalty applied to them"},
        "blurb": "Small tenders are usually not worth the paperwork. This is how hard they get "
                 "pushed down.",
    },
    "triage.bucket_thresholds": {
        "kind": "fields", "title": "Score cut-offs", "icon": "filter",
        "labels": {"relevant": "Relevant at this score or above",
                   "gray": "Gray zone at this score or above"},
        "blurb": "Where the triage score lands decides whether a tender is analysed at all. "
                 "Anything below the gray cut-off is dropped.",
    },
    "suppliers.fx_rates": {
        "kind": "pairs", "title": "Exchange rates", "icon": "check-circle",
        "key": "Conversion", "val": "Rate", "num": True, "key_ph": "EUR->MDL",
        "blurb": "Used to convert your catalog prices into the tender's currency. A missing rate "
                 "means the line cost cannot be converted and the margin comes out wrong.",
    },
    "llm.models": {
        "kind": "pairs", "title": "Model per stage", "icon": "sliders",
        "key": "Stage", "val": "Model", "num": False, "key_ph": "extract",
        "blurb": "Which model runs which stage. 'default' is the fallback for anything not "
                 "listed. Cheap models for reading, stronger ones for judgement.",
    },
    "applicability.model_by_bucket": {
        "kind": "pairs", "title": "Model per triage bucket", "icon": "sliders",
        "key": "Bucket", "val": "Model key", "num": False, "key_ph": "relevant",
        "blurb": "Lets the gray zone be judged by a different (usually cheaper) model than "
                 "clearly relevant tenders.",
    },
    "supervisor.rank_weights": {
        "kind": "pairs", "title": "Digest ranking", "icon": "alert",
        "key": "Signal", "val": "Weight", "num": True,
        "blurb": "How the digest orders tenders. Weights are relative to each other.",
    },
    "llm.pricing": {
        "kind": "table", "title": "Model prices", "icon": "sliders",
        "cols": [("in", "Input"), ("out", "Output")], "key": "Model",
        "blurb": "USD per 1,000,000 tokens. These only compute the cost figures shown to you — "
                 "they do not change what Anthropic actually bills. Keep them current or the "
                 "spend numbers lie.",
    },
    "sources.mtender": {"kind": "fields", "title": "MTender", "icon": "search",
                        "blurb": "The national procurement portal. Free to read — no tokens are "
                                 "spent collecting from it."},
    "sources.genericweb": {"kind": "fields", "title": "Generic web scraping", "icon": "search",
                           "blurb": "Reads arbitrary tender sites listed under Sites. This one "
                                    "does spend tokens, because pages go through a model."},
}


def _label_of(sub, spec):
    given = (spec.get("labels") or {}).get(sub)
    if given:
        return given
    return label_of("x." + sub)


def _widget(name, value):
    if isinstance(value, bool):
        on = " checked" if value else ""
        return (f'<label class="switch"><input type="checkbox" name="{name}"{on}>'
                f'<span>{"On" if value else "Off"}</span></label>')
    if isinstance(value, (int, float)):
        step = "1" if isinstance(value, int) else "any"
        return (f'<input class="note-in" type="number" step="{step}" name="{name}" '
                f'value="{_e(value)}" style="max-width:200px">')
    if isinstance(value, list):
        return (f'<input class="note-in" type="text" name="{name}" '
                f'value="{_e(", ".join(str(x) for x in value))}">')
    if len(str(value or "")) > 70:
        return f'<textarea class="note-in ta" name="{name}" rows="2">{_e(value)}</textarea>'
    return f'<input class="note-in" type="text" name="{name}" value="{_e(value or "")}">'


def _shell(key, spec, inner):
    blurb = spec.get("blurb") or CONFIG_META.get(key, "")
    return ('<form method="post" action="/app/settings/kv/save" class="card">'
            f'<div class="card-h">{icon(spec.get("icon", "sliders"))}'
            f'<h2>{_e(spec["title"])}</h2><div class="spacer"></div>'
            f'<span class="chip plain mono">{_e(key)}</span></div>'
            '<div class="card-b">'
            f'<p class="mut" style="margin:0 0 14px;line-height:1.6">{_e(blurb)}</p>'
            f'{inner}</div>'
            f'<input type="hidden" name="key" value="{_e(key)}">'
            '<div class="fb" style="border-top:1px solid var(--line)">'
            '<button class="btn">Save</button></div></form>')


def _pairs(key, value, spec):
    items = sorted((value or {}).items(), key=lambda x: (-x[1], x[0])
                   if spec.get("num") else (0, str(x[0])))
    rows = [f'<div class="kw2 kw2-h"><span>{_e(spec["key"])}</span>'
            f'<span>{_e(spec["val"])}</span></div>']
    idx = 0
    for k, v in items:
        vw = (f'<input class="note-in" type="number" step="any" name="v{idx}" value="{_e(v)}">'
              if spec.get("num") else
              f'<input class="note-in" type="text" name="v{idx}" value="{_e(v)}">')
        rows.append(f'<div class="kw2"><input class="note-in" type="text" name="k{idx}" '
                    f'value="{_e(k)}">{vw}</div>')
        idx += 1
    for _ in range(3):
        ph = _e(spec.get("key_ph") or "")
        vw = (f'<input class="note-in" type="number" step="any" name="v{idx}">'
              if spec.get("num") else f'<input class="note-in" type="text" name="v{idx}">')
        rows.append(f'<div class="kw2"><input class="note-in" type="text" name="k{idx}" '
                    f'placeholder="{ph}">{vw}</div>')
        idx += 1
    rows.append('<div class="pref-help">Clear a name to remove that line.</div>')
    return _shell(key, spec, "".join(rows))


def _fields(key, value, spec):
    rows = []
    for sub, v in (value or {}).items():
        rows.append('<div class="pref">'
                    f'<div class="pref-h"><label>{_e(_label_of(sub, spec))}</label></div>'
                    f'<div class="pref-b" style="display:block">{_widget("f_" + sub, v)}</div>'
                    "</div>")
    return _shell(key, spec, "".join(rows))


def _table(key, value, spec):
    cols = spec["cols"]
    head = (f'<div class="tbl3 tbl3-h"><span>{_e(spec["key"])}</span>'
            + "".join(f"<span>{_e(lbl)}</span>" for _c, lbl in cols) + "</div>")
    rows = [head]
    idx = 0
    for name, sub in sorted((value or {}).items()):
        sub = sub if isinstance(sub, dict) else {}
        cells = "".join(
            f'<input class="note-in" type="number" step="any" name="c{idx}_{c}" '
            f'value="{_e(sub.get(c, 0))}">' for c, _lbl in cols)
        rows.append(f'<div class="tbl3"><input class="note-in" type="text" name="k{idx}" '
                    f'value="{_e(name)}">{cells}</div>')
        idx += 1
    for _ in range(2):
        cells = "".join(f'<input class="note-in" type="number" step="any" name="c{idx}_{c}">'
                        for c, _lbl in cols)
        rows.append(f'<div class="tbl3"><input class="note-in" type="text" name="k{idx}" '
                    f'placeholder="claude-...">{cells}</div>')
        idx += 1
    rows.append('<div class="pref-help">Clear a model name to remove its row.</div>')
    return _shell(key, spec, "".join(rows))


def render(key, value, spec):
    if spec["kind"] == "pairs":
        return _pairs(key, value, spec)
    if spec["kind"] == "table":
        return _table(key, value, spec)
    return _fields(key, value, spec)


def form_for(store, key):
    spec = SPECS.get(key)
    if not spec:
        return None
    return render(key, store.get(key), spec)


def keys_for(section_id):
    from web.user.settings_meta import section_of
    return [k for k in SPECS if section_of(k) == section_id]
