from __future__ import annotations

import json
import time

from engine.contracts import Stage, StageContext, StageResult
from engine.jsonutil import loads_loose
from engine.llm import LLMGateway
from engine.registry import register
from workflows.verify import (verify_against_source, decide_action,
                              _store_verification, flag_parse_failure)

DEFAULT_MATCH_PROMPT = (
    "Ești specialist în aprovizionare. Pentru fiecare CERINȚĂ de echipament, alege din CATALOG "
    "produsul care satisface specificațiile tehnice. Evaluează potrivirea reală a specificațiilor, "
    "nu doar denumirea. Răspunde DOAR cu JSON valid: {\"matches\": [{\"req_index\": int, "
    "\"catalog_id\": string sau null, \"spec_fit\": \"full\"|\"partial\"|\"none\", "
    "\"confidence\": 0..1, \"note\": string}]}. Dacă niciun produs din catalog nu se potrivește, "
    "catalog_id=null și spec_fit='none'."
)

DEFAULT_VERIFY_PROMPT = (
    "Verifici potrivirile furnizor-cerință. Compară MATCHES cu CERINȚELE și CATALOGUL. "
    "Raportează DOAR probleme reale: (1) produs marcat 'full' care NU îndeplinește o specificație "
    "critică din cerință; (2) potrivire inventată (catalog_id inexistent); (3) cerință clar "
    "acoperită de catalog dar marcată 'none'. NU raporta nuanțe de formulare. Răspunde DOAR JSON: "
    "{\"status\":\"ok\"|\"issues\", \"issues\":[], \"missing\":[], \"confidence\":0..1}."
)


def _load_requirements(conn, tender_id):
    row = conn.execute(
        "SELECT fields_json FROM extractions WHERE tender_id = ? ORDER BY id DESC LIMIT 1",
        (tender_id,)).fetchone()
    if row and row["fields_json"]:
        fields = loads_loose(row["fields_json"])
        if isinstance(fields, dict):
            equip = fields.get("echipamente") or []
            reqs = []
            for i, e in enumerate(equip):
                if isinstance(e, dict):
                    reqs.append({"index": i, "denumire": e.get("denumire"),
                                 "model": e.get("model"), "cantitate": e.get("cantitate"),
                                 "specificatii": e.get("specificatii")})
            if reqs:
                return reqs, fields.get("valoare_estimata")
    vrow = conn.execute(
        "SELECT reason FROM verdicts WHERE tender_id = ? AND stage_name = 'applicability' "
        "ORDER BY id DESC LIMIT 1", (tender_id,)).fetchone()
    if vrow and vrow["reason"]:
        reason = loads_loose(vrow["reason"]) or {}
        items = reason.get("required_equipment") or []
        return [{"index": i, "denumire": str(x)} for i, x in enumerate(items)], None
    return [], None


def _parse_number(s):
    import re
    found = re.findall(r"[\d.,]+", str(s))
    if not found:
        return None
    num = max(found, key=len)
    if "." in num and "," in num:
        if num.rfind(".") > num.rfind(","):
            num = num.replace(",", "")
        else:
            num = num.replace(".", "").replace(",", ".")
    elif num.count(".") > 1:
        num = num.replace(".", "")
    elif num.count(",") > 1:
        num = num.replace(",", "")
    elif "," in num:
        num = num.replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def _tender_value(tender, valoare_estimata):
    v = tender.get("value_amount")
    if v:
        return float(v), tender.get("value_currency")
    if valoare_estimata:
        return _parse_number(valoare_estimata), None
    return None, None


def _qty(value):
    try:
        return int(str(value).split()[0])
    except (ValueError, IndexError, AttributeError):
        return 1


def _catalog_index(catalog):
    return {str(p.get("id")): p for p in catalog if p.get("id") is not None}


def produce_supplier_matches(requirements, catalog, gateway, config, hint=None):
    system = config.get("suppliers.match_prompt", DEFAULT_MATCH_PROMPT)
    if hint:
        system = system + "\n\nINDICAȚIE: " + hint
    body = ("CERINȚE:\n" + json.dumps(requirements, ensure_ascii=False)
            + "\n\n=====\n\nCATALOG:\n" + json.dumps(catalog, ensure_ascii=False))
    r = gateway.complete("suppliers", system, [{"role": "user", "content": body}],
                         max_tokens=int(config.get("suppliers.max_output_tokens", 2048)),
                         prefill="{")
    parsed = loads_loose(r["text"])
    return {"status": "ok" if parsed is not None else "parse_error",
            "matches": (parsed or {}).get("matches", []) if isinstance(parsed, dict) else [],
            "raw": r["text"], "source_text": body,
            "model": r["model"], "cost": r["cost"],
            "tokens": r["input_tokens"] + r["output_tokens"]}


def _to_currency(amount, from_cur, to_cur, fx_rates):
    if amount is None:
        return None
    if not from_cur or not to_cur or from_cur == to_cur:
        return amount
    key = f"{from_cur}->{to_cur}"
    rate = fx_rates.get(key)
    if rate is None:
        inv = fx_rates.get(f"{to_cur}->{from_cur}")
        rate = (1.0 / inv) if inv else None
    return amount * rate if rate else None


def compute_costs(requirements, matches, catalog, tender_value, tender_currency=None,
                  fx_rates=None):
    fx_rates = fx_rates or {}
    cat = _catalog_index(catalog)
    by_req = {m.get("req_index"): m for m in matches if isinstance(m, dict)}
    items = []
    total = 0.0
    target_cur = tender_currency
    matched = 0
    unmatched = 0
    fx_incomplete = False
    for req in requirements:
        idx = req["index"]
        m = by_req.get(idx, {})
        cid = m.get("catalog_id")
        product = cat.get(str(cid)) if cid is not None else None
        qty = _qty(req.get("cantitate"))
        if product:
            price = float(product.get("price") or 0)
            prod_cur = product.get("currency")
            line = price * qty
            if target_cur is None:
                target_cur = prod_cur
            line_conv = _to_currency(line, prod_cur, target_cur, fx_rates)
            if line_conv is None:
                fx_incomplete = True
                line_conv = line
            total += line_conv
            matched += 1
            items.append({"requirement": req.get("denumire"), "supplier": product.get("supplier"),
                          "model": product.get("model"), "unit_price": price,
                          "currency": prod_cur, "quantity": qty,
                          "line_cost": line, "line_cost_converted": line_conv,
                          "spec_fit": m.get("spec_fit"), "confidence": m.get("confidence"),
                          "source": "catalog", "note": m.get("note")})
        else:
            unmatched += 1
            items.append({"requirement": req.get("denumire"), "supplier": None,
                          "quantity": qty, "spec_fit": "none", "source": "none",
                          "note": m.get("note")})
    margin = None
    if tender_value and target_cur:
        margin = (tender_value - total) / tender_value
    return {"items": items, "total_cost": total, "tender_value": tender_value,
            "currency": target_cur, "margin": margin,
            "margin_partial": unmatched > 0 or fx_incomplete,
            "fx_incomplete": fx_incomplete,
            "matched_count": matched, "unmatched_count": unmatched}


def _store_suppliers(conn, tender_id, summary, model, tokens, cost):
    conn.execute("DELETE FROM suppliers WHERE tender_id = ?", (tender_id,))
    conn.execute(
        "INSERT INTO suppliers(tender_id, items_json, total_cost, tender_value, currency, "
        "margin, matched_count, unmatched_count, margin_partial, model, tokens, cost, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (tender_id, json.dumps(summary["items"], ensure_ascii=False), summary["total_cost"],
         summary["tender_value"], summary["currency"], summary["margin"],
         summary["matched_count"], summary["unmatched_count"],
         1 if summary.get("margin_partial") else 0, model, tokens, cost, time.time()))
    conn.commit()


@register("suppliers")
class SuppliersStage(Stage):
    consumes = ("tender",)
    produces = ("suppliers",)

    def run(self, ctx: StageContext) -> StageResult:
        tender = ctx.payload.get("tender") or {}
        tender_id = ctx.payload.get("tender_id") or ctx.tender_id
        gw = LLMGateway(ctx.config, ctx.db)
        catalog = ctx.config.get("suppliers.catalog", [])

        requirements, valoare = _load_requirements(ctx.db, int(tender_id))
        tender_value, currency = _tender_value(tender, valoare)
        from workflows.trace import log_steps
        if not requirements:
            log_steps(ctx.db, int(tender_id), "suppliers", [
                ("Load requirements", "no equipment items found in the extraction"),
                ("Stop", "nothing to price — tender has no equipment requirements")])
            return StageResult(payload={**ctx.payload,
                                        "suppliers": {"status": "no_requirements"}})

        out = produce_supplier_matches(requirements, catalog, gw, ctx.config)
        if out["status"] != "ok":
            if tender_id is not None:
                log_steps(ctx.db, int(tender_id), "suppliers", [
                    ("Load requirements", f"{len(requirements)} item(s)"),
                    ("Match to catalog", "model output could not be parsed (parse_error)")])
                flag_parse_failure(ctx.db, int(tender_id), "suppliers", out["raw"])
            return StageResult(payload={**ctx.payload,
                                        "suppliers": {"status": "parse_error"}})

        fx_rates = ctx.config.get("suppliers.fx_rates", {})
        summary = compute_costs(requirements, out["matches"], catalog, tender_value,
                                tender_currency=currency, fx_rates=fx_rates)
        if tender_id is not None:
            _store_suppliers(ctx.db, int(tender_id), summary, out["model"],
                             out["tokens"], out["cost"])
            margin_txt = (f"{summary['margin']*100:.1f}%" if summary["margin"] is not None
                          else "n/a (no value or currency)")
            log_steps(ctx.db, int(tender_id), "suppliers", [
                ("Load requirements",
                 f"{len(requirements)} equipment item(s); tender value "
                 f"{tender_value} {currency or '?'}"),
                ("Match to catalog",
                 f"{summary['matched_count']} matched, {summary['unmatched_count']} unmatched "
                 f"(model {out['model']})"),
                ("Compute cost",
                 f"total {summary['total_cost']:.2f} {summary['currency'] or ''}"
                 + (" · FX rate missing for some items" if summary.get("fx_incomplete") else "")),
                ("Margin", margin_txt
                 + (" (partial — unmatched items)" if summary.get("margin_partial") else ""))])
            if summary["unmatched_count"] > 0 or summary["fx_incomplete"]:
                from workflows.verify import _store_verification
                note = []
                if summary["unmatched_count"] > 0:
                    note.append(f"{summary['unmatched_count']} echipamente fără furnizor în catalog")
                if summary["fx_incomplete"]:
                    note.append("curs valutar lipsă pentru conversie - marjă pe valute diferite")
                _store_verification(ctx.db, int(tender_id), "suppliers",
                                    {"status": "issues", "issues": note, "missing": [],
                                     "confidence": 0.0, "model": None, "tokens": 0, "cost": 0},
                                    0, True)

        return StageResult(
            payload={**ctx.payload, "suppliers": {"status": "ok", **summary},
                     "suppliers_source": out["source_text"],
                     "_supplier_matches": out["matches"], "_requirements": requirements,
                     "_catalog": catalog},
            metrics={"tokens": out["tokens"], "cost": out["cost"]})


@register("suppliers_verify")
class SuppliersVerifyStage(Stage):
    consumes = ("suppliers",)
    produces = ("suppliers_verification",)

    def run(self, ctx: StageContext) -> StageResult:
        tender_id = ctx.payload.get("tender_id") or ctx.tender_id
        suppliers = ctx.payload.get("suppliers") or {}
        source_text = ctx.payload.get("suppliers_source") or ""
        gw = LLMGateway(ctx.config, ctx.db)

        if suppliers.get("status") != "ok" or not source_text:
            return StageResult(payload={**ctx.payload,
                                        "suppliers_verification": {"status": "skipped"}})

        strictness = ctx.config.get("verify.strictness", "strict")
        threshold = float(ctx.config.get("verify.flag_confidence_threshold", 0.6))
        prompt = ctx.config.get("verify.suppliers_prompt", DEFAULT_VERIFY_PROMPT)
        matches = ctx.payload.get("_supplier_matches", [])

        result = verify_against_source(gw, ctx.config, source_text, matches, prompt)
        action = decide_action(result, strictness, threshold)
        needs_review = action in ("retry", "flag")
        if tender_id is not None:
            _store_verification(ctx.db, int(tender_id), "suppliers", result, 0, needs_review)

        return StageResult(
            payload={**ctx.payload, "suppliers_verification": {
                "status": result["status"], "issues": result["issues"],
                "needs_review": needs_review}},
            metrics={"tokens": result["tokens"], "cost": result["cost"]})
