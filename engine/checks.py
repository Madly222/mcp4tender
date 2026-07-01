from __future__ import annotations

import json
import time

from .registry import all_stages

REQUIRED_TABLES = {
    "raw_documents", "tenders", "pipeline_runs", "stage_runs",
    "verdicts", "configs", "config_meta", "audit_log",
}


def run_startup_checks(conn, store):
    results = []

    try:
        conn.execute("SELECT 1").fetchone()
        results.append(("db", "ok", ""))
    except Exception as exc:
        results.append(("db", "fail", str(exc)))

    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    have = {r[0] for r in rows}
    missing = REQUIRED_TABLES - have
    results.append(("schema", "ok" if not missing else "fail",
                    "missing: " + ",".join(sorted(missing)) if missing else ""))

    cfg = store.all()
    results.append(("configs", "ok" if cfg else "warn", f"{len(cfg)} keys"))

    stages = all_stages()
    results.append(("stages", "ok" if stages else "warn", ",".join(stages)))

    try:
        from .llm import LLMGateway
        gw = LLMGateway(store, conn)
        if gw.expects_real_but_stub():
            results.append(("llm_provider", "warn",
                            "STUB active but config expects real provider "
                            "(ANTHROPIC_API_KEY missing/invalid) - LLM calls return stub data"))
        else:
            results.append(("llm_provider", "ok", gw.provider.name))
    except Exception as exc:
        results.append(("llm_provider", "warn", str(exc)))

    ok = all(status != "fail" for _, status, _ in results)
    conn.execute(
        "INSERT INTO audit_log(ts, actor, action, entity, detail_json) VALUES(?,?,?,?,?)",
        (time.time(), "system", "startup_check", "engine",
         json.dumps({"ok": ok, "results": results}, ensure_ascii=False)),
    )
    conn.commit()
    return ok, results
