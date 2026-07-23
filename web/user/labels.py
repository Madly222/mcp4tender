from __future__ import annotations

import re

# Keyed by the FULL config key on purpose: max_output_tokens exists under four different
# prefixes and means something different in each. Never key these by the stem.
LABELS = {
    "notify.email.enabled": "Send by email",
    "notify.email.host": "Mail server (host or IP)",
    "notify.email.port": "Mail server port",
    "notify.email.tls": "Use STARTTLS",
    "notify.email.login": "Mail login",
    "notify.email.from": "Send from (address)",
    "notify.email.to": "Send to (comma-separated addresses)",
    "notify.message.block_text": "Message: include the short text block",
    "notify.message.block_analysis": "Message: attach the full analysis report",
    "notify.text.buyer": "Text block: who is buying",
    "notify.text.value": "Text block: tender value",
    "notify.text.deadline": "Text block: submission deadline",
    "notify.text.verdict": "Text block: can-we-do-it verdict",
    "notify.text.rating": "Text block: overall fit rating",
    "notify.text.link": "Text block: link to the tender",
    "notify.telegram.enabled": "Send to Telegram",
    "notify.telegram.chat_id": "Telegram chat or group ID",
    "analyze.batch_size": "Tenders analysed per run",
    "collect.max_age_days": "Ignore tenders older than",

    "applicability.max_extraction_chars": "How much of the spec the model reads",
    "applicability.max_output_tokens": "Length limit on the fit verdict",
    "applicability.proceed_verdicts": "Verdicts worth costing out",
    "llm.cache_enabled": "Reuse identical answers",
    "llm.provider": "AI provider",

    "documents.cache_dir": "Where downloaded documents are kept",
    "documents.max_docs_per_tender": "Documents read per tender",
    "documents.max_pages_ocr": "Pages sent to OCR per document",
    "documents.ocr_max_tokens": "Length limit on OCR output",
    "documents.ocr_prompt": "Instructions given to the OCR model",
    "documents.read_types": "File types worth opening",
    "documents.scanned_threshold": "When a PDF counts as scanned",
    "documents.skip_formats": "File types never opened",
    "documents.timeout": "Give up downloading after",
    "documents.vision_enabled": "Read scanned pages as images",

    "extract.fallback_tail_chars": "Fallback: characters taken from the end",
    "extract.max_output_tokens": "Length limit on extracted fields",
    "extract.max_section_chars": "Longest section handed to the model",
    "extract.min_offset_ratio": "How far in a section may start",
    "extract.section_markers": "Words that start the useful section",
    "extract.section_prefix_chars": "Characters kept before a marker",
    "extract.skip_title_patterns": "Document titles never read",
    "extract.slice_min_chars": "Shortest slice worth sending",

    "verify.flag_confidence_threshold": "Flag an answer below this confidence",
    "verify.max_output_tokens": "Length limit on the check",
    "verify.max_retries": "Retries when a check fails",
    "verify.max_source_chars": "Source text given to the checker",
    "verify.strictness": "How strict the checker is",

    "results.new_days": "Drop undecided tenders from the inbox after",
    "results.archive_after_days": "Move to the archive after",
    "results.closed_statuses": "Statuses that mean bidding is over",
    "results.pending_statuses": "Statuses that mean bidding has not started",

    "suppliers.margin_min": "Minimum margin worth bidding",
    "suppliers.max_output_tokens": "Length limit on the costing",
    "suppliers.proceed_verdicts": "Verdicts that reach costing",
    "suppliers.web_enabled": "Look up prices on the web",

    "runtime.mode": "Run mode",
    "runtime.max_retries": "Retries before a stage gives up",
    "runtime.retry_backoff": "Wait between retries",
    "log.level": "How much gets logged",

    "pipeline.tender_triage": "Pipeline: first pass",
    "pipeline.tender_extract": "Pipeline: reading documents",
    "pipeline.tender_applicability": "Pipeline: can we do it",
    "pipeline.tender_suppliers": "Pipeline: costing",
    "pipeline.demo": "Pipeline: demo",

    "supervisor.autonomy": "How much the supervisor may do alone",
    "supervisor.coverage_drop_ratio": "Alert if coverage falls by",
    "supervisor.coverage_ok_statuses": "Statuses that count as covered",
    "supervisor.coverage_stale_hours": "Alert if nothing ran for",
    "supervisor.digest_verdicts": "Verdicts included in the digest",
    "supervisor.escalate_stages": "Stages worth escalating",
    "supervisor.escalation_model": "Model used when escalating",
    "supervisor.max_escalations": "Escalations allowed per run",

    "dummy.message": "Demo message",
    "dummy.flaky_fail_times": "Demo: fail this many times",
}

_ACRONYMS = {"ocr": "OCR", "llm": "AI", "url": "URL", "api": "API", "cpv": "CPV",
             "fx": "FX", "id": "ID", "js": "JS"}


def humanize(key):
    """Fallback for a key nobody has named yet.

    Deliberately imperfect: it exists so a new config key still reads as words instead of
    a variable name. If you add a key, add a real label above rather than lean on this.
    """
    stem = key.split(".", 1)[1] if "." in key else key
    words = re.split(r"[_\-.]+", stem)
    out = [_ACRONYMS.get(w.lower(), w) for w in words if w]
    if not out:
        return key
    first = out[0]
    if first not in _ACRONYMS.values():
        first = first[:1].upper() + first[1:]
    return " ".join([first] + [w if w in _ACRONYMS.values() else w.lower() for w in out[1:]])


def label_of(key):
    return LABELS.get(key) or humanize(key)
