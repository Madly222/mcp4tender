from __future__ import annotations

import json
import re
import time

from engine.contracts import Stage, StageContext, StageResult
from engine.documents import get_document_text
from engine.llm import LLMGateway
from engine.registry import register

_EXT_RE = re.compile(r"\.(pdf|docx|doc|odt|xlsx|xls)$", re.IGNORECASE)
_SUFFIXES = (".semnat", ".signed", ".semnată", ".semnat1")

DEFAULT_MARKERS = [
    "cerinte tehnice", "cerințe tehnice", "specificații tehnice",
    "specificatii tehnice", "caiet de sarcini", "denumirea bunurilor",
    "lista bunurilor", "parametri tehnici",
]

DEFAULT_PROMPT = (
    "Ești un analist de achiziții publice. Din textul caietului de sarcini de mai jos, "
    "extrage informația structurată. Răspunde DOAR cu un obiect JSON valid, fără markdown, "
    "cu cheile: obiect (string), cerinte_tehnice (listă de stringuri), "
    "echipamente (listă de obiecte {denumire, model, cantitate, specificatii}), "
    "termen_livrare (string), data_depunerii (string, termenul-limită de depunere a ofertelor "
    "dacă e menționat în documente, ex. '15.08.2026' sau null), "
    "criterii_calificare (listă de stringuri), "
    "valoare_estimata (string sau null). Dacă o informație lipsește, folosește null sau listă goală."
)


def _doc_base(title):
    t = (title or "").lower()
    t = _EXT_RE.sub("", t)
    for suf in _SUFFIXES:
        if t.endswith(suf):
            t = t[: -len(suf)]
    return t.strip()


def dedupe_documents(docs, prefer=("pdf", "docx", "doc")):
    def rank(fmt):
        fmt = (fmt or "").lower()
        return prefer.index(fmt) if fmt in prefer else len(prefer)

    by_base = {}
    for d in docs:
        base = _doc_base(d.get("title"))
        cur = by_base.get(base)
        if cur is None or rank(d.get("format")) < rank(cur.get("format")):
            by_base[base] = d
    return list(by_base.values())


def select_documents(tender, config):
    read_types = config.get("documents.read_types", ["biddingDocuments", "tenderNotice"])
    skip = config.get("documents.skip_formats", ["doc"])
    skip_titles = [s.lower() for s in config.get("extract.skip_title_patterns", ["duae"])]
    docs = []
    for d in tender.get("documents", []):
        if read_types and d.get("type") not in read_types:
            continue
        if (d.get("format") or "").lower() in skip:
            continue
        title = (d.get("title") or "").lower()
        if any(p in title for p in skip_titles):
            continue
        docs.append(d)
    docs = dedupe_documents(docs)
    return docs[: int(config.get("documents.max_docs_per_tender", 3))]


def extract_technical_section(text, config):
    min_chars = int(config.get("extract.slice_min_chars", 20000))
    if len(text) <= min_chars:
        return text, {"sliced": False, "reason": "short"}
    markers = config.get("extract.section_markers", DEFAULT_MARKERS)
    offset_ratio = float(config.get("extract.min_offset_ratio", 0.15))
    max_len = int(config.get("extract.max_section_chars", 120000))
    low = text.lower()
    threshold = int(len(text) * offset_ratio)
    best = None
    for m in markers:
        idx = low.find(m.lower(), threshold)
        if idx >= 0 and (best is None or idx < best):
            best = idx
    if best is None:
        tail = int(config.get("extract.fallback_tail_chars", 100000))
        return text[-tail:], {"sliced": True, "reason": "fallback_tail"}
    prefix = int(config.get("extract.section_prefix_chars", 500))
    start = max(0, best - prefix)
    return text[start:start + max_len], {"sliced": True, "reason": "marker", "offset": best}


def _parse_json(text):
    from engine.jsonutil import loads_loose
    parsed = loads_loose(text)
    return (parsed, None) if parsed is not None else (None, "json_parse_failed")


def _store_extraction(conn, tender_id, fields, sources, model, method, tokens, cost):
    if not isinstance(fields, dict):
        fields = {"raw": str(fields)[:4000]}
    conn.execute("DELETE FROM extractions WHERE tender_id = ?", (tender_id,))
    conn.execute(
        "INSERT INTO extractions(tender_id, fields_json, sources_json, model, method, "
        "tokens, cost, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (tender_id, json.dumps(fields, ensure_ascii=False),
         json.dumps(sources, ensure_ascii=False), model, method, tokens, cost, time.time()),
    )
    conn.commit()


def _fields_from_metadata(tender):
    cpv = tender.get("cpv") or []
    cpv_txt = ""
    if isinstance(cpv, list) and cpv:
        c = cpv[0] if isinstance(cpv[0], dict) else {}
        cpv_txt = " ".join(str(x) for x in (c.get("id"), c.get("description")) if x)
    obiect = tender.get("title") or tender.get("description") or ""
    if cpv_txt:
        obiect = (obiect + " — " + cpv_txt).strip(" —")
    return {"obiect": obiect,
            "valoare_estimata": tender.get("value_amount"),
            "termen_livrare": tender.get("deadline"),
            "echipamente": []}


def produce_extraction(tender, gateway, config, hint=None):
    steps = []
    docs = select_documents(tender, config)
    steps.append(("Select documents", f"{len(docs)} document(s) attached to this tender"))
    if not docs:
        steps.append(("No documents", "nothing to read — falling back to the tender's metadata"))
        f = _fields_from_metadata(tender)
        steps.append(("Build fields from metadata",
                      f"obiect from title + CPV; valoare = {f.get('valoare_estimata')}"))
        return {"status": "metadata_only", "fields": f, "sources": [], "source_text": "",
                "method": "metadata", "model": None, "cost": 0, "tokens": 0, "steps": steps}

    texts = []
    sources = []
    total_cost = 0.0
    total_tokens = 0
    method = "text"
    for d in docs:
        title = d.get("title") or d.get("url") or "document"
        r = get_document_text(d, gateway, config)
        if r.get("method") == "vision":
            method = "vision"
        total_cost += r.get("cost", 0)
        total_tokens += r.get("tokens", 0)
        section, meta = extract_technical_section(r.get("text", ""), config)
        if section.strip():
            texts.append(section)
            sources.append({"title": d.get("title"), "url": d.get("url"),
                            "chars": len(section), "slice": meta})
            steps.append(("Read document",
                          f"{title}: {len(section)} chars ({r.get('method', 'text')})"))
        else:
            steps.append(("Read document", f"{title}: no usable text found"))

    if not texts:
        steps.append(("No readable text", "documents yielded no text — using tender metadata"))
        return {"status": "metadata_only", "fields": _fields_from_metadata(tender),
                "sources": sources, "source_text": "", "method": method, "model": None,
                "cost": total_cost, "tokens": total_tokens, "steps": steps}

    source_text = "\n\n=====\n\n".join(texts)
    max_chars = int(config.get("extract.max_input_chars", 200000))
    if len(source_text) > max_chars:
        steps.append(("Truncate input",
                      f"combined {len(source_text)} chars capped to {max_chars}"))
        source_text = source_text[:max_chars]
    steps.append(("Assemble input", f"{len(source_text)} chars from {len(texts)} source(s)"))
    system = config.get("extract.prompt", DEFAULT_PROMPT)
    if hint:
        system = system + "\n\nINDICAȚIE DE VERIFICARE: " + hint
    max_tokens = int(config.get("extract.max_output_tokens", 2048))
    steps.append(("Model input · system prompt", system[:3000]))
    steps.append(("Model input · content sent (preview)", source_text[:6000]))
    r = gateway.complete("extract", system, [{"role": "user", "content": source_text}],
                         max_tokens=max_tokens, prefill="{")
    total_cost += r["cost"]
    total_tokens += r["input_tokens"] + r["output_tokens"]
    steps.append(("Call model",
                  f"{r['model']}: {r['input_tokens']}+{r['output_tokens']} tokens, "
                  f"${r['cost']:.4f}"))
    steps.append(("Model output · raw response", (r["text"] or "")[:8000]))
    fields, parse_err = _parse_json(r["text"])
    if fields is not None:
        steps.append(("Parse output", f"parsed OK — {len(fields)} field(s) extracted"))
    else:
        steps.append(("Parse output", f"could not parse JSON: {parse_err}"))

    return {"status": "ok" if fields is not None else "parse_error",
            "fields": fields if fields is not None else r["text"],
            "sources": sources, "source_text": source_text, "method": method,
            "model": r["model"], "cost": total_cost, "tokens": total_tokens,
            "parse_error": parse_err, "steps": steps}


@register("extract")
class ExtractStage(Stage):
    consumes = ("tender",)
    produces = ("extraction",)

    def run(self, ctx: StageContext) -> StageResult:
        tender = ctx.payload.get("tender") or {}
        tender_id = ctx.payload.get("tender_id") or ctx.tender_id
        gw = LLMGateway(ctx.config, ctx.db)

        out = produce_extraction(tender, gw, ctx.config)
        if tender_id is not None:
            _store_extraction(ctx.db, int(tender_id), out["fields"], out["sources"],
                              out["model"], out["method"], out["tokens"], out["cost"])
            from workflows.trace import log_steps
            log_steps(ctx.db, int(tender_id), "extract", out.get("steps"))
            if out["status"] == "parse_error":
                from workflows.verify import flag_parse_failure
                flag_parse_failure(ctx.db, int(tender_id), "extract", str(out["fields"]))

        extraction = {"status": out["status"], "fields": out["fields"],
                      "model": out["model"], "cost": out["cost"], "tokens": out["tokens"]}
        return StageResult(
            payload={**ctx.payload, "extraction": extraction,
                     "extract_source": out["source_text"]},
            metrics={"tokens": out["tokens"], "cost": out["cost"]})
