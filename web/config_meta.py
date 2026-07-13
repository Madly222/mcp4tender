from __future__ import annotations

CONFIG_META = {
    "runtime.mode": "Label stored in the 'mode' column of every pipeline run record. Cosmetic only; does not change behaviour.",
    "runtime.max_retries": "How many times a failed pipeline stage is retried before the whole run is marked failed.",
    "runtime.retry_backoff": "Seconds to wait between stage retries (works together with runtime.max_retries).",
    "dummy.message": "Text returned by the built-in demo pipeline's echo stage. Demo/testing only.",
    "dummy.flaky_fail_times": "Number of times the demo 'flaky' stage fails before succeeding. Demo/testing only.",
    "log.level": "Logging verbosity for the process: DEBUG, INFO, WARNING, ERROR. Logs go to stdout/stderr (journalctl under systemd). DEBUG shows per-page fetch sizes and parsed item counts.",

    "pipeline.demo": "Ordered list of stage names executed by the demo pipeline.",
    "pipeline.tender_triage": "Ordered list of stages for the triage pipeline (relevance scoring).",
    "pipeline.tender_extract": "Ordered list of stages for the document-extraction pipeline.",
    "pipeline.tender_applicability": "Ordered list of stages for the applicability (can-we-win) pipeline.",
    "pipeline.tender_suppliers": "Ordered list of stages for the supplier-sourcing pipeline.",

    "schedule.timezone": "IANA timezone the scheduler uses to decide when jobs run, e.g. 'Europe/Chisinau'. Empty = server local time.",
    "schedule.jobs": "Jobs run by the background scheduler. Pipeline job: {pipeline, at:[HH:MM], enabled}. Collect job: {kind:'collect', sources:[mtender,genericweb], days:[0-6 or mon..sun, empty=every day], at:[HH:MM], analyze:true, enabled}. Max 24 times/day; each collect run fetches incrementally and (analyze=true) runs triage..suppliers on pending items (batch = analyze.batch_size).",

    "results.new_days": "How many days a tender stays in the 'New' tab after it was first found. Only incremental daily finds can be 'New'.",
    "results.archive_after_days": "A tender is archived once its submission deadline has passed, or - when it has no deadline - once it is older than this many days (by publication date, or found date if none). A tender with a future deadline is never archived by age. Archived tenders are kept, never deleted.",
    "collect.max_age_days": "Hard ceiling for collection. A tender is skipped at collect time if its deadline has already passed, or - when it has no deadline - if it is older than this many days. The effective ceiling is the smaller of this and results.archive_after_days, so a historical back-fill never stores tenders that would land straight in Archive. Undated tenders are always kept.",

    "triage.cpv_weights": "Score added per CPV code prefix; the longest matching prefix wins. Positive = relevant category, negative = penalised.",
    "triage.keyword_weights": "Score added when a keyword (case-insensitive substring) appears in title+description+buyer. Negative values penalise.",
    "triage.value_band": "Tender-value scoring: 'min' is the threshold; 'weight_below_min' is the penalty applied when the estimated value is below min.",
    "triage.bucket_thresholds": "Score cut-offs mapping a triage score to a bucket: score >= relevant -> 'relevant', >= gray -> 'gray', otherwise dropped.",

    "llm.provider": "LLM backend. 'auto' = Anthropic if ANTHROPIC_API_KEY is set, else stub. 'anthropic' = force real API. 'stub' = no API, placeholder output.",
    "llm.models": "Model id used per stage. Keys are stage names (extract, ocr, verify, applicability, suppliers...); 'default' is the fallback.",
    "llm.pricing": "USD price per 1,000,000 tokens for each model ({in, out}). Used only to compute the cost figures shown for each call.",
    "llm.cache_enabled": "Cache identical LLM calls in the database so repeated calls are free and instant.",

    "documents.cache_dir": "Directory where downloaded tender documents are cached on disk.",
    "documents.timeout": "HTTP timeout (seconds) when downloading a tender document.",
    "documents.read_types": "Only documents whose type is in this list are read (e.g. biddingDocuments, tenderNotice).",
    "documents.skip_formats": "Document formats skipped entirely, by lowercase file extension.",
    "documents.vision_enabled": "Allow vision/OCR on scanned PDFs that contain little extractable text.",
    "documents.scanned_threshold": "If a PDF page yields fewer characters than this, it is treated as scanned and sent to OCR.",
    "documents.max_pages_ocr": "Maximum number of pages OCR'd per document.",
    "documents.ocr_max_tokens": "Maximum output tokens for the OCR/vision transcription call.",
    "documents.max_docs_per_tender": "Maximum number of documents read per tender.",
    "documents.ocr_prompt": "Prompt used to transcribe scanned documents via vision/OCR.",

    "extract.slice_min_chars": "If the document text is shorter than this, the whole document is sent to the model instead of slicing to a section.",
    "extract.min_offset_ratio": "A matched technical section is only used if it starts past this fraction of the document (avoids matching the table of contents).",
    "extract.max_section_chars": "Maximum characters of a matched section sent to the model.",
    "extract.section_prefix_chars": "Characters of context kept before a matched section marker.",
    "extract.fallback_tail_chars": "If no section marker is found, send this many characters from the end of the document.",
    "extract.skip_title_patterns": "Documents whose title contains any of these substrings are skipped (e.g. 'duae').",
    "extract.max_output_tokens": "Maximum output tokens for the field-extraction call.",
    "extract.section_markers": "Phrases that mark the start of the technical-requirements section inside a tender document.",

    "verify.strictness": "Verification strictness. 'strict' flags more results for human review.",
    "verify.max_retries": "How many times extraction is retried when verification fails.",
    "verify.flag_confidence_threshold": "Verification confidence below this value flags the result for human review.",
    "verify.max_source_chars": "Maximum characters of source text sent to the verification call.",
    "verify.max_output_tokens": "Maximum output tokens for verification calls.",

    "applicability.max_output_tokens": "Maximum output tokens for the applicability (can-we-win) call.",
    "applicability.max_extraction_chars": "Maximum characters of the extracted fields passed into the applicability call.",
    "applicability.proceed_verdicts": "Applicability verdicts considered worth pursuing; used downstream for suppliers and the digest.",
    "applicability.model_by_bucket": "Which model alias (from llm.models) to use per triage bucket for the applicability stage.",
    "capabilities.profile": "Your company profile (capabilities, certifications, partnerships, references) given to the model to judge whether you can deliver a tender.",

    "suppliers.web_enabled": "Allow supplier sourcing to use web search (when implemented). Off = catalog + LLM only.",
    "suppliers.margin_min": "Minimum acceptable margin (0.15 = 15%). Informational threshold surfaced in the digest.",
    "suppliers.max_output_tokens": "Maximum output tokens for the supplier-matching call.",
    "suppliers.proceed_verdicts": "Applicability verdicts that qualify a tender for supplier sourcing.",
    "suppliers.catalog": "Your known products/suppliers with prices; the model matches tender items against these entries.",
    "suppliers.fx_rates": "Currency conversion rates to MDL, used to compute cost and margin.",

    "supervisor.autonomy": "'auto' = the super-agent may auto-resolve flagged tenders; any other value = advisory only (a human handles them).",
    "supervisor.escalation_model": "Stronger model used when auto-resolving a flagged tender.",
    "supervisor.escalate_stages": "Which stages the super-agent is allowed to auto-resolve.",
    "supervisor.max_escalations": "Maximum number of auto-resolutions per supervise run (budget).",
    "supervisor.rank_weights": "Weights for the digest ranking score: 'score' x readiness + 'margin' x (margin percent).",
    "supervisor.digest_verdicts": "Applicability verdicts included in the digest.",
    "supervisor.coverage_stale_hours": "Warn if a source has not collected anything for more than this many hours.",
    "supervisor.coverage_drop_ratio": "Warn if a source's latest new-item count drops below this fraction of its recent average.",
    "supervisor.coverage_ok_statuses": "Source-run statuses treated as healthy; any other status triggers a coverage warning.",

    "web.host": "Network interface the web server binds to. 0.0.0.0 = all interfaces.",
    "web.port": "TCP port the web server listens on.",
    "web.token": "Access token for the web UI. Empty = open access. The env var TENDERENGINE_WEB_TOKEN overrides this value.",
    "web.read_only": "When on, the web UI hides every edit control and rejects all changes.",
    "web.run_scheduler": "Run the background job scheduler inside the web process ('app.py web').",
    "web.require_checks": "Refuse to start the web server if startup checks fail.",
    "web.digest_limit": "Maximum number of tenders shown on the digest home page.",
    "web.title": "Title shown in the web UI header and the browser tab.",
    "web.allow_restart": "Show the 'Restart service' button in the web UI. The process exits cleanly and systemd (Restart=always) starts it again with the new code.",

    "sources.mtender": "MTender (OCDS API) source: enabled, list_url, record_url_template, timeout, page_limit, max_records_per_run, backfill_days.",
    "sources.genericweb": "Generic web crawler for the user-defined tender sites. 'enabled' turns it on/off. The crawler is given only a base URL and finds the 'next page' link itself. max_input_chars caps page text sent to the model; max_output_tokens caps the JSON returned; max_pages_per_run caps pages per 'Collect next batch'; incremental_max_pages caps pages for a 'Check new' run; fallback_batch is the absolute count used when a site's total can't be estimated. engine='builtin' (plain fetch, optional Playwright JS) or 'crawl4ai' (uses the Crawl4AI library: always renders JS and returns clean content); wait_ms is the render settle time.",
    "sites.tenders": "Tender sites to crawl (managed on the Sites page). Each entry: label, url (base listing URL), enabled, step_percent (% of the estimated total to pull per batch). The crawl position and any login are stored separately, not here.",
    "sites.partners": "Partner / supplier reference websites (managed on the Sites page). Each entry: label, url, category, notes.",
}


def describe(key):
    if key in CONFIG_META:
        return CONFIG_META[key]
    if key.startswith("sources."):
        return "Collector source settings. 'enabled' toggles the source; other fields tune fetching."
    if key.startswith("pipeline."):
        return "Ordered list of stage names executed by this pipeline."
    return ""
