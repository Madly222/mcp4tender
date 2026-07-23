from __future__ import annotations

import json

SECTIONS = [
    ("company", "Company profile", "shield",
     "Who you are and what you can deliver. The applicability analysis judges every tender "
     "against this.", ("capabilities",)),
    ("relevance", "What counts as relevant", "filter",
     "Keywords, CPV codes and value bands that decide which tenders reach you at all.",
     ("triage",)),
    ("suppliers", "Suppliers and margins", "check-circle",
     "Your catalog, currency rates and the margin below which a tender is not worth it.",
     ("suppliers",)),
    ("sources", "Where we look", "search",
     "Portals and websites that get scanned, and how far back.", ("sources", "sites", "collect")),
    ("schedule", "When we look", "clock",
     "Scan times and how much gets analysed per run.", ("schedule", "analyze")),
    ("ai", "AI models and cost", "sliders",
     "Which model runs which stage, and what it costs.", ("llm", "applicability")),
    ("reading", "Reading documents", "download",
     "How tender documents are fetched, OCR'd and cut down before the model sees them.",
     ("documents", "extract", "verify")),
    ("lists", "List behaviour", "inbox",
     "Company defaults for what counts as new and when things archive. Each person can override "
     "these in Preferences.", ("results",)),
    ("sending", "Sending results", "send",
     "Where a tender's analysis goes when you press Send — your own mail server, a Telegram "
     "group via a bot, or both.", ("notify",)),
    ("message", "What the message says", "edit",
     "Build the message the Send button ships: which blocks it has and what the short text "
     "mentions.", ("notify.message", "notify.text")),
    ("engine", "Engine internals", "alert",
     "Pipelines, retries, logging and the digest supervisor. Change with care.",
     ("runtime", "pipeline", "log", "supervisor", "dummy")),
]

ADMIN_ONLY = ("web",)

BY_ID = {s[0]: s for s in SECTIONS}


def prefix_of(key):
    return key.split(".", 1)[0]


def section_of(key):
    best, best_len = None, -1
    for sid, _label, _icon, _blurb, prefixes in SECTIONS:
        for pfx in prefixes:
            if (key == pfx or key.startswith(pfx + ".")) and len(pfx) > best_len:
                best, best_len = sid, len(pfx)
    return best


def is_admin_only(key):
    return prefix_of(key) in ADMIN_ONLY


def keys_in(store, section_id):
    return sorted(k for k in store.all() if section_of(k) == section_id)


def vtype_of(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list) and value and all(isinstance(x, str) for x in value):
        return "list_str"
    return "json"


def parse(vtype, raw):
    if vtype == "bool":
        return raw is not None and str(raw).lower() not in ("", "0", "false", "off")
    if vtype == "int":
        return int(float(str(raw).strip()))
    if vtype == "float":
        return float(str(raw).strip())
    if vtype == "str":
        return raw if raw is not None else ""
    if vtype == "list_str":
        return [s.strip() for s in str(raw or "").split(",") if s.strip()]
    parsed = json.loads(str(raw or "null"))
    if parsed is None:
        raise ValueError("empty JSON")
    return parsed
