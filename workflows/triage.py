from __future__ import annotations

import json
import time

from engine.contracts import Stage, StageContext, StageResult
from engine.registry import register


def _text(tender):
    parts = [tender.get("title") or "", tender.get("description") or "",
             tender.get("buyer") or ""]
    return " ".join(parts).lower()


def _cpv_score(tender, weights):
    reasons = []
    matched_prefixes = {}
    codes = {c.get("id") for c in tender.get("cpv") or [] if c.get("id")}
    for code in codes:
        best = None
        for prefix, w in weights.items():
            if code.startswith(prefix):
                if best is None or len(prefix) > len(best[0]):
                    best = (prefix, w)
        if best:
            matched_prefixes[best[0]] = best[1]
    total = 0
    for prefix, w in matched_prefixes.items():
        total += w
        reasons.append({"type": "cpv", "key": prefix, "w": w})
    return total, reasons


def _keyword_score(text, weights):
    total = 0
    reasons = []
    for kw, w in weights.items():
        if kw.lower() in text:
            total += w
            reasons.append({"type": "keyword", "key": kw, "w": w})
    return total, reasons


def _value_score(tender, band):
    if not band:
        return 0, []
    amount = tender.get("value_amount")
    if amount is None:
        return 0, []
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return 0, []
    minimum = band.get("min")
    if minimum is not None and amount < float(minimum):
        w = float(band.get("weight_below_min", 0))
        if w:
            return w, [{"type": "value", "key": "below_min", "w": w}]
    return 0, []


def score_tender(tender, config):
    cpv_w = config.get("triage.cpv_weights", {})
    kw_w = config.get("triage.keyword_weights", {})
    band = config.get("triage.value_band", {})

    s_cpv, r_cpv = _cpv_score(tender, cpv_w)
    s_kw, r_kw = _keyword_score(_text(tender), kw_w)
    s_val, r_val = _value_score(tender, band)
    total = s_cpv + s_kw + s_val
    return total, r_cpv + r_kw + r_val


def bucket_for(score, config):
    th = config.get("triage.bucket_thresholds", {"relevant": 3, "gray": 0.5})
    if score >= th.get("relevant", 3):
        return "relevant"
    if score >= th.get("gray", 0.5):
        return "gray"
    return "out"


def _write_verdict(conn, tender_id, bucket, score, reasons):
    conn.execute(
        "DELETE FROM verdicts WHERE tender_id = ? AND stage_name = 'triage'", (tender_id,))
    conn.execute(
        "INSERT INTO verdicts(tender_id, stage_name, verdict, score, confidence, reason, "
        "model, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (tender_id, "triage", bucket, score, None,
         json.dumps(reasons, ensure_ascii=False), None, time.time()),
    )
    conn.commit()


@register("triage")
class TriageStage(Stage):
    consumes = ("tender",)
    produces = ("triage",)

    def run(self, ctx: StageContext) -> StageResult:
        tender = ctx.payload.get("tender") or {}
        score, reasons = score_tender(tender, ctx.config)
        bucket = bucket_for(score, ctx.config)
        tender_id = ctx.payload.get("tender_id") or ctx.tender_id
        if tender_id is not None:
            _write_verdict(ctx.db, int(tender_id), bucket, score, reasons)
        return StageResult(payload={**ctx.payload,
                                    "triage": {"bucket": bucket, "score": score,
                                               "reasons": reasons}})
