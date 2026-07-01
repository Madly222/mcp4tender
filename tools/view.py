from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("TENDERENGINE_DB", str(BASE_DIR / "data" / "tenderengine.db"))


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ts(value):
    if value is None:
        return "-"
    return dt.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def _print_rows(rows, cols):
    if not rows:
        print("(empty)")
        return
    widths = {c: len(c) for c in cols}
    data = []
    for r in rows:
        d = {c: str(r[c]) for c in cols}
        for c in cols:
            widths[c] = max(widths[c], len(d[c]))
        data.append(d)
    line = "  ".join(c.ljust(widths[c]) for c in cols)
    print(line)
    print("  ".join("-" * widths[c] for c in cols))
    for d in data:
        print("  ".join(d[c].ljust(widths[c]) for c in cols))


def cmd_runs(conn, n):
    rows = conn.execute(
        "SELECT run_id, pipeline, mode, status, started_at, finished_at "
        "FROM pipeline_runs ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    out = [{"run_id": r["run_id"][:12], "pipeline": r["pipeline"], "mode": r["mode"],
            "status": r["status"], "started": _ts(r["started_at"]),
            "finished": _ts(r["finished_at"])} for r in rows]
    _print_rows(out, ["run_id", "pipeline", "mode", "status", "started", "finished"])


def cmd_stages(conn, n):
    rows = conn.execute(
        "SELECT run_id, stage_name, status, tokens, cost, error, started_at "
        "FROM stage_runs ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    out = [{"run_id": r["run_id"][:12], "stage": r["stage_name"], "status": r["status"],
            "tokens": r["tokens"], "cost": r["cost"],
            "error": (r["error"] or "")[:40], "at": _ts(r["started_at"])} for r in rows]
    _print_rows(out, ["run_id", "stage", "status", "tokens", "cost", "error", "at"])


def cmd_tenders(conn, n):
    rows = conn.execute(
        "SELECT id, source, external_id, status, updated_at FROM tenders "
        "ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    out = [{"id": r["id"], "source": r["source"], "external_id": r["external_id"],
            "status": r["status"], "updated": _ts(r["updated_at"])} for r in rows]
    _print_rows(out, ["id", "source", "external_id", "status", "updated"])


def cmd_verdicts(conn, n):
    rows = conn.execute(
        "SELECT tender_id, stage_name, verdict, score, confidence, model, created_at "
        "FROM verdicts ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    out = [{"tender_id": r["tender_id"], "stage": r["stage_name"], "verdict": r["verdict"],
            "score": r["score"], "conf": r["confidence"], "model": r["model"],
            "at": _ts(r["created_at"])} for r in rows]
    _print_rows(out, ["tender_id", "stage", "verdict", "score", "conf", "model", "at"])


def cmd_configs(conn, _n):
    rows = conn.execute(
        "SELECT key, version, value_json FROM configs WHERE active = 1 ORDER BY key"
    ).fetchall()
    for r in rows:
        print(f"{r['key']}  (v{r['version']})  =  {r['value_json']}")
    if not rows:
        print("(no active configs)")


def cmd_triage(conn, n):
    rows = conn.execute(
        "SELECT t.id, t.normalized_json, v.verdict, v.score, v.reason "
        "FROM tenders t LEFT JOIN verdicts v "
        "ON v.tender_id = t.id AND v.stage_name = 'triage' "
        "ORDER BY v.score DESC, t.id DESC LIMIT ?", (n,)
    ).fetchall()
    import json as _json
    out = []
    for r in rows:
        try:
            title = (_json.loads(r["normalized_json"]) or {}).get("title") or ""
        except Exception:
            title = ""
        out.append({"id": r["id"], "bucket": r["verdict"] or "-",
                    "score": r["score"] if r["score"] is not None else "-",
                    "title": title[:50]})
    _print_rows(out, ["id", "bucket", "score", "title"])


def cmd_extractions(conn, n):
    import json as _json
    rows = conn.execute(
        "SELECT tender_id, fields_json, method, tokens, cost, model FROM extractions "
        "ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    out = []
    for r in rows:
        try:
            f = _json.loads(r["fields_json"]) if r["fields_json"] else {}
            obiect = (f.get("obiect") if isinstance(f, dict) else "") or ""
            nech = len(f.get("echipamente", [])) if isinstance(f, dict) else 0
        except Exception:
            obiect, nech = "(parse err)", 0
        out.append({"tender": r["tender_id"], "method": r["method"] or "-",
                    "equip": nech, "tokens": r["tokens"],
                    "cost": f"${r['cost']:.4f}" if r["cost"] else "$0",
                    "obiect": str(obiect)[:44]})
    _print_rows(out, ["tender", "method", "equip", "tokens", "cost", "obiect"])


def cmd_verifications(conn, n):
    rows = conn.execute(
        "SELECT tender_id, stage, status, issues_json, retries, needs_review, cost "
        "FROM verifications ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    import json as _json
    out = []
    for r in rows:
        try:
            ij = _json.loads(r["issues_json"]) if r["issues_json"] else {}
            nmiss = len(ij.get("missing", []) or [])
            niss = len(ij.get("issues", []) or [])
        except Exception:
            nmiss = niss = 0
        out.append({"tender": r["tender_id"], "stage": r["stage"],
                    "status": r["status"] or "-", "missing": nmiss, "issues": niss,
                    "retries": r["retries"], "review": "YES" if r["needs_review"] else "",
                    "cost": f"${r['cost']:.4f}" if r["cost"] else "$0"})
    _print_rows(out, ["tender", "stage", "status", "missing", "issues", "retries", "review", "cost"])


def cmd_applicability(conn, n):
    import json as _json
    rows = conn.execute(
        "SELECT t.id, t.normalized_json, v.verdict, v.score, v.confidence, v.reason "
        "FROM tenders t JOIN verdicts v ON v.tender_id = t.id "
        "AND v.stage_name = 'applicability' ORDER BY v.score DESC LIMIT ?", (n,)
    ).fetchall()
    out = []
    for r in rows:
        try:
            title = (_json.loads(r["normalized_json"]) or {}).get("title") or ""
        except Exception:
            title = ""
        try:
            reason = _json.loads(r["reason"]) if r["reason"] else {}
            ngaps = len(reason.get("gaps", []) or [])
        except Exception:
            ngaps = 0
        out.append({"id": r["id"], "verdict": r["verdict"] or "-",
                    "score": r["score"] if r["score"] is not None else "-",
                    "conf": r["confidence"] if r["confidence"] is not None else "-",
                    "gaps": ngaps, "title": title[:38]})
    _print_rows(out, ["id", "verdict", "score", "conf", "gaps", "title"])


def cmd_suppliers(conn, n):
    rows = conn.execute(
        "SELECT tender_id, total_cost, tender_value, currency, margin, matched_count, "
        "unmatched_count, margin_partial FROM suppliers ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    out = []
    for r in rows:
        margin = f"{r['margin']*100:.1f}%" if r["margin"] is not None else "-"
        if r["margin"] is not None and r["margin_partial"]:
            margin += "~"
        out.append({"tender": r["tender_id"],
                    "cost": f"{r['total_cost']:.0f}{r['currency'] or ''}" if r["total_cost"] else "0",
                    "tender_val": f"{r['tender_value']:.0f}{r['currency'] or ''}" if r["tender_value"] else "?",
                    "margin": margin, "matched": r["matched_count"],
                    "unmatched": r["unmatched_count"],
                    "partial": "YES" if r["margin_partial"] else ""})
    _print_rows(out, ["tender", "cost", "tender_val", "margin", "matched", "unmatched", "partial"])


def cmd_sources(conn, n):
    rows = conn.execute(
        "SELECT source, started_at, fetched, new_items, cursor_after, status, error "
        "FROM source_runs ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    out = [{"source": r["source"], "fetched": r["fetched"], "new": r["new_items"],
            "status": r["status"], "cursor": (r["cursor_after"] or "")[:24],
            "error": (r["error"] or "")[:30], "at": _ts(r["started_at"])} for r in rows]
    _print_rows(out, ["source", "fetched", "new", "status", "cursor", "error", "at"])


def cmd_audit(conn, n):
    rows = conn.execute(
        "SELECT ts, actor, action, entity, detail_json FROM audit_log "
        "ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    for r in rows:
        print(f"{_ts(r['ts'])}  {r['actor']}  {r['action']}  {r['entity']}  {r['detail_json']}")
    if not rows:
        print("(empty)")


def main():
    p = argparse.ArgumentParser(description="tender engine read-only inspector")
    p.add_argument("command",
                   choices=["runs", "stages", "tenders", "verdicts", "configs", "audit", "sources", "triage", "extractions", "verifications", "applicability", "suppliers"])
    p.add_argument("-n", type=int, default=20)
    args = p.parse_args()

    if not Path(DB_PATH).exists():
        print(f"db not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = _conn()
    {"runs": cmd_runs, "stages": cmd_stages, "tenders": cmd_tenders,
     "verdicts": cmd_verdicts, "configs": cmd_configs, "audit": cmd_audit,
     "sources": cmd_sources, "triage": cmd_triage,
     "extractions": cmd_extractions,
     "verifications": cmd_verifications,
     "applicability": cmd_applicability,
     "suppliers": cmd_suppliers}[args.command](conn, args.n)


if __name__ == "__main__":
    main()
