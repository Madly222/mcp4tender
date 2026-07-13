from __future__ import annotations

import time

from engine import process_selected_tenders, process_stored_tenders
from workflows.segments import classify_row

SCOPES = ("all", "not_new", "new", "history", "archive")


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


def _scope_ids(conn, store, scope):
    if scope == "all" or store is None:
        return None
    keep = set()
    for r in conn.execute(
            "SELECT id, origin, created_at, normalized_json FROM tenders").fetchall():
        seg = classify_row(r, store)
        if scope == "not_new":
            if seg != "new":
                keep.add(r["id"])
        elif scope == seg:
            keep.add(r["id"])
    return keep


def segment_counts(conn, store):
    out = {s: 0 for s in ("new", "history", "archive")}
    for r in conn.execute(
            "SELECT id, origin, created_at, normalized_json FROM tenders").fetchall():
        out[classify_row(r, store)] += 1
    return out


def _filter(ids, sids):
    return ids if sids is None else [i for i in ids if i in sids]


def _ids(conn, sql, params):
    return [r["id"] for r in conn.execute(sql, params).fetchall()]


def run_triage(store, conn, limit=None, scope="all"):
    sids = _scope_ids(conn, store, scope)
    if sids is None:
        return process_stored_tenders("pipeline.tender_triage", store, conn, limit=limit)
    ids = _ids(conn, "SELECT id FROM tenders WHERE status IN ('new','updated') ORDER BY id"
               + (" LIMIT ?" if limit else ""), ([limit] if limit else []))
    ids = _filter(ids, sids)
    r = process_selected_tenders("pipeline.tender_triage", store, conn, ids,
                                 next_status="triaged")
    r.setdefault("buckets", {})
    return r


def run_extract(store, conn, limit=None, scope="all"):
    sids = _scope_ids(conn, store, scope)
    buckets = store.get("extract.buckets", ["relevant", "gray"])
    ph = ",".join("?" for _ in buckets)
    ids = _ids(conn,
               f"SELECT t.id FROM tenders t JOIN verdicts v ON v.tender_id=t.id "
               f"AND v.stage_name='triage' WHERE v.verdict IN ({ph}) "
               f"AND t.status='triaged' ORDER BY v.score DESC"
               + (" LIMIT ?" if limit else ""),
               buckets + ([limit] if limit else []))
    return process_selected_tenders("pipeline.tender_extract", store, conn, _filter(ids, sids))


def run_applicability(store, conn, limit=None, scope="all"):
    sids = _scope_ids(conn, store, scope)
    buckets = store.get("extract.buckets", ["relevant", "gray"])
    ph = ",".join("?" for _ in buckets)
    ids = _ids(conn,
               f"SELECT t.id FROM tenders t JOIN verdicts v ON v.tender_id=t.id "
               f"AND v.stage_name='triage' WHERE v.verdict IN ({ph}) "
               f"AND t.status='extracted' ORDER BY v.score DESC"
               + (" LIMIT ?" if limit else ""),
               buckets + ([limit] if limit else []))
    return process_selected_tenders("pipeline.tender_applicability", store, conn,
                                    _filter(ids, sids), next_status="analyzed")


def run_suppliers(store, conn, limit=None, scope="all"):
    sids = _scope_ids(conn, store, scope)
    verdicts = store.get("suppliers.proceed_verdicts", ["can", "partial"])
    ph = ",".join("?" for _ in verdicts)
    ids = _ids(conn,
               f"SELECT t.id FROM tenders t JOIN verdicts v ON v.tender_id=t.id "
               f"AND v.stage_name='applicability' WHERE v.verdict IN ({ph}) "
               f"AND t.status='analyzed' ORDER BY v.score DESC"
               + (" LIMIT ?" if limit else ""),
               verdicts + ([limit] if limit else []))
    return process_selected_tenders("pipeline.tender_suppliers", store, conn,
                                    _filter(ids, sids), next_status="sourced")


def run_all(store, conn, limit=None, scope="all"):
    return {
        "triage": run_triage(store, conn, limit=limit, scope=scope),
        "extract": run_extract(store, conn, limit=limit, scope=scope),
        "applicability": run_applicability(store, conn, limit=limit, scope=scope),
        "suppliers": run_suppliers(store, conn, limit=limit, scope=scope),
    }


def clear_irrelevant(conn, reject_verdicts=("cannot", "out"), store=None, scope="all"):
    sids = _scope_ids(conn, store, scope)
    ph = ",".join("?" for _ in reject_verdicts)
    rows = conn.execute(
        f"SELECT t.id, t.source, t.external_id FROM tenders t JOIN verdicts v "
        f"ON v.tender_id=t.id AND v.stage_name='applicability' "
        f"WHERE v.verdict IN ({ph})", list(reject_verdicts)).fetchall()
    now = time.time()
    removed = 0
    for r in rows:
        if sids is not None and r["id"] not in sids:
            continue
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


def dedupe_mtender(conn):
    import json as _json
    from workflows.collectors.mtender import base_ocid
    rows = conn.execute(
        "SELECT id, external_id, normalized_json, status FROM tenders "
        "WHERE source='mtender'").fetchall()
    groups = {}
    for r in rows:
        groups.setdefault(base_ocid(r["external_id"]), []).append(r)

    def richness(r):
        try:
            nj = _json.loads(r["normalized_json"] or "{}")
        except Exception:
            nj = {}
        score = (1 if nj.get("title") else 0) + (1 if nj.get("value_amount") else 0)
        return (score, 1 if r["status"] not in ("new", "failed") else 0, r["id"])

    removed = 0
    for base, grp in groups.items():
        if len(grp) < 2:
            continue
        grp.sort(key=richness, reverse=True)
        keeper, dupes = grp[0], [r["id"] for r in grp[1:]]
        _purge_tender_ids(conn, dupes)
        conn.execute("UPDATE tenders SET external_id=? WHERE id=?", (base, keeper["id"]))
        removed += len(dupes)
    conn.commit()
    return removed


def dedupe_documents_db(conn, source="mtender"):
    import json as _json
    from workflows.collectors.mtender import dedupe_documents
    rows = conn.execute(
        "SELECT id, normalized_json FROM tenders WHERE source=?", (source,)).fetchall()
    changed = 0
    removed = 0
    for r in rows:
        try:
            nj = _json.loads(r["normalized_json"] or "{}")
        except Exception:
            continue
        docs = nj.get("documents")
        if not isinstance(docs, list) or len(docs) < 2:
            continue
        deduped = dedupe_documents(docs)
        if len(deduped) < len(docs):
            nj["documents"] = deduped
            conn.execute("UPDATE tenders SET normalized_json=? WHERE id=?",
                         (_json.dumps(nj, ensure_ascii=False), r["id"]))
            changed += 1
            removed += len(docs) - len(deduped)
    conn.commit()
    return {"tenders_changed": changed, "documents_removed": removed}


_STAGE_ORDER = ["triage", "extract", "applicability", "suppliers"]
_STAGE_PREV = {"triage": "new", "extract": "triaged",
               "applicability": "extracted", "suppliers": "analyzed"}
_STAGE_FORWARD = {
    "triage": ("triaged", "extracted", "analyzed", "sourced", "failed"),
    "extract": ("extracted", "analyzed", "sourced"),
    "applicability": ("analyzed", "sourced"),
    "suppliers": ("sourced",),
}


def _idcond(ids):
    if ids is None:
        return "", ()
    qs = ",".join("?" * len(ids))
    return f" AND tender_id IN ({qs})", tuple(ids)


def _delete_stage_data(conn, stage, ids=None):
    c, p = _idcond(ids)
    if stage == "triage":
        conn.execute(f"DELETE FROM verdicts WHERE stage_name='triage'{c}", p)
        conn.execute(f"DELETE FROM verifications WHERE stage='triage'{c}", p)
    elif stage == "extract":
        conn.execute(f"DELETE FROM extractions WHERE 1=1{c}", p)
        conn.execute(f"DELETE FROM verifications WHERE stage='extract'{c}", p)
    elif stage == "applicability":
        conn.execute(f"DELETE FROM verdicts WHERE stage_name='applicability'{c}", p)
        conn.execute(
            f"DELETE FROM verifications WHERE stage IN ('applicability','applicability_verify'){c}",
            p)
    elif stage == "suppliers":
        conn.execute(f"DELETE FROM suppliers WHERE 1=1{c}", p)


def clear_stage(conn, stage, store=None, scope="all"):
    if stage not in _STAGE_ORDER:
        return 0
    sids = _scope_ids(conn, store, scope)
    ids_list = None if sids is None else list(sids)
    idx = _STAGE_ORDER.index(stage)
    for st in _STAGE_ORDER[idx:]:
        _delete_stage_data(conn, st, ids_list)
    forward = _STAGE_FORWARD[stage]
    prev = _STAGE_PREV[stage]
    ph = ",".join("?" * len(forward))
    if ids_list is None:
        n = conn.execute(f"SELECT COUNT(*) FROM tenders WHERE status IN ({ph})",
                         forward).fetchone()[0]
        conn.execute(f"UPDATE tenders SET status=?, updated_at=? WHERE status IN ({ph})",
                     (prev, time.time(), *forward))
    elif not ids_list:
        conn.commit()
        return 0
    else:
        qs = ",".join("?" * len(ids_list))
        n = conn.execute(
            f"SELECT COUNT(*) FROM tenders WHERE status IN ({ph}) AND id IN ({qs})",
            (*forward, *ids_list)).fetchone()[0]
        conn.execute(
            f"UPDATE tenders SET status=?, updated_at=? WHERE status IN ({ph}) AND id IN ({qs})",
            (prev, time.time(), *forward, *ids_list))
    conn.commit()
    return n


def requeue_failed(conn, store=None, scope="all"):
    sids = _scope_ids(conn, store, scope)
    rows = conn.execute("SELECT id FROM tenders WHERE status='failed'").fetchall()
    n = 0
    for r in rows:
        if sids is not None and r["id"] not in sids:
            continue
        has_triage = conn.execute(
            "SELECT 1 FROM verdicts WHERE tender_id=? AND stage_name='triage'",
            (r["id"],)).fetchone()
        conn.execute("UPDATE tenders SET status=?, updated_at=? WHERE id=?",
                     ("triaged" if has_triage else "new", time.time(), r["id"]))
        n += 1
    conn.commit()
    return n


def reset_analysis(conn, store=None, scope="all"):
    sids = _scope_ids(conn, store, scope)
    if sids is None:
        n = conn.execute(
            "SELECT COUNT(*) FROM tenders WHERE status != 'new'").fetchone()[0]
        for tbl in ("verdicts", "extractions", "verifications", "suppliers"):
            conn.execute(f"DELETE FROM {tbl}")
        conn.execute("UPDATE tenders SET status='new', updated_at=? WHERE status != 'new'",
                     (time.time(),))
        conn.commit()
        return n
    target = [r["id"] for r in conn.execute(
        "SELECT id FROM tenders WHERE status != 'new'").fetchall() if r["id"] in sids]
    if not target:
        conn.commit()
        return 0
    qs = ",".join("?" * len(target))
    for tbl in ("verdicts", "extractions", "verifications", "suppliers"):
        conn.execute(f"DELETE FROM {tbl} WHERE tender_id IN ({qs})", target)
    conn.execute(f"UPDATE tenders SET status='new', updated_at=? WHERE id IN ({qs})",
                 (time.time(), *target))
    conn.commit()
    return len(target)


def wipe_collected(conn, source="genericweb", forget=False, store=None, scope="all"):
    sids = _scope_ids(conn, store, scope)
    base_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM tenders WHERE source = ?", (source,)).fetchall()]
    ids = base_ids if sids is None else [i for i in base_ids if i in sids]
    _purge_tender_ids(conn, ids)
    if sids is None:
        conn.execute("DELETE FROM raw_documents WHERE source = ?", (source,))
        if forget:
            conn.execute("DELETE FROM dismissed_tenders WHERE source = ?", (source,))
        if source == "genericweb":
            conn.execute("UPDATE crawl_state SET next_url=NULL, total_collected=0, "
                         "exhausted=0, note=NULL")
    conn.commit()
    return len(ids)
