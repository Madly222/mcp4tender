from __future__ import annotations

import time

STAGES = ("inbox", "qualified", "in_progress", "submitted", "won", "lost", "skipped")
DECIDED = tuple(s for s in STAGES if s != "inbox")
OPEN_STAGES = ("qualified", "in_progress", "submitted")

LABELS = {
    "inbox": "Undecided",
    "qualified": "Qualified",
    "in_progress": "In progress",
    "submitted": "Submitted",
    "won": "Won",
    "lost": "Lost",
    "skipped": "Skipped",
}

CHIP = {
    "inbox": "", "qualified": "", "in_progress": "acc", "submitted": "ok",
    "won": "ok", "lost": "bad", "skipped": "bad",
}


def account_id(request):
    acct = getattr(request.state, "account", None)
    return acct["id"] if acct is not None else 0


def stage_of(conn, tender_id, acct_id):
    row = conn.execute("SELECT stage FROM tender_work WHERE tender_id=? AND account_id=?",
                       (tender_id, acct_id)).fetchone()
    return row["stage"] if row else "inbox"


def stages_for(conn, tender_ids, acct_id):
    if not tender_ids:
        return {}
    marks = ",".join("?" * len(tender_ids))
    rows = conn.execute(
        f"SELECT tender_id, stage, note, updated_at FROM tender_work "
        f"WHERE account_id=? AND tender_id IN ({marks})",
        (acct_id, *tender_ids)).fetchall()
    return {r["tender_id"]: {"stage": r["stage"], "note": r["note"],
                             "updated_at": r["updated_at"]} for r in rows}


def set_stage(conn, tender_id, acct_id, stage, note=None):
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    if stage == "inbox":
        conn.execute("DELETE FROM tender_work WHERE tender_id=? AND account_id=?",
                     (tender_id, acct_id))
        conn.commit()
        return "inbox"
    conn.execute(
        "INSERT INTO tender_work(tender_id,account_id,stage,note,updated_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(tender_id,account_id) DO UPDATE SET stage=excluded.stage, "
        "note=COALESCE(excluded.note, tender_work.note), updated_at=excluded.updated_at",
        (tender_id, acct_id, stage, note, time.time()))
    conn.commit()
    return stage


def counts(conn, acct_id):
    rows = conn.execute(
        "SELECT stage, COUNT(*) n FROM tender_work WHERE account_id=? GROUP BY stage",
        (acct_id,)).fetchall()
    out = {s: 0 for s in STAGES}
    for r in rows:
        if r["stage"] in out:
            out[r["stage"]] = r["n"]
    return out


def ids_in(conn, acct_id, stages):
    if not stages:
        return []
    marks = ",".join("?" * len(stages))
    rows = conn.execute(
        f"SELECT tender_id FROM tender_work WHERE account_id=? AND stage IN ({marks})",
        (acct_id, *stages)).fetchall()
    return [r["tender_id"] for r in rows]


def decided_ids(conn, acct_id):
    rows = conn.execute("SELECT tender_id FROM tender_work WHERE account_id=?",
                        (acct_id,)).fetchall()
    return {r["tender_id"] for r in rows}
