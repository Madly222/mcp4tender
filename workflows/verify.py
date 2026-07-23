from __future__ import annotations

import json
import re
import time

from engine.contracts import Stage, StageContext, StageResult
from engine.llm import LLMGateway
from engine.registry import register
from workflows.extract import produce_extraction, _store_extraction


def _parse_json(text):
    from engine.jsonutil import loads_loose
    return loads_loose(text)


def verify_against_source(gateway, config, source_text, produced, prompt, model_stage="verify"):
    body = ("DATE EXTRASE (JSON):\n" + json.dumps(produced, ensure_ascii=False)
            + "\n\n=====\n\nTEXT SURSĂ:\n" + source_text[:int(config.get("verify.max_source_chars", 60000))])
    r = gateway.complete(model_stage, prompt, [{"role": "user", "content": body}],
                         max_tokens=int(config.get("verify.max_output_tokens", 1024)),
                         prefill="{")
    parsed = _parse_json(r["text"]) or {}
    status = parsed.get("status", "ok")
    issues = parsed.get("issues", []) or []
    missing = parsed.get("missing", []) or []
    confidence = parsed.get("confidence")
    return {"status": status, "issues": issues, "missing": missing,
            "confidence": confidence, "cost": r["cost"],
            "tokens": r["input_tokens"] + r["output_tokens"], "model": r["model"]}


def hint_items(result):
    out = []
    for item in (result.get("missing") or []) + (result.get("issues") or []):
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            out.append(" ".join(str(v) for v in item.values() if v not in (None, "")))
        elif item not in (None, ""):
            out.append(str(item))
    return "; ".join(x for x in out if x)


def decide_action(verify_result, strictness, flag_confidence_threshold=0.6):
    has_missing = bool(verify_result.get("missing"))
    raw_issues = bool(verify_result.get("issues")) or verify_result.get("status") == "issues"
    confidence = verify_result.get("confidence")
    confident_ok = confidence is not None and confidence >= flag_confidence_threshold
    has_issues = raw_issues and not confident_ok
    if strictness == "light":
        return "flag" if (has_missing or has_issues) else "pass"
    if strictness == "balanced":
        if has_missing:
            return "retry"
        return "flag" if has_issues else "pass"
    if has_missing or has_issues:
        return "retry"
    return "pass"


def _store_verification(conn, tender_id, stage, result, retries, needs_review):
    conn.execute(
        "INSERT INTO verifications(tender_id, stage, status, issues_json, confidence, "
        "retries, needs_review, model, tokens, cost, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (tender_id, stage, result.get("status"),
         json.dumps({"issues": result.get("issues"), "missing": result.get("missing")},
                    ensure_ascii=False),
         result.get("confidence"), retries, 1 if needs_review else 0,
         result.get("model"), result.get("tokens", 0), result.get("cost", 0), time.time()),
    )
    if needs_review:
        conn.execute("UPDATE tenders SET status = 'needs_review' WHERE id = ?", (tender_id,))
    conn.commit()


def flag_parse_failure(conn, tender_id, stage, raw_text):
    result = {"status": "issues",
              "issues": ["răspunsul producătorului nu s-a parsat ca JSON"],
              "missing": [], "confidence": 0.0, "model": None, "tokens": 0, "cost": 0}
    _store_verification(conn, int(tender_id), stage, result, 0, True)


@register("extract_verify")
class ExtractVerifyStage(Stage):
    consumes = ("extraction",)
    produces = ("verification",)

    def run(self, ctx: StageContext) -> StageResult:
        tender = ctx.payload.get("tender") or {}
        tender_id = ctx.payload.get("tender_id") or ctx.tender_id
        extraction = ctx.payload.get("extraction") or {}
        source_text = ctx.payload.get("extract_source") or ""
        gw = LLMGateway(ctx.config, ctx.db)

        if extraction.get("status") != "ok" or not source_text:
            return StageResult(payload={**ctx.payload,
                                        "verification": {"status": "skipped"}})

        strictness = ctx.config.get("verify.strictness", "strict")
        max_retries = int(ctx.config.get("verify.max_retries", 1))
        threshold = float(ctx.config.get("verify.flag_confidence_threshold", 0.6))
        prompt = ctx.config.get("verify.extract_prompt", DEFAULT_VERIFY_PROMPT)

        fields = extraction.get("fields")
        result = verify_against_source(gw, ctx.config, source_text, fields, prompt)
        total_cost = result["cost"]
        total_tokens = result["tokens"]
        retries = 0

        action = decide_action(result, strictness, threshold)
        while action == "retry" and retries < max_retries:
            retries += 1
            hint = "Completează/corectează: " + hint_items(result)
            out = produce_extraction(tender, gw, ctx.config, hint=hint)
            total_cost += out.get("cost", 0)
            total_tokens += out.get("tokens", 0)
            if out.get("status") == "ok":
                fields = out["fields"]
                if tender_id is not None:
                    _store_extraction(ctx.db, int(tender_id), fields, out["sources"],
                                      out["model"], out["method"], out["tokens"], out["cost"])
                result = verify_against_source(gw, ctx.config, source_text, fields, prompt)
                total_cost += result["cost"]
                total_tokens += result["tokens"]
            action = decide_action(result, strictness, threshold)

        needs_review = action in ("retry", "flag")
        if tender_id is not None:
            _store_verification(ctx.db, int(tender_id), "extract", result, retries, needs_review)

        verification = {"status": result["status"], "issues": result["issues"],
                        "missing": result["missing"], "retries": retries,
                        "needs_review": needs_review}
        return StageResult(payload={**ctx.payload, "verification": verification,
                                    "extraction": {**extraction, "fields": fields}},
                           metrics={"tokens": total_tokens, "cost": total_cost})


DEFAULT_VERIFY_PROMPT = (
    "Ești un verificator de calitate pentru extragerea datelor din caiete de sarcini. "
    "Compară DATELE EXTRASE (JSON) cu TEXTUL SURSĂ și raportează DOAR probleme reale de fond. "
    "Raportează în 'missing' DOAR câmpuri care există explicit în sursă dar lipsesc/sunt null în extras "
    "(ex: o valoare estimată scrisă clar în document). NU raporta ca lipsă informații care NU există în sursă. "
    "Raportează în 'issues' DOAR: date inventate care nu apar în sursă, sau erori numerice/cantități greșite. "
    "NU raporta probleme de formă (ex: o informație corectă aflată în alt câmp decât te-ai aștepta, "
    "sau detalii prezente în cerinte_tehnice dar nu duplicate în specificatii). "
    "Răspunde DOAR cu JSON valid: {\"status\": \"ok\"|\"issues\", \"issues\": [stringuri], "
    "\"missing\": [nume_camp], \"confidence\": 0..1}. "
    "confidence = cât de sigur ești că problemele raportate sunt reale (1=sigur). "
    "Dacă extragerea e corectă pe fond, status='ok' cu liste goale."
)
