from __future__ import annotations

import time

from engine import health
from engine.secrets import set_api_key


class SettingsError(Exception):
    pass


def lines(text):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def numval(v, default):
    try:
        f = float(v)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return default


def save_company(form, store, actor="web"):
    p = dict(store.get("capabilities.profile", {}) or {})
    p["company"] = (form.get("company") or "").strip()
    p["country"] = (form.get("country") or "").strip()
    p["experience_years"] = int(numval(form.get("experience_years"), 0))
    p["eu_arm"] = (form.get("eu_arm") or "").strip()
    p["verticals"] = lines(form.get("verticals"))
    p["services"] = lines(form.get("services"))
    p["certifications"] = lines(form.get("certifications"))
    p["references"] = lines(form.get("references"))
    p["partner_network"] = lines(form.get("partner_network"))
    p["notes"] = (form.get("notes") or "").strip()
    vendors = {}
    for ln in lines(form.get("vendors")):
        k, _sep, v = ln.partition("=")
        if k.strip():
            vendors[k.strip()] = v.strip()
    p["vendor_partnerships"] = vendors
    store.set("capabilities.profile", p, actor=actor, note="edit company profile")
    return "company saved"


def save_keywords(form, store, actor="web"):
    weights = {}
    i = 0
    while f"kw{i}" in form:
        k = (form.get(f"kw{i}") or "").strip().lower()
        w = form.get(f"wt{i}")
        i += 1
        if not k or w in (None, ""):
            continue
        try:
            wv = float(w)
        except (TypeError, ValueError):
            continue
        weights[k] = int(wv) if wv == int(wv) else wv
    if not weights:
        raise SettingsError("no keywords to save")
    store.set("triage.keyword_weights", weights, actor=actor, note="edit keywords")
    return f"saved {len(weights)} keyword(s)"


def save_apikey(form):
    value = (form.get("api_key") or "").strip()
    if not value:
        return "key unchanged"
    if not value.startswith("sk-"):
        raise SettingsError("that does not look like an API key (expected sk-...)")
    path = set_api_key(value)
    return f"key saved to {path} and applied without restart"


def run_key_test(form, store, actor="web"):
    typed = (form.get("api_key") or "").strip()
    model = (store.get("llm.models", {}) or {}).get("default")
    r = health.check_api_key(model=model, key=typed or None)
    store.set("llm.last_key_check",
              {"status": r["status"], "code": r.get("code"), "detail": r.get("detail"),
               "raw": r.get("raw"), "model": model, "at": time.time()},
              actor=actor, note="test key result")
    if r["status"] == "ok":
        return "key works"
    raise SettingsError(f"{r.get('code')}: {r.get('detail')}")


DAYS = [(0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri"), (5, "Sat"), (6, "Sun")]
KNOWN_SOURCES = [("mtender", "MTender (no tokens)"),
                 ("genericweb", "Generic web (uses tokens)")]
_TIME_RE = __import__("re").compile(r"^(\d{1,2}):([0-5]\d)$")


def collect_job(store):
    for j in store.get("schedule.jobs", []) or []:
        if isinstance(j, dict) and j.get("kind") == "collect":
            return j
    return {"kind": "collect", "sources": ["mtender", "genericweb"], "days": [],
            "at": ["06:00", "18:00"], "analyze": True, "enabled": False}


def other_jobs(store):
    return [j for j in (store.get("schedule.jobs", []) or [])
            if not (isinstance(j, dict) and j.get("kind") == "collect")]


def parse_times(raw):
    import re
    out = []
    for part in re.split(r"[,\s]+", raw or ""):
        part = part.strip()
        m = _TIME_RE.match(part) if part else None
        if not m or int(m.group(1)) > 23:
            continue
        norm = "%02d:%s" % (int(m.group(1)), m.group(2))
        if norm not in out:
            out.append(norm)
    return sorted(out)[:24]


def save_schedule(form, store, actor="web"):
    tz = (form.get("timezone") or "").strip()
    enabled = form.get("enabled") == "on"
    days = [i for i, _ in DAYS if form.get(f"day_{i}") == "on"]
    times = parse_times(form.get("times") or "")
    sources = [k for k, _ in KNOWN_SOURCES if form.get(f"src_{k}") == "on"] or \
        [k for k, _ in KNOWN_SOURCES]
    analyze = form.get("analyze") == "on"

    warn = ""
    if tz:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(tz)
        except Exception:
            warn = f" (warning: timezone {tz} not recognised, using server local time)"
    if enabled and not times:
        warn += " (warning: no valid run times, schedule will not fire)"

    job = {"kind": "collect", "sources": sources, "days": days,
           "at": times, "analyze": analyze, "enabled": enabled}
    store.set("schedule.timezone", tz, actor=actor, note="schedule.timezone")
    store.set("schedule.jobs", other_jobs(store) + [job], actor=actor,
              note="schedule collect job")
    return "schedule saved" + warn


def catalog_currencies(store):
    out = {"MDL"}
    for k in (store.get("suppliers.fx_rates", {}) or {}):
        a, _sep, b = str(k).partition("->")
        out.add(a.strip().upper())
        out.add(b.strip().upper())
    return sorted(c for c in out if c)


def _slug(text, taken):
    import re
    base = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:40] or "item"
    slug = base
    n = 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    return slug


def _rate_known(cur, rates, target="MDL"):
    cur = (cur or "").upper()
    if not cur or cur == target:
        return True
    return f"{cur}->{target}" in rates or f"{target}->{cur}" in rates


def save_catalog(form, store, actor="web"):
    rates = store.get("suppliers.fx_rates", {}) or {}
    items = []
    taken = set()
    unrated = set()
    i = 0
    while f"cat{i}_denumire" in form:
        idx = i
        i += 1
        if form.get(f"cat{idx}_remove") == "on":
            continue
        name = (form.get(f"cat{idx}_denumire") or "").strip()
        if not name:
            continue
        cur = (form.get(f"cat{idx}_currency") or "MDL").strip().upper()
        item_id = (form.get(f"cat{idx}_id") or "").strip() or _slug(name, taken)
        if item_id in taken:
            item_id = _slug(name, taken)
        taken.add(item_id)
        if not _rate_known(cur, rates):
            unrated.add(cur)
        items.append({
            "id": item_id,
            "supplier": (form.get(f"cat{idx}_supplier") or "").strip(),
            "denumire": name,
            "model": (form.get(f"cat{idx}_model") or "").strip(),
            "vendor": (form.get(f"cat{idx}_vendor") or "").strip(),
            "price": numval(form.get(f"cat{idx}_price"), 0),
            "currency": cur,
            "specs": (form.get(f"cat{idx}_specs") or "").strip(),
        })
    store.set("suppliers.catalog", items, actor=actor, note="edit supplier catalog")
    msg = f"saved {len(items)} catalog item(s)"
    if unrated:
        msg += (" (warning: no exchange rate for " + ", ".join(sorted(unrated))
                + " - those line costs cannot be converted and the margin will be wrong)")
    return msg


def save_pairs(form, store, key, numeric, actor="web"):
    out = {}
    i = 0
    while f"k{i}" in form:
        name = (form.get(f"k{i}") or "").strip()
        raw = form.get(f"v{i}")
        i += 1
        if not name or raw in (None, ""):
            continue
        if numeric:
            try:
                out[name] = numval(raw, None)
            except Exception:
                continue
            if out[name] is None:
                del out[name]
        else:
            out[name] = str(raw).strip()
    if not out:
        raise SettingsError("nothing to save — at least one line is required")
    store.set(key, out, actor=actor, note=f"edit {key}")
    return f"saved {len(out)} line(s) in {key}"


def save_fields(form, store, key, actor="web"):
    current = dict(store.get(key, {}) or {})
    out = {}
    for sub, old in current.items():
        raw = form.get("f_" + sub)
        if isinstance(old, bool):
            out[sub] = raw == "on"
        elif isinstance(old, int):
            out[sub] = int(numval(raw, old))
        elif isinstance(old, float):
            out[sub] = float(numval(raw, old))
        elif isinstance(old, list):
            out[sub] = [s.strip() for s in str(raw or "").split(",") if s.strip()]
        else:
            out[sub] = (raw if raw is not None else old) or ""
    store.set(key, out, actor=actor, note=f"edit {key}")
    return f"saved {key}"


def save_table(form, store, key, cols, actor="web"):
    out = {}
    i = 0
    while f"k{i}" in form:
        name = (form.get(f"k{i}") or "").strip()
        idx = i
        i += 1
        if not name:
            continue
        out[name] = {c: numval(form.get(f"c{idx}_{c}"), 0) for c in cols}
    if not out:
        raise SettingsError("nothing to save — at least one row is required")
    store.set(key, out, actor=actor, note=f"edit {key}")
    return f"saved {len(out)} row(s) in {key}"


def save_notify_secrets(form):
    from engine.secrets import write_env_var
    from workflows.notify import SMTP_PASSWORD_VAR, TG_TOKEN_VAR
    saved = []
    smtp = (form.get("smtp_password") or "").strip()
    tok = (form.get("tg_token") or "").strip()
    if smtp:
        write_env_var(SMTP_PASSWORD_VAR, smtp)
        saved.append("mail password")
    if tok:
        if ":" not in tok:
            raise SettingsError("that does not look like a bot token "
                                "(expected 123456:ABC-DEF...)")
        write_env_var(TG_TOKEN_VAR, tok)
        saved.append("bot token")
    if not saved:
        return "nothing to save — both fields were empty"
    return "saved " + " and ".join(saved)


def run_send_test(store, conn):
    from workflows import notify
    on = notify.channels_on(store)
    if not on["email"] and not on["telegram"]:
        raise SettingsError("turn on email or Telegram below first, then test")
    row = conn.execute("SELECT id FROM tenders ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        raise SettingsError("collect at least one tender first — the test sends a real one")
    res = notify.notify_tender(store, conn, row["id"])
    return f"test send: {res['detail']}"

