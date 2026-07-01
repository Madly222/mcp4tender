from __future__ import annotations

import time
import uuid

from .contracts import StageContext
from .hashing import content_hash
from .registry import get_stage


def _run_stage_with_retry(stage, ctx, max_retries, backoff, sleep_fn):
    try:
        stage.validate_input(ctx)
    except KeyError as exc:
        return None, "error", str(exc), 0

    attempts = 0
    while True:
        attempts += 1
        try:
            result = stage.run(ctx)
            return result, result.status, result.error, attempts
        except Exception as exc:
            if attempts <= max_retries:
                if backoff:
                    sleep_fn(backoff)
                continue
            return None, "error", str(exc), attempts


def run_pipeline(pipeline_key, store, conn, initial_payload=None,
                 tender_id=None, sleep_fn=time.sleep):
    stages = store.get(pipeline_key)
    if not stages:
        raise KeyError(f"pipeline config empty or missing: {pipeline_key}")

    max_retries = int(store.get("runtime.max_retries", 0))
    backoff = float(store.get("runtime.retry_backoff", 0))

    run_id = uuid.uuid4().hex
    mode = store.get("runtime.mode", "nightly")
    now = time.time()
    conn.execute(
        "INSERT INTO pipeline_runs(run_id, pipeline, mode, status, started_at) "
        "VALUES(?,?,?,?,?)",
        (run_id, pipeline_key, mode, "running", now),
    )
    conn.commit()

    payload = dict(initial_payload or {})
    failed = False

    for stage_name in stages:
        stage = get_stage(stage_name)
        started = time.time()
        input_hash = content_hash(payload)
        ctx = StageContext(payload=payload, config=store, db=conn,
                           run_id=run_id,
                           tender_id=str(tender_id) if tender_id else None)
        result, status, error, attempts = _run_stage_with_retry(
            stage, ctx, max_retries, backoff, sleep_fn)

        tokens = result.metrics.get("tokens", 0) if result else 0
        cost = result.metrics.get("cost", 0) if result else 0
        conn.execute(
            "INSERT INTO stage_runs(run_id, tender_id, stage_name, status, input_hash, "
            "started_at, finished_at, tokens, cost, error) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (run_id, tender_id, stage_name, status, input_hash, started, time.time(),
             tokens, cost, error),
        )

        if status != "ok" or result is None:
            failed = True
            break
        payload = result.payload

    conn.execute(
        "UPDATE pipeline_runs SET status = ?, finished_at = ? WHERE run_id = ?",
        ("failed" if failed else "done", time.time(), run_id),
    )
    conn.commit()
    return {"run_id": run_id, "status": "failed" if failed else "done", "payload": payload}
