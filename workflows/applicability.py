from __future__ import annotations

import json
import time

from engine.contracts import Stage, StageContext, StageResult
from engine.llm import LLMGateway
from engine.registry import register
from workflows.verify import (verify_against_source, decide_action,
                              _store_verification, _parse_json, flag_parse_failure)

DEFAULT_PROMPT = (
    "Ești analist de licitații pentru compania descrisă în PROFIL. Evaluează dacă compania "
    "poate executa acest tender, pe baza obiectului, cerințelor tehnice și echipamentelor "
    "necesare. Ține cont de TOATE criteriile din profil (parteneriate, certificări, referințe, "
    "verticale, servicii, note). Fii realist. Răspunde DOAR cu JSON valid: "
    "{\"can_execute\": \"can\"|\"partial\"|\"cannot\", \"readiness_score\": 0-100, "
    "\"confidence\": 0..1, \"reasoning\": string, \"matched\": [ce din profil se potrivește], "
    "\"gaps\": [ce lipsește pentru execuție completă], "
    "\"required_equipment\": [echipamente necesare]}."
)

DEFAULT_VERIFY_PROMPT = (
    "Verifici un verdict de aplicabilitate față de PROFILUL companiei și CERINȚELE tenderului. "
    "Raportează DOAR probleme reale: (1) verdict 'can'/'partial' dar există gaps critice "
    "neacoperite de profil; (2) verdict 'cannot' dar profilul acoperă clar cerințele; "
    "(3) gaps inventate sau parteneriate/certificări din profil ignorate. "
    "NU raporta probleme de formulare. Răspunde DOAR cu JSON: "
    "{\"status\":\"ok\"|\"issues\", \"issues\":[], \"missing\":[], \"confidence\":0..1}."
)


def _profile_text(config):
    profile = config.get("capabilities.profile", {})
    return json.dumps(profile, ensure_ascii=False, indent=2)


def _load_extraction(conn, tender_id):
    row = conn.execute(
        "SELECT fields_json FROM extractions WHERE tender_id = ? ORDER BY id DESC LIMIT 1",
        (tender_id,)).fetchone()
    if not row or not row["fields_json"]:
        return None
    try:
        return json.loads(row["fields_json"])
    except json.JSONDecodeError:
        return None


def _load_bucket(conn, tender_id):
    row = conn.execute(
        "SELECT verdict FROM verdicts WHERE tender_id = ? AND stage_name = 'triage' "
        "ORDER BY id DESC LIMIT 1", (tender_id,)).fetchone()
    return row["verdict"] if row else "gray"


def _build_context(tender, extraction, config):
    parts = ["PROFIL COMPANIE:\n" + _profile_text(config)]
    parts.append("TENDER:\n" + json.dumps({
        "obiect": tender.get("title"), "buyer": tender.get("buyer"),
        "value_amount": tender.get("value_amount"),
        "value_currency": tender.get("value_currency"),
        "cpv": tender.get("cpv")}, ensure_ascii=False))
    if extraction:
        parts.append("CERINȚE EXTRASE:\n" + json.dumps(extraction, ensure_ascii=False)[
            :int(config.get("applicability.max_extraction_chars", 30000))])
    return "\n\n=====\n\n".join(parts)


def _model_stage(bucket, config):
    mapping = config.get("applicability.model_by_bucket",
                         {"relevant": "applicability", "gray": "applicability_gray"})
    return mapping.get(bucket, "applicability_gray")


def produce_applicability(tender, extraction, bucket, gateway, config, hint=None):
    steps = []
    context = _build_context(tender, extraction, config)
    steps.append(("Build context",
                  f"{len(context)} chars (company profile + extracted facts)"
                  + ("" if extraction else " — no extraction available, tender fields only")))
    system = config.get("applicability.prompt", DEFAULT_PROMPT)
    if hint:
        system = system + "\n\nINDICAȚIE: " + hint
    stage = _model_stage(bucket, config)
    steps.append(("Pick model", f"triage bucket '{bucket}' → model stage '{stage}'"))
    steps.append(("Model input · system prompt", system[:3000]))
    steps.append(("Model input · content sent", context[:6000]))
    r = gateway.complete(stage, system, [{"role": "user", "content": context}],
                         max_tokens=int(config.get("applicability.max_output_tokens", 2048)),
                         prefill="{")
    steps.append(("Call model",
                  f"{r['model']}: {r['input_tokens']}+{r['output_tokens']} tokens, "
                  f"${r['cost']:.4f}"))
    steps.append(("Model output · raw response", (r["text"] or "")[:8000]))
    verdict = _parse_json(r["text"])
    if isinstance(verdict, dict):
        steps.append(("Parse verdict",
                      f"can_execute={verdict.get('can_execute')}, "
                      f"readiness={verdict.get('readiness_score')}, "
                      f"gaps={len(verdict.get('gaps') or [])}"))
    else:
        steps.append(("Parse verdict", "could not parse the model's JSON output"))
    return {"status": "ok" if verdict is not None else "parse_error",
            "verdict": verdict if verdict is not None else r["text"],
            "source_text": context, "model": r["model"],
            "cost": r["cost"], "tokens": r["input_tokens"] + r["output_tokens"],
            "steps": steps}


def _store_verdict(conn, tender_id, verdict_obj, model):
    conn.execute(
        "DELETE FROM verdicts WHERE tender_id = ? AND stage_name = 'applicability'",
        (tender_id,))
    if not isinstance(verdict_obj, dict):
        conn.execute(
            "INSERT INTO verdicts(tender_id, stage_name, verdict, score, confidence, reason, "
            "model, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (tender_id, "applicability", "unknown", None, None,
             json.dumps({"raw": str(verdict_obj)[:2000]}, ensure_ascii=False),
             model, time.time()))
        conn.commit()
        return
    reason = json.dumps({"reasoning": verdict_obj.get("reasoning"),
                         "matched": verdict_obj.get("matched"),
                         "gaps": verdict_obj.get("gaps"),
                         "required_equipment": verdict_obj.get("required_equipment")},
                        ensure_ascii=False)
    verdict = (verdict_obj.get("can_execute") or verdict_obj.get("verdict") or "unknown")
    conn.execute(
        "INSERT INTO verdicts(tender_id, stage_name, verdict, score, confidence, reason, "
        "model, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (tender_id, "applicability", verdict,
         verdict_obj.get("readiness_score"), verdict_obj.get("confidence"),
         reason, model, time.time()))
    conn.commit()


@register("applicability")
class ApplicabilityStage(Stage):
    consumes = ("tender",)
    produces = ("applicability",)

    def run(self, ctx: StageContext) -> StageResult:
        tender = ctx.payload.get("tender") or {}
        tender_id = ctx.payload.get("tender_id") or ctx.tender_id
        gw = LLMGateway(ctx.config, ctx.db)
        extraction = ctx.payload.get("extraction", {}).get("fields") if ctx.payload.get("extraction") else None
        if extraction is None and tender_id is not None:
            extraction = _load_extraction(ctx.db, int(tender_id))
        bucket = _load_bucket(ctx.db, int(tender_id)) if tender_id is not None else "gray"

        out = produce_applicability(tender, extraction, bucket, gw, ctx.config)
        if tender_id is not None:
            _store_verdict(ctx.db, int(tender_id), out["verdict"], out["model"])
            from workflows.trace import log_steps
            log_steps(ctx.db, int(tender_id), "applicability", out.get("steps"))
            if out["status"] != "ok":
                flag_parse_failure(ctx.db, int(tender_id), "applicability", str(out["verdict"]))

        return StageResult(
            payload={**ctx.payload, "applicability": {"status": out["status"],
                                                      "verdict": out["verdict"],
                                                      "model": out["model"]},
                     "applicability_source": out["source_text"],
                     "_bucket": bucket, "_extraction": extraction},
            metrics={"tokens": out["tokens"], "cost": out["cost"]})


@register("applicability_verify")
class ApplicabilityVerifyStage(Stage):
    consumes = ("applicability",)
    produces = ("applicability_verification",)

    def run(self, ctx: StageContext) -> StageResult:
        tender = ctx.payload.get("tender") or {}
        tender_id = ctx.payload.get("tender_id") or ctx.tender_id
        applicability = ctx.payload.get("applicability") or {}
        source_text = ctx.payload.get("applicability_source") or ""
        gw = LLMGateway(ctx.config, ctx.db)

        if applicability.get("status") != "ok" or not source_text:
            return StageResult(payload={**ctx.payload,
                                        "applicability_verification": {"status": "skipped"}})

        strictness = ctx.config.get("verify.strictness", "strict")
        max_retries = int(ctx.config.get("verify.max_retries", 1))
        threshold = float(ctx.config.get("verify.flag_confidence_threshold", 0.6))
        prompt = ctx.config.get("verify.applicability_prompt", DEFAULT_VERIFY_PROMPT)

        verdict = applicability.get("verdict")
        bucket = ctx.payload.get("_bucket", "gray")
        extraction = ctx.payload.get("_extraction")

        result = verify_against_source(gw, ctx.config, source_text, verdict, prompt)
        total_cost = result["cost"]
        total_tokens = result["tokens"]
        retries = 0
        action = decide_action(result, strictness, threshold)

        while action == "retry" and retries < max_retries:
            retries += 1
            hint = "Reanalizează ținând cont de: " + "; ".join(
                (result.get("missing") or []) + (result.get("issues") or []))
            out = produce_applicability(tender, extraction, bucket, gw, ctx.config, hint=hint)
            total_cost += out.get("cost", 0)
            total_tokens += out.get("tokens", 0)
            if out.get("status") == "ok":
                verdict = out["verdict"]
                if tender_id is not None:
                    _store_verdict(ctx.db, int(tender_id), verdict, out["model"])
                result = verify_against_source(gw, ctx.config, source_text, verdict, prompt)
                total_cost += result["cost"]
                total_tokens += result["tokens"]
            action = decide_action(result, strictness, threshold)

        needs_review = action in ("retry", "flag")
        if tender_id is not None:
            _store_verification(ctx.db, int(tender_id), "applicability", result,
                                retries, needs_review)

        return StageResult(
            payload={**ctx.payload, "applicability_verification": {
                "status": result["status"], "issues": result["issues"],
                "missing": result["missing"], "retries": retries,
                "needs_review": needs_review}},
            metrics={"tokens": total_tokens, "cost": total_cost})
