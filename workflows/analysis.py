from __future__ import annotations

import time

from engine import process_selected_tenders, process_stored_tenders


def funnel_counts(conn):
    def n(sql, params=()):
        return conn.execute(sql, params).fetchone()[0]
    statuses = {}
    for r in conn.execute("SELECT status, COUNT(*) c FROM tenders GROUP BY status").fetchall():
        statuses[r["status"]] = r["c"]
    total = n("SELECT COUNT(*) FROM tenders")
    triage_buckets = {}
    for r in conn.execute(
        "SELECT verdict, COUNT(*) c FROM verdicts WHERE stage_name='triage' GROUP BY verdict"
    ).fetchall():
        triage_buckets[r["verdict"]] = r["c"]
    appl = {}
    for r in conn.execute(
        "SELECT verdict, COUNT(*) c FROM verdicts WHERE stage_name='applicability' GROUP BY verdict"
    ).fetchall():
        appl[r["verdict"]] = r["c"]
    return {
        "total": total,
        "by_status": statuses,
        "new": statuses.get("new", 0) + statuses.get("updated", 0),
        "triaged": statuses.get("triaged", 0),
        "extracted": statuses.get("extracted", 0),
        "analyzed": statuses.get("analyzed", 0),
        "sourced": statuses.get("sourced", 0),
        "dismissed": n("SELECT COUNT(*) FROM dismissed_tenders"),
        "triage_buckets": triage_buckets,
        "applicability": appl,
    }


def _ids(conn, sql, params):
    return [r["id"] for r in conn.execute(sql, params).fetchall()]


def run_triage(store, conn, limit=None):
    return process_stored_tenders("pipeline.tender_triage", store, conn, limit=limit)


def run_extract(store, conn, limit=None):
    buckets = store.get("extract.buckets", ["relevant", "gray"])
    ph = ",".join("?" for _ in buckets)
    ids = _ids(conn,
               f"SELECT t.id FROM tenders t JOIN verdicts v ON v.tender_id=t.id "
               f"AND v.stage_name='triage' WHERE v.verdict IN ({ph}) "
               f"AND t.status='triaged' ORDER BY v.score DESC"
               + (" LIMIT ?" if limit else ""),
               buckets + ([limit] if limit else []))
    return process_selected_tenders("pipeline.tender_extract", store, conn, ids)


def run_applicability(store, conn, limit=None):
    buckets = store.get("extract.buckets", ["relevant", "gray"])
    ph = ",".join("?" for _ in buckets)
    ids = _ids(conn,
               f"SELECT t.id FROM tenders t JOIN verdicts v ON v.tender_id=t.id "
               f"AND v.stage_name='triage' WHERE v.verdict IN ({ph}) "
               f"AND t.status='extracted' ORDER BY v.score DESC"
               + (" LIMIT ?" if limit else ""),
               buckets + ([limit] if limit else []))
    return process_selected_tenders("pipeline.tender_applicability", store, conn, ids,
                                    next_status="analyzed")


def run_suppliers(store, conn, limit=None):
    verdicts = store.get("suppliers.proceed_verdicts", ["can", "partial"])
    ph = ",".join("?" for _ in verdicts)
    ids = _ids(conn,
               f"SELECT t.id FROM tenders t JOIN verdicts v ON v.tender_id=t.id "
               f"AND v.stage_name='applicability' WHERE v.verdict IN ({ph}) "
               f"AND t.status='analyzed' ORDER BY v.score DESC"
               + (" LIMIT ?" if limit else ""),
               verdicts + ([limit] if limit else []))
    return process_selected_tenders("pipeline.tender_suppliers", store, conn, ids,
                                    next_status="sourced")


def run_all(store, conn):
    return {
        "triage": run_triage(store, conn),
        "extract": run_extract(store, conn),
        "applicability": run_applicability(store, conn),
        "suppliers": run_suppliers(store, conn),
    }


def clear_irrelevant(conn, reject_verdicts=("cannot", "out")):
    ph = ",".join("?" for _ in reject_verdicts)
    rows = conn.execute(
        f"SELECT t.id, t.source, t.external_id FROM tenders t JOIN verdicts v "
        f"ON v.tender_id=t.id AND v.stage_name='applicability' "
        f"WHERE v.verdict IN ({ph})", list(reject_verdicts)).fetchall()
    now = time.time()
    removed = 0
    for r in rows:
        conn.execute(
            "INSERT OR IGNORE INTO dismissed_tenders(external_id, source, reason, dismissed_at) "
            "VALUES(?,?,?,?)", (r["external_id"], r["source"], "irrelevant", now))
        conn.execute("DELETE FROM verdicts WHERE tender_id=?", (r["id"],))
        conn.execute("DELETE FROM tenders WHERE id=?", (r["id"],))
        removed += 1
    conn.commit()
    return removed


def _purge_tender_ids(conn, ids):
    if not ids:
        return
    qs = ",".join("?" * len(ids))
    for tbl in ("verdicts", "extractions", "verifications", "suppliers"):
        conn.execute(f"DELETE FROM {tbl} WHERE tender_id IN ({qs})", ids)
    conn.execute(f"DELETE FROM tenders WHERE id IN ({qs})", ids)


def wipe_collected(conn, source="genericweb", forget=False):
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM tenders WHERE source = ?", (source,)).fetchall()]
    _purge_tender_ids(conn, ids)
    conn.execute("DELETE FROM raw_documents WHERE source = ?", (source,))
    if forget:
        conn.execute("DELETE FROM dismissed_tenders WHERE source = ?", (source,))
    if source == "genericweb":
        conn.execute("UPDATE crawl_state SET next_url=NULL, total_collected=0, "
                     "exhausted=0, note=NULL")
    conn.commit()
    return len(ids)
