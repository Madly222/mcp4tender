from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

from engine import db
from engine.config_store import ConfigStore
from engine.checks import run_startup_checks
from engine.runner import run_pipeline
from engine.scheduler import Scheduler

import workflows  # noqa: F401

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("TENDERENGINE_DB", str(BASE_DIR / "data" / "tenderengine.db"))
DEFAULTS_DIR = BASE_DIR / "config" / "defaults"


def bootstrap():
    conn = db.connect(DB_PATH)
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    seeded = store.seed_defaults(DEFAULTS_DIR)
    return conn, store, seeded


def _log(msg):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def cmd_check(conn, store, _args):
    ok, results = run_startup_checks(conn, store)
    for name, status, detail in results:
        print(f"  {name:10} {status:5} {detail}")
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


def cmd_run(conn, store, args):
    result = run_pipeline(args.pipeline, store, conn)
    print(f"run {result['run_id']} -> {result['status']}")
    print(f"payload: {result['payload']}")
    return 0 if result["status"] == "done" else 1


def cmd_serve(conn, store, _args):
    ok, _ = run_startup_checks(conn, store)
    if not ok:
        _log("startup checks FAILED, refusing to serve")
        return 1

    def dispatch(pipeline, job):
        if job.get("kind") == "collect":
            from workflows.collect_jobs import run_collect_job
            r = run_collect_job(job, store, conn, _log)
            _log(f"collect job -> new={r['new']}")
            return
        if not pipeline:
            return
        result = run_pipeline(pipeline, store, conn)
        _log(f"{pipeline} -> {result['status']}")

    scheduler = Scheduler(store, dispatch, logger=_log)
    try:
        scheduler.run_forever(interval=30)
    except KeyboardInterrupt:
        scheduler.stop()
    return 0


def _start_scheduler_thread():
    import threading

    def _run():
        conn = db.connect(DB_PATH)
        db.init_schema(conn)
        store = ConfigStore(conn)
        store.reload()

        def dispatch(pipeline, job):
            if job.get("kind") == "collect":
                from workflows.collect_jobs import run_collect_job
                r = run_collect_job(job, store, conn, _log)
                _log(f"sched collect job -> new={r['new']}")
                return
            if not pipeline:
                return
            result = run_pipeline(pipeline, store, conn)
            _log(f"sched {pipeline} -> {result['status']}")

        scheduler = Scheduler(store, dispatch, logger=_log)
        scheduler.run_forever(interval=30)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def cmd_web(conn, store, args):
    ok, _ = run_startup_checks(conn, store)
    if not ok and store.get("web.require_checks", True):
        _log("startup checks FAILED, refusing to serve web")
        return 1
    run_sched = store.get("web.run_scheduler", True)
    if run_sched:
        _start_scheduler_thread()
    import uvicorn
    from web.server import create_app
    app = create_app(DB_PATH)
    host = store.get("web.host", "0.0.0.0")
    port = int(getattr(args, "port", None) or store.get("web.port", 1255))
    token = os.environ.get("TENDERENGINE_WEB_TOKEN") or store.get("web.token", "")
    _log(f"web on http://{host}:{port}  scheduler={'on' if run_sched else 'off'}  "
         f"auth={'token' if token else 'OPEN (no token set)'}")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def cmd_demo(conn, store, _args):
    from engine import all_stages
    print(f"registered stages: {all_stages()}")
    result = run_pipeline("pipeline.demo", store, conn)
    print(f"run {result['run_id']} -> {result['status']}")
    print(f"payload: {result['payload']}")
    return 0


def cmd_collect(conn, store, args):
    from engine import run_collector
    if getattr(args, "reset", False):
        conn.execute("DELETE FROM source_state WHERE source = ?", (args.source,))
        conn.execute("UPDATE tenders SET content_hash = '' WHERE source = ?", (args.source,))
        conn.commit()
        _log(f"reset cursor + tender hashes for {args.source}")
    r = run_collector(args.source, store, conn)
    print(r)
    return 0 if r.get("status") in ("done", "disabled") else 1


def _warn_if_stub(store, conn):
    from engine import LLMGateway
    gw = LLMGateway(store, conn)
    if gw.expects_real_but_stub():
        _log("WARNING: LLM provider is STUB (no valid ANTHROPIC_API_KEY) - "
             "results will be placeholder data, not real analysis!")
    return gw.provider.name


def _print_digest(digest):
    if not digest:
        print("(digest empty - no can/partial tenders analyzed)")
        return
    print(f"\n=== DIGEST: {len(digest)} tenders to consider ===")
    for i, d in enumerate(digest, 1):
        margin = f"{d['margin']*100:.0f}%" if d["margin"] is not None else "?"
        if d.get("margin_partial"):
            margin += "~"
        print(f"\n{i}. [{d['rank_score']}] {(d['title'] or '')[:70]}")
        print(f"   verdict={d['verdict']} score={d['readiness_score']} "
              f"margin={margin} ({d['currency'] or ''}) deadline={d['deadline'] or '?'}")
        if d.get("gaps"):
            print(f"   gaps: {'; '.join(str(g)[:60] for g in d['gaps'])}")


def cmd_digest(conn, store, args):
    from workflows.supervisor import build_digest
    digest = build_digest(conn, store, limit=args.limit)
    _print_digest(digest)
    return 0


def cmd_supervise(conn, store, args):
    from workflows.supervisor import supervise
    _warn_if_stub(store, conn)
    report = supervise(conn, store, digest_limit=args.limit)
    esc = report["escalations"]
    print(f"\n=== ESCALATIONS (autonomy={store.get('supervisor.autonomy','auto')}) ===")
    print(f"auto-resolved: {len(esc['done'])}, need human: {len(esc['human_needed'])}, "
          f"escalations used: {esc['spent']}")
    for h in esc["human_needed"][:10]:
        print(f"  human: tender {h['tender_id']} [{h['stage']}] - {h.get('reason','')}")
    cov = report["coverage"]
    print(f"\n=== COVERAGE ===")
    if cov["warnings"]:
        for w in cov["warnings"]:
            print(f"  ! {w}")
    else:
        print("  ok - no collection warnings")
    _print_digest(report["digest"])
    return 0


def cmd_suppliers(conn, store, args):
    from engine import process_selected_tenders
    _warn_if_stub(store, conn)
    verdicts = store.get("suppliers.proceed_verdicts", ["can", "partial"])
    placeholders = ",".join("?" for _ in verdicts)
    rows = conn.execute(
        f"SELECT t.id FROM tenders t JOIN verdicts v ON v.tender_id = t.id "
        f"AND v.stage_name = 'applicability' WHERE v.verdict IN ({placeholders}) "
        "AND t.status = 'analyzed' ORDER BY v.score DESC" +
        (" LIMIT ?" if args.limit else ""),
        verdicts + ([args.limit] if args.limit else []),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if not ids:
        print("no analyzed can/partial tenders for suppliers")
        return 0
    print(f"sourcing suppliers for {len(ids)} tenders...")
    summary = process_selected_tenders("pipeline.tender_suppliers", store, conn, ids,
                                       next_status="sourced")
    print(f"sourced {summary['done']}/{summary['total']} (failed {summary['failed']})")
    return 0


def cmd_applicability(conn, store, args):
    from engine import process_selected_tenders
    _warn_if_stub(store, conn)
    buckets = store.get("extract.buckets", ["relevant", "gray"])
    placeholders = ",".join("?" for _ in buckets)
    rows = conn.execute(
        f"SELECT t.id FROM tenders t JOIN verdicts v ON v.tender_id = t.id "
        f"AND v.stage_name = 'triage' WHERE v.verdict IN ({placeholders}) "
        "AND t.status = 'extracted' ORDER BY v.score DESC" +
        (" LIMIT ?" if args.limit else ""),
        buckets + ([args.limit] if args.limit else []),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if not ids:
        print("no extracted relevant/gray tenders for applicability")
        return 0
    print(f"analyzing applicability for {len(ids)} tenders...")
    summary = process_selected_tenders("pipeline.tender_applicability", store, conn, ids,
                                       next_status="analyzed")
    print(f"analyzed {summary['done']}/{summary['total']} (failed {summary['failed']})")
    return 0


def cmd_extract(conn, store, args):
    from engine import process_selected_tenders
    _warn_if_stub(store, conn)
    buckets = store.get("extract.buckets", ["relevant", "gray"])
    placeholders = ",".join("?" for _ in buckets)
    rows = conn.execute(
        f"SELECT t.id FROM tenders t JOIN verdicts v ON v.tender_id = t.id "
        f"AND v.stage_name = 'triage' WHERE v.verdict IN ({placeholders}) "
        "AND t.status = 'triaged' ORDER BY v.score DESC" +
        (" LIMIT ?" if args.limit else ""),
        buckets + ([args.limit] if args.limit else []),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if not ids:
        print("no triaged relevant/gray tenders to extract")
        return 0
    print(f"extracting {len(ids)} tenders...")
    summary = process_selected_tenders("pipeline.tender_extract", store, conn, ids)
    print(f"extracted {summary['done']}/{summary['total']} (failed {summary['failed']})")
    return 0


def cmd_read_doc(conn, store, args):
    import json as _json
    from engine import LLMGateway, get_document_text
    row = conn.execute("SELECT normalized_json FROM tenders WHERE id = ?",
                       (args.tender_id,)).fetchone()
    if not row:
        print(f"tender {args.tender_id} not found")
        return 1
    tender = _json.loads(row["normalized_json"])
    read_types = store.get("documents.read_types", ["biddingDocuments", "tenderNotice"])
    skip = store.get("documents.skip_formats", ["doc"])
    docs = [d for d in tender.get("documents", [])
            if (not read_types or d.get("type") in read_types)
            and (d.get("format") or "").lower() not in skip]
    if not docs:
        print("no readable documents on this tender")
        return 0
    gw = LLMGateway(store, conn)
    print(f"provider: {gw.provider.name}, readable docs: {len(docs)}")
    for d in docs[:int(store.get("documents.max_docs_per_tender", 3))]:
        r = get_document_text(d, gw, store)
        print(f"\n--- {d.get('title')} [{d.get('format')}] ---")
        print(f"method={r['method']} chars={r.get('chars',0)} cost=${r.get('cost',0):.6f}")
        print((r.get("text") or r.get("error") or "")[:600])
    return 0


def cmd_llm_test(conn, store, args):
    from engine import LLMGateway
    gw = LLMGateway(store, conn)
    print(f"provider: {gw.provider.name}")
    msg = [{"role": "user", "content": getattr(args, "text", None) or "Say OK in one word."}]
    r1 = gw.complete("default", "You are concise.", msg, max_tokens=64)
    print(f"model={r1['model']} cached={r1['cached']} "
          f"in={r1['input_tokens']} out={r1['output_tokens']} cost=${r1['cost']:.6f}")
    print(f"text: {r1['text'][:200]}")
    r2 = gw.complete("default", "You are concise.", msg, max_tokens=64)
    print(f"second call cached={r2['cached']} (cache works if True)")
    return 0


def cmd_renormalize(conn, store, args):
    from engine import renormalize_source
    r = renormalize_source(args.source, store, conn)
    print(r)
    return 0


def cmd_triage(conn, store, args):
    from engine import process_stored_tenders
    pipeline = getattr(args, "pipeline", None) or "pipeline.tender_triage"
    summary = process_stored_tenders(pipeline, store, conn)
    print(f"triaged {summary['done']}/{summary['total']}  buckets={summary['buckets']}")
    return 0


def cmd_probe(conn, store, args):
    import json as _json
    from engine.http import get_json
    sc = store.get(f"sources.{args.source}", {})
    list_url = sc.get("list_url")
    if not list_url:
        print(f"no list_url in sources.{args.source}")
        return 1
    resp = get_json(list_url, timeout=int(sc.get("timeout", 30)))
    if isinstance(resp, dict):
        print(f"top-level keys: {list(resp.keys())}")
        data = resp.get("data") or []
        print(f"data items: {len(data)}")
        if data:
            print(f"first entry: {_json.dumps(data[0], ensure_ascii=False)}")
            print(f"last entry:  {_json.dumps(data[-1], ensure_ascii=False)}")
        for k in resp:
            if k != "data":
                print(f"cursor field '{k}': {_json.dumps(resp[k], ensure_ascii=False)[:200]}")
    else:
        print(f"unexpected response type: {type(resp)}")
    return 0


def cmd_dedupe_docs(conn, store, args):
    from workflows.analysis import dedupe_documents_db
    r = dedupe_documents_db(conn, source=getattr(args, "source", None) or "mtender")
    print(f"dedupe-docs: {r['documents_removed']} duplicate document(s) removed "
          f"across {r['tenders_changed']} tender(s)")
    return 0


def main():
    p = argparse.ArgumentParser(description="tender engine")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("check")
    pr = sub.add_parser("run")
    pr.add_argument("pipeline")
    sub.add_parser("serve")
    pweb = sub.add_parser("web")
    pweb.add_argument("--port", type=int, default=None)
    sub.add_parser("demo")
    pc = sub.add_parser("collect")
    pc.add_argument("source")
    pc.add_argument("--reset", action="store_true")
    pp = sub.add_parser("probe")
    pp.add_argument("source")
    sub.add_parser("triage")
    pr2 = sub.add_parser("renormalize")
    pr2.add_argument("source")
    pl = sub.add_parser("llm-test")
    pl.add_argument("--text", default=None)
    prd = sub.add_parser("read-doc")
    prd.add_argument("tender_id", type=int)
    pe = sub.add_parser("extract")
    pe.add_argument("--limit", type=int, default=None)
    pa = sub.add_parser("applicability")
    pa.add_argument("--limit", type=int, default=None)
    psup = sub.add_parser("suppliers")
    psup.add_argument("--limit", type=int, default=None)
    psv = sub.add_parser("supervise")
    psv.add_argument("--limit", type=int, default=None)
    pdg = sub.add_parser("digest")
    pdg.add_argument("--limit", type=int, default=None)
    pdd = sub.add_parser("dedupe-docs")
    pdd.add_argument("--source", default="mtender")
    args = p.parse_args()

    conn, store, seeded = bootstrap()
    import logging
    _level = str(store.get("log.level", "INFO")).upper()
    logging.basicConfig(
        level=getattr(logging, _level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)
    if seeded:
        _log(f"seeded configs: {seeded}")

    handler = {"check": cmd_check, "run": cmd_run, "serve": cmd_serve,
               "web": cmd_web,
               "demo": cmd_demo, "collect": cmd_collect, "probe": cmd_probe,
               "triage": cmd_triage, "renormalize": cmd_renormalize,
               "llm-test": cmd_llm_test, "read-doc": cmd_read_doc,
               "extract": cmd_extract, "applicability": cmd_applicability,
               "suppliers": cmd_suppliers, "supervise": cmd_supervise,
               "digest": cmd_digest, "dedupe-docs": cmd_dedupe_docs}.get(args.command, cmd_demo)
    sys.exit(handler(conn, store, args))


if __name__ == "__main__":
    main()
