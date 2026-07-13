from __future__ import annotations

from engine import run_collector
from workflows.analysis import run_all

DEFAULT_SOURCES = ["mtender", "genericweb"]


def _batch(store):
    try:
        return max(1, min(2000, int(store.get("analyze.batch_size", 50) or 50)))
    except (TypeError, ValueError):
        return 50


def run_collect_job(job, store, conn, logger=lambda m: None):
    sources = job.get("sources") or DEFAULT_SOURCES
    total_new = 0
    for src in sources:
        try:
            r = run_collector(src, store, conn, params={"mode": "incremental"})
            got = r.get("new", 0) if isinstance(r, dict) else 0
            status = r.get("status") if isinstance(r, dict) else "?"
            total_new += got or 0
            logger(f"collect {src}: {status} new={got}")
        except Exception as exc:
            logger(f"collect {src} error: {exc}")
    result = {"new": total_new, "analyze": None}
    if job.get("analyze", True):
        try:
            res = run_all(store, conn, limit=_batch(store), scope="all")
            summary = {k: v.get("done", 0) for k, v in res.items()}
            result["analyze"] = summary
            logger(f"analyze: {summary}")
        except Exception as exc:
            logger(f"analyze error: {exc}")
    return result
