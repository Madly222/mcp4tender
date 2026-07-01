from __future__ import annotations

import json
import time

from engine.jsonutil import loads_loose
from engine.llm import LLMGateway
import workflows.applicability as ap
from workflows.verify import verify_against_source, decide_action, _store_verification


def _latest_extraction_fields(conn, tender_id):
    row = conn.execute(
        "SELECT fields_json FROM extractions WHERE tender_id = ? ORDER BY id DESC LIMIT 1",
        (tender_id,)).fetchone()
    if row and row["fields_json"]:
        f = loads_loose(row["fields_json"])
        return f if isinstance(f, dict) else None
    return None


def build_digest(conn, store, limit=None):
    weights = store.get("supervisor.rank_weights", {"score": 0.6, "margin": 0.4})
    proceed = store.get("supervisor.digest_verdicts", ["can", "partial"])
    placeholders = ",".join("?" for _ in proceed)
    rows = conn.execute(
        f"SELECT t.id, t.normalized_json, v.verdict, v.score, v.confidence, v.reason "
        f"FROM tenders t JOIN verdicts v ON v.tender_id = t.id "
        f"AND v.stage_name = 'applicability' WHERE v.verdict IN ({placeholders})",
        proceed).fetchall()

    items = []
    for r in rows:
        nj = loads_loose(r["normalized_json"]) or {}
        reason = loads_loose(r["reason"]) or {}
        sup = conn.execute(
            "SELECT margin, margin_partial, unmatched_count, currency, total_cost, tender_value "
            "FROM suppliers WHERE tender_id = ? ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
        fields = _latest_extraction_fields(conn, r["id"]) or {}
        margin = sup["margin"] if sup and sup["margin"] is not None else None
        score = r["score"] or 0
        m_norm = margin if margin is not None else 0
        rank = float(weights.get("score", 0.6)) * score + \
            float(weights.get("margin", 0.4)) * (m_norm * 100)
        items.append({
            "tender_id": r["id"], "title": nj.get("title"), "buyer": nj.get("buyer"),
            "verdict": r["verdict"], "readiness_score": score, "confidence": r["confidence"],
            "margin": margin, "margin_partial": bool(sup["margin_partial"]) if sup else None,
            "unmatched": sup["unmatched_count"] if sup else None,
            "currency": sup["currency"] if sup else None,
            "deadline": fields.get("termen_livrare"),
            "gaps": (reason.get("gaps") or [])[:3],
            "rank_score": round(rank, 2)})
    items.sort(key=lambda x: x["rank_score"], reverse=True)
    return items[:limit] if limit else items


def _latest_flags(conn):
    rows = conn.execute(
        "SELECT v.tender_id, v.stage, v.needs_review FROM verifications v "
        "JOIN (SELECT tender_id, stage, MAX(id) mid FROM verifications "
        "GROUP BY tender_id, stage) m ON v.id = m.mid WHERE v.needs_review = 1").fetchall()
    return [(r["tender_id"], r["stage"]) for r in rows]


def run_escalations(conn, store, gateway=None):
    autonomy = store.get("supervisor.autonomy", "auto")
    esc_model = store.get("supervisor.escalation_model", "claude-opus-4-8")
    esc_stages = store.get("supervisor.escalate_stages", ["applicability"])
    budget = int(store.get("supervisor.max_escalations", 10))
    gw = gateway or LLMGateway(store, conn)

    flags = _latest_flags(conn)
    done = []
    human = []
    spent = 0
    for tender_id, stage in flags:
        if stage == "suppliers":
            human.append({"tender_id": tender_id, "stage": stage,
                          "reason": "catalog/fx gap - needs human action (model cannot resolve)"})
            continue
        if autonomy != "auto" or stage not in esc_stages or spent >= budget:
            human.append({"tender_id": tender_id, "stage": stage,
                          "reason": "advisory mode" if autonomy != "auto" else
                          ("budget exhausted" if spent >= budget else "stage not eligible")})
            continue
        if stage == "applicability":
            ok = _escalate_applicability(conn, store, gw, tender_id, esc_model)
            spent += 1
            (done if ok else human).append({"tender_id": tender_id, "stage": stage,
                                            "model": esc_model, "resolved": ok})
        else:
            human.append({"tender_id": tender_id, "stage": stage,
                          "reason": "escalation not implemented for stage"})
    return {"done": done, "human_needed": human, "spent": spent}


def _escalate_applicability(conn, store, gw, tender_id, esc_model):
    row = conn.execute("SELECT normalized_json FROM tenders WHERE id = ?",
                       (tender_id,)).fetchone()
    if not row:
        return False
    tender = loads_loose(row["normalized_json"]) or {}
    extraction = ap._load_extraction(conn, tender_id)
    bucket = ap._load_bucket(conn, tender_id)
    gw.model_override = {"applicability": esc_model}
    out = ap.produce_applicability(tender, extraction, bucket, gw, store)
    gw.model_override = {}
    if out["status"] != "ok":
        return False
    ap._store_verdict(conn, tender_id, out["verdict"], out["model"])
    prompt = store.get("verify.applicability_prompt", ap.DEFAULT_VERIFY_PROMPT)
    result = verify_against_source(gw, store, out["source_text"], out["verdict"], prompt)
    threshold = float(store.get("verify.flag_confidence_threshold", 0.6))
    action = decide_action(result, store.get("verify.strictness", "strict"), threshold)
    resolved = action == "pass"
    _store_verification(conn, tender_id, "applicability", result, 1, not resolved)
    if resolved:
        conn.execute("UPDATE tenders SET status = 'analyzed' WHERE id = ? AND status = 'needs_review'",
                     (tender_id,))
        conn.commit()
    return resolved


def check_coverage(conn, store):
    stale_hours = float(store.get("supervisor.coverage_stale_hours", 48))
    drop_ratio = float(store.get("supervisor.coverage_drop_ratio", 0.3))
    now = time.time()
    warnings = []
    sources = []
    srows = conn.execute("SELECT DISTINCT source FROM source_runs").fetchall()
    for s in srows:
        src = s["source"]
        runs = conn.execute(
            "SELECT started_at, fetched, new_items, status FROM source_runs "
            "WHERE source = ? ORDER BY id DESC LIMIT 10", (src,)).fetchall()
        if not runs:
            continue
        last = runs[0]
        age_h = (now - (last["started_at"] or now)) / 3600.0
        recent = [r["new_items"] or 0 for r in runs[1:6]]
        avg = sum(recent) / len(recent) if recent else None
        entry = {"source": src, "age_hours": round(age_h, 1),
                 "last_new": last["new_items"], "last_status": last["status"],
                 "avg_recent_new": round(avg, 1) if avg is not None else None}
        sources.append(entry)
        if age_h > stale_hours:
            warnings.append(f"{src}: last collection {age_h:.0f}h ago (>{stale_hours:.0f}h)")
        ok_statuses = store.get("supervisor.coverage_ok_statuses", ["ok", "done", "success"])
        if last["status"] and last["status"] not in ok_statuses:
            warnings.append(f"{src}: last collection status={last['status']}")
        if avg and avg > 0 and (last["new_items"] or 0) < avg * drop_ratio:
            warnings.append(f"{src}: sharp drop - {last['new_items']} vs average {avg:.0f}")
    return {"warnings": warnings, "sources": sources}


def supervise(conn, store, digest_limit=None):
    gw = LLMGateway(store, conn)
    escalations = run_escalations(conn, store, gw)
    digest = build_digest(conn, store, limit=digest_limit)
    coverage = check_coverage(conn, store)
    conn.execute(
        "INSERT INTO supervisor_runs(digest_json, escalations_json, coverage_json, autonomy, "
        "escalations_done, human_needed, cost, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (json.dumps(digest, ensure_ascii=False), json.dumps(escalations, ensure_ascii=False),
         json.dumps(coverage, ensure_ascii=False), store.get("supervisor.autonomy", "auto"),
         len(escalations["done"]), len(escalations["human_needed"]), 0, time.time()))
    conn.commit()
    return {"digest": digest, "escalations": escalations, "coverage": coverage}
