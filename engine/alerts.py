from __future__ import annotations

import time

WINDOW = 7 * 86400


def seen_until(store):
    try:
        return float(store.get("alerts.seen_until", 0) or 0)
    except Exception:
        return 0.0


def friendly(error, stage=None):
    e = (error or "").lower()
    if not e.strip():
        return "The run failed without leaving a reason. Press Retry failed to run it again."
    if "daily spend limit" in e or "spend limit reached" in e:
        return ("The daily AI spending limit has been reached — analysis is paused until "
                "tomorrow. Raise or clear the limit in Settings → AI if this was expected.")
    if "credit balance" in e or "insufficient" in e or "billing" in e:
        return "The Claude API key has run out of credit — top it up, analysis is failing."
    if "rate limit" in e or "429" in e:
        return "The Claude API is rate-limiting us — runs will be slower or fail. It usually clears on its own."
    if "overloaded" in e or "529" in e:
        return "The Claude API is overloaded right now — this clears on its own, press Retry failed in a few minutes."
    if "authentication" in e or "invalid x-api-key" in e or "401" in e or "403" in e:
        return "The Claude API key is wrong or revoked — check Settings → AI."
    if "expected str instance, dict found" in e:
        return ("The controller model answered with structured objects where text was "
                "expected — fixed in the Jul 23 update; press Retry failed to re-run these tenders.")
    if "timeout" in e or "timed out" in e:
        return ("The tender site took too long to answer — usually the portal being slow. "
                "Press Retry failed; if it keeps happening the site may be down.")
    if "get failed" in e or "get text failed" in e or "connection" in e \
            or "name or service not known" in e or "getaddrinfo" in e:
        return ("Couldn't reach the tender site — it was unreachable when we tried. "
                "Press Retry failed once the portal is back up.")
    if "404" in e or "not found" in e:
        return "The tender page is gone (404) — the portal removed or moved it. Nothing to fix on our side."
    if "500" in e or "502" in e or "503" in e or "bad gateway" in e:
        return "The tender site returned a server error — their problem, not ours. Press Retry failed later."
    if "empty prompt" in e or "nothing to send" in e:
        return ("The tender page had no readable text to analyze — often a page that loads "
                "its content with JavaScript. Turn on JS for that site or use an API source.")
    if "json" in e or "expecting value" in e or "decode" in e or "unterminated" in e:
        return ("The model's answer wasn't valid data and couldn't be read — usually a one-off. "
                "Press Retry failed to run it again.")
    if "no such" in e or "database is locked" in e or "sqlite" in e:
        return "A database hiccup interrupted the run — press Retry failed to run it again."
    where = {"extract": "reading the tender documents",
             "applicability": "deciding whether the tender fits us",
             "suppliers": "looking up suppliers",
             "verify": "double-checking the analysis",
             "site_collect": "collecting from the tender site",
             "qualification": "qualifying the tender"}.get((stage or "").lower())
    tail = f" while {where}" if where else ""
    return (f"The run failed{tail} for a reason we don't have a plain-language "
            "explanation for yet — the technical detail is below. Press Retry failed to try again.")


def recent(conn, since=None, limit=100):
    cutoff = since if since is not None else time.time() - WINDOW
    out = []
    for r in conn.execute(
            "SELECT sr.stage_name, sr.error, sr.finished_at, sr.tender_id "
            "FROM stage_runs sr WHERE sr.status='error' AND sr.finished_at > ? "
            "ORDER BY sr.finished_at DESC LIMIT ?", (cutoff, limit)):
        out.append({"kind": "stage", "stage": r["stage_name"], "error": r["error"] or "",
                    "ts": r["finished_at"], "tender_id": r["tender_id"],
                    "hint": friendly(r["error"], r["stage_name"])})
    for r in conn.execute(
            "SELECT tender_id, step, error, finished_at FROM qualify_runs "
            "WHERE status='failed' AND finished_at > ? "
            "ORDER BY finished_at DESC LIMIT ?", (cutoff, limit)):
        out.append({"kind": "qualify", "stage": r["step"] or "qualification",
                    "error": r["error"] or "", "ts": r["finished_at"],
                    "tender_id": r["tender_id"],
                    "hint": friendly(r["error"], r["step"] or "qualification")})
    out.sort(key=lambda a: a["ts"] or 0, reverse=True)
    return out[:limit]


def unseen_count(conn, store):
    try:
        cutoff = max(seen_until(store), time.time() - WINDOW)
        n = conn.execute(
            "SELECT (SELECT COUNT(*) FROM stage_runs WHERE status='error' "
            "AND finished_at > ?) + (SELECT COUNT(*) FROM qualify_runs "
            "WHERE status='failed' AND finished_at > ?)", (cutoff, cutoff)).fetchone()[0]
        return int(n or 0)
    except Exception:
        return 0
