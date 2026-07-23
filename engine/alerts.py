from __future__ import annotations

import time

WINDOW = 7 * 86400


def seen_until(store):
    try:
        return float(store.get("alerts.seen_until", 0) or 0)
    except Exception:
        return 0.0


def friendly(error):
    e = (error or "").lower()
    if "credit balance" in e or "insufficient" in e or "billing" in e:
        return "The Claude API key has run out of credit — top it up, analysis is failing."
    if "rate limit" in e or "429" in e:
        return "The Claude API is rate-limiting us — runs will be slower or fail."
    if "overloaded" in e or "529" in e:
        return "The Claude API is overloaded right now — retry later."
    if "authentication" in e or "invalid x-api-key" in e or "401" in e:
        return "The Claude API key is wrong or revoked — check Settings → AI."
    if "expected str instance, dict found" in e:
        return ("The controller model answered with structured objects where text was "
                "expected — fixed in the Jul 23 update; press Retry failed on Analyze "
                "to re-run these tenders.")
    return None


def recent(conn, since=None, limit=100):
    cutoff = since if since is not None else time.time() - WINDOW
    out = []
    for r in conn.execute(
            "SELECT sr.stage_name, sr.error, sr.finished_at, sr.tender_id "
            "FROM stage_runs sr WHERE sr.status='error' AND sr.finished_at > ? "
            "ORDER BY sr.finished_at DESC LIMIT ?", (cutoff, limit)):
        out.append({"kind": "stage", "stage": r["stage_name"], "error": r["error"] or "",
                    "ts": r["finished_at"], "tender_id": r["tender_id"],
                    "hint": friendly(r["error"])})
    for r in conn.execute(
            "SELECT tender_id, step, error, finished_at FROM qualify_runs "
            "WHERE status='failed' AND finished_at > ? "
            "ORDER BY finished_at DESC LIMIT ?", (cutoff, limit)):
        out.append({"kind": "qualify", "stage": r["step"] or "qualification",
                    "error": r["error"] or "", "ts": r["finished_at"],
                    "tender_id": r["tender_id"], "hint": friendly(r["error"])})
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
