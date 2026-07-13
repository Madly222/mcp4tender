from __future__ import annotations

import re
import time

from engine.secrets import get_api_key, key_source

OK = "ok"
WARN = "warn"
FAIL = "fail"

BLOCKING_CODES = ("credit", "limit", "auth", "model", "network")

STAGE_KEYS = ("default", "extract", "ocr", "verify", "applicability",
              "applicability_gray", "suppliers")

CONSOLE_URL = "https://console.anthropic.com/settings/billing"


def spend(conn, days=1):
    since = time.time() - days * 86400
    row = conn.execute(
        "SELECT COALESCE(SUM(cost),0), COALESCE(SUM(tokens),0), COUNT(*) "
        "FROM stage_runs WHERE started_at >= ?", (since,)).fetchone()
    return {"cost": row[0] or 0.0, "tokens": row[1] or 0, "runs": row[2] or 0}


def spend_by_stage(conn, days=30):
    since = time.time() - days * 86400
    rows = conn.execute(
        "SELECT stage_name, COALESCE(SUM(cost),0) c, COALESCE(SUM(tokens),0) t "
        "FROM stage_runs WHERE started_at >= ? GROUP BY stage_name "
        "ORDER BY c DESC", (since,)).fetchall()
    return [{"stage": r[0], "cost": r[1], "tokens": r[2]} for r in rows]


def _regain_date(msg):
    m = re.search(r"regain access on ([0-9]{4}-[0-9]{2}-[0-9]{2}(?: at [0-9:]+ ?[A-Z]*)?)", msg)
    return m.group(1) if m else None


def classify_api_error(exc):
    msg = str(exc)
    low = msg.lower()
    if "usage limit" in low or "specified api usage" in low or "spend limit" in low:
        when = _regain_date(msg)
        tail = f" Access returns on {when}." if when else ""
        return ("limit", "A spending/usage limit set on the Anthropic account has been reached, "
                         "so the API is refusing calls." + tail + " Raise or remove the limit in "
                         "the Anthropic Console (Settings -> Limits), or wait for it to reset.")
    if ("credit balance is too low" in low or "insufficient" in low or "billing" in low
            or "out of credit" in low):
        return ("credit", "Out of credits. Anthropic returns this same message for three "
                          "different causes: credits really are exhausted, the model needs a "
                          "higher usage tier, or the key is stale. Top up or mint a new key.")
    if ("authentication" in low or "invalid x-api-key" in low or "401" in low
            or "permission" in low or "403" in low):
        return ("auth", "The API key is rejected. Create a new one in the Anthropic Console.")
    if "rate limit" in low or "429" in low or "overloaded" in low or "529" in low:
        return ("rate", "Rate limited or the API was overloaded. The key works; it will "
                        "succeed on retry.")
    if "not_found" in low or "404" in low or "does not exist" in low:
        return ("model", "The model name is not recognised. Fix the model IDs in the Models "
                         "section below.")
    if "timeout" in low or "connection" in low or "network" in low or "getaddrinfo" in low:
        return ("network", "The server could not reach api.anthropic.com. Check outbound "
                           "network and DNS.")
    if "empty prompt" in low:
        return ("prompt", "The engine tried to send an empty prompt. Usually means the "
                          "tender had no readable document text.")
    return ("unknown", msg[:300])


def check_api_key(model="claude-haiku-4-5-20251001", client=None, key=None, env_path=None):
    key = key or get_api_key(env_path)
    if not key:
        return {"status": FAIL, "code": "missing", "detail": "No API key configured."}
    if client is None:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
        except Exception as exc:
            return {"status": FAIL, "code": "sdk", "detail": str(exc)[:200]}
    try:
        client.messages.create(model=model, max_tokens=1,
                               messages=[{"role": "user", "content": "hi"}])
        return {"status": OK, "code": "valid", "detail": "Key works."}
    except Exception as exc:
        code, detail = classify_api_error(exc)
        return {"status": FAIL, "code": code, "detail": detail, "raw": str(exc)[:300]}


def provider_in_use(store):
    try:
        from engine.llm import select_provider
        return select_provider(store).name
    except Exception as exc:
        return "unknown (%s)" % str(exc)[:60]


def recent_llm_errors(conn, days=7, limit=8):
    since = time.time() - days * 86400
    rows = conn.execute(
        "SELECT stage_name, started_at, error, tender_id FROM stage_runs "
        "WHERE error IS NOT NULL AND error != '' AND started_at >= ? "
        "ORDER BY started_at DESC LIMIT ?", (since, limit)).fetchall()
    out = []
    for r in rows:
        code, fix = classify_api_error(r[2])
        out.append({"stage": r[0], "at": r[1], "raw": str(r[2])[:300],
                    "tender_id": r[3], "code": code, "fix": fix})
    return out


def error_counts(conn, days=7):
    since = time.time() - days * 86400
    rows = conn.execute(
        "SELECT error FROM stage_runs WHERE error IS NOT NULL AND error != '' "
        "AND started_at >= ?", (since,)).fetchall()
    counts = {}
    for r in rows:
        code = classify_api_error(r[0])[0]
        counts[code] = counts.get(code, 0) + 1
    return counts


def llm_status(conn, store, env_path=None, days=7):
    provider = provider_in_use(store)
    errs = recent_llm_errors(conn, days=days, limit=1)
    last = errs[0] if errs else None
    counts = error_counts(conn, days=days)
    if provider == "stub":
        state, why = FAIL, "Stub provider active: every LLM stage returns fake text."
    elif last and last["code"] in BLOCKING_CODES:
        state, why = FAIL, last["fix"]
    elif counts:
        state, why = WARN, "Some LLM calls failed recently."
    else:
        state, why = OK, "No LLM errors in the last %d days." % days
    return {"provider": provider, "key_source": key_source(env_path), "state": state,
            "why": why, "last_error": last, "counts": counts}


def _add(issues, level, title, fix):
    issues.append({"level": level, "title": title, "fix": fix})


def collect_issues(conn, store, env_path=None):
    issues = []

    src = key_source(env_path)
    provider = store.get("llm.provider", "auto")
    if src == "missing" and provider != "stub":
        _add(issues, FAIL, "No ANTHROPIC_API_KEY - the engine silently uses a stub provider",
             "LLM stages return fake text (STUB_RESPONSE) instead of failing. "
             "Paste a key in the API key box below.")

    status = llm_status(conn, store, env_path)
    last = status["last_error"]
    if last and last["code"] in BLOCKING_CODES:
        _add(issues, FAIL, "LLM calls are failing: " + last["code"], last["fix"])

    models = store.get("llm.models", {}) or {}
    pricing = store.get("llm.pricing", {}) or {}
    default_model = models.get("default")
    for stage in STAGE_KEYS:
        name = models.get(stage) or default_model
        if name and name not in pricing:
            _add(issues, WARN, f"Model '{name}' ({stage}) has no entry in llm.pricing",
                 "Token cost for this stage is recorded as 0, so spend numbers understate reality.")
            break

    mt = store.get("sources.mtender", {}) or {}
    gw = store.get("sources.genericweb", {}) or {}
    sites = store.get("sites.tenders", []) or []
    if not mt.get("enabled"):
        _add(issues, WARN, "Source 'mtender' is disabled",
             "Scheduled collection will skip it. Enable sources.mtender.enabled in Config.")
    if sites and not gw.get("enabled"):
        _add(issues, WARN, f"{len(sites)} site(s) configured but source 'genericweb' is disabled",
             "Scheduled collection will skip every website. "
             "Enable sources.genericweb.enabled in Config.")

    jobs = store.get("schedule.jobs", []) or []
    collect_jobs = [j for j in jobs if isinstance(j, dict) and j.get("kind") == "collect"]
    job = collect_jobs[0] if collect_jobs else None
    if job and job.get("enabled"):
        if not job.get("at"):
            _add(issues, FAIL, "Scheduled collection is on, but no run times are set",
                 "It will never fire. Add times on the Schedule page.")
        tz = (store.get("schedule.timezone", "") or "").strip()
        if not tz:
            _add(issues, WARN, "No timezone set - the schedule uses server local time",
                 "Set schedule.timezone (e.g. Europe/Chisinau) on the Schedule page.")
        else:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(tz)
            except Exception:
                _add(issues, FAIL, f"Timezone '{tz}' is not recognised",
                     "The schedule falls back to server local time. Use an IANA name.")
        if job.get("analyze"):
            pending = conn.execute(
                "SELECT COUNT(*) FROM tenders WHERE status IN ('new','updated')").fetchone()[0]
            batch = store.get("analyze.batch_size", 50)
            runs = len(job.get("at") or [])
            if pending > 200:
                _add(issues, WARN,
                     f"{pending} tenders await analysis and auto-analyse is on "
                     f"(batch {batch} x {runs} runs/day)",
                     "Each scheduled run reads documents through the model. "
                     "Lower analyze.batch_size or clear the backlog manually first.")

    failed = conn.execute("SELECT COUNT(*) FROM tenders WHERE status='failed'").fetchone()[0]
    if failed:
        _add(issues, WARN, f"{failed} tender(s) in status 'failed'",
             "Use 'Retry failed' on the Analyze page once the cause is fixed.")

    return issues
