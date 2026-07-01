from __future__ import annotations

import json
import time

from .hashing import content_hash
from .runner import run_pipeline


def _get_tender(conn, source, external_id):
    return conn.execute(
        "SELECT id, content_hash, status FROM tenders WHERE source = ? AND external_id = ?",
        (source, external_id),
    ).fetchone()


def _upsert_tender(conn, source, external_id, chash, normalized):
    now = time.time()
    existing = _get_tender(conn, source, external_id)
    if existing is None:
        cur = conn.execute(
            "INSERT INTO tenders(source, external_id, content_hash, normalized_json, "
            "status, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            (source, external_id, chash, json.dumps(normalized, ensure_ascii=False),
             "processing", now, now),
        )
        conn.commit()
        return cur.lastrowid
    conn.execute(
        "UPDATE tenders SET content_hash = ?, normalized_json = ?, status = ?, updated_at = ? "
        "WHERE id = ?",
        (chash, json.dumps(normalized, ensure_ascii=False), "processing", now, existing["id"]),
    )
    conn.commit()
    return existing["id"]


def _set_status(conn, tender_id, status):
    conn.execute(
        "UPDATE tenders SET status = ?, updated_at = ? WHERE id = ?",
        (status, time.time(), tender_id),
    )
    conn.commit()


def process_one(pipeline_key, item, store, conn, force=False, sleep_fn=time.sleep):
    source = item["source"]
    external_id = item["external_id"]
    content = item.get("content", item)
    chash = content_hash(content)

    existing = _get_tender(conn, source, external_id)
    if not force and existing is not None and existing["content_hash"] == chash \
            and existing["status"] == "done":
        return {"status": "skipped_dedup", "tender_id": existing["id"], "run_id": None}

    tender_id = _upsert_tender(conn, source, external_id, chash, content)
    result = run_pipeline(pipeline_key, store, conn,
                          initial_payload={"tender": content, "tender_id": tender_id},
                          tender_id=tender_id, sleep_fn=sleep_fn)
    _set_status(conn, tender_id, "done" if result["status"] == "done" else "failed")
    return {"status": result["status"], "tender_id": tender_id, "run_id": result["run_id"]}


def process_batch(pipeline_key, items, store, conn, force=False, sleep_fn=time.sleep):
    summary = {"total": len(items), "done": 0, "failed": 0, "skipped_dedup": 0, "results": []}
    for item in items:
        r = process_one(pipeline_key, item, store, conn, force=force, sleep_fn=sleep_fn)
        summary[r["status"]] = summary.get(r["status"], 0) + 1
        summary["results"].append(r)
    return summary


def process_stored_tenders(pipeline_key, store, conn, statuses=("new", "updated"),
                           next_status="triaged", limit=None, sleep_fn=time.sleep):
    placeholders = ",".join("?" for _ in statuses)
    query = (f"SELECT id, normalized_json FROM tenders WHERE status IN ({placeholders}) "
             "ORDER BY id")
    params = list(statuses)
    if limit:
        query += " LIMIT ?"
        params.append(int(limit))
    rows = conn.execute(query, params).fetchall()

    summary = {"total": len(rows), "done": 0, "failed": 0, "buckets": {}}
    for row in rows:
        try:
            normalized = json.loads(row["normalized_json"]) if row["normalized_json"] else {}
        except json.JSONDecodeError:
            normalized = {}
        result = run_pipeline(pipeline_key, store, conn,
                              initial_payload={"tender": normalized, "tender_id": row["id"]},
                              tender_id=row["id"], sleep_fn=sleep_fn)
        if result["status"] == "done":
            summary["done"] += 1
            bucket = (result["payload"].get("triage") or {}).get("bucket")
            if bucket:
                summary["buckets"][bucket] = summary["buckets"].get(bucket, 0) + 1
            _set_status(conn, row["id"], next_status)
        else:
            summary["failed"] += 1
            _set_status(conn, row["id"], "failed")
    return summary


def process_selected_tenders(pipeline_key, store, conn, tender_ids,
                             next_status="extracted", sleep_fn=time.sleep):
    summary = {"total": len(tender_ids), "done": 0, "failed": 0}
    for tid in tender_ids:
        row = conn.execute(
            "SELECT normalized_json FROM tenders WHERE id = ?", (tid,)).fetchone()
        if not row:
            continue
        try:
            normalized = json.loads(row["normalized_json"]) if row["normalized_json"] else {}
        except json.JSONDecodeError:
            normalized = {}
        result = run_pipeline(pipeline_key, store, conn,
                              initial_payload={"tender": normalized, "tender_id": tid},
                              tender_id=tid, sleep_fn=sleep_fn)
        if result["status"] == "done":
            summary["done"] += 1
            _set_status(conn, tid, next_status)
        else:
            summary["failed"] += 1
    return summary
