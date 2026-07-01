from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db
from engine.config_store import ConfigStore
from engine.llm import LLMGateway
from engine.runner import run_pipeline
import workflows  # noqa: F401
import workflows.verify as vfy
from workflows.verify import decide_action, verify_against_source


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("pipeline.tender_extract", ["extract", "extract_verify"])
    store.set("pipeline.verify_only", ["extract_verify"])
    store.set("llm.provider", "stub")
    store.set("verify.strictness", "strict")
    store.set("verify.max_retries", 1)
    return conn, store


def seed_tender(conn):
    now = time.time()
    cur = conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        ("t", "x", "h", json.dumps({"documents": []}), "triaged", now, now))
    conn.commit()
    return cur.lastrowid


def test_decide_action_strict():
    assert decide_action({"missing": ["v"], "issues": []}, "strict") == "retry"
    assert decide_action({"missing": [], "issues": ["x"]}, "strict") == "retry"
    assert decide_action({"missing": [], "issues": []}, "strict") == "pass"


def test_decide_action_balanced():
    assert decide_action({"missing": ["v"], "issues": []}, "balanced") == "retry"
    assert decide_action({"missing": [], "issues": ["x"]}, "balanced") == "flag"
    assert decide_action({"missing": [], "issues": []}, "balanced") == "pass"


def test_decide_action_light():
    assert decide_action({"missing": ["v"], "issues": []}, "light") == "flag"
    assert decide_action({"missing": [], "issues": []}, "light") == "pass"


def test_confidence_threshold_suppresses_nitpicks():
    # high-confidence issues with no missing => verifier is sure these are nitpicks => pass
    hi = {"missing": [], "issues": ["nitpick"], "confidence": 0.82}
    assert decide_action(hi, "strict", 0.6) == "pass"
    # low-confidence issues => still acted on
    lo = {"missing": [], "issues": ["maybe real"], "confidence": 0.3}
    assert decide_action(lo, "strict", 0.6) == "retry"
    # missing always acts regardless of confidence
    miss = {"missing": ["valoare"], "issues": [], "confidence": 0.99}
    assert decide_action(miss, "strict", 0.6) == "retry"


def test_verify_against_source(tmp_path):
    conn, store = fresh(tmp_path)

    class P:
        name = "p"; available = True
        def generate(self, model, system, messages, max_tokens):
            return {"text": json.dumps({"status": "issues", "issues": ["a"],
                                        "missing": ["valoare_estimata"], "confidence": 0.5}),
                    "input_tokens": 10, "output_tokens": 5}

    gw = LLMGateway(store, conn, provider=P())
    r = verify_against_source(gw, store, "source", {"x": 1}, "prompt")
    assert r["status"] == "issues"
    assert "valoare_estimata" in r["missing"]


def test_verifier_retry_fixes(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    tid = seed_tender(conn)

    class VProvider:
        name = "v"; available = True
        def __init__(self):
            self.calls = 0
        def generate(self, model, system, messages, max_tokens):
            self.calls += 1
            if self.calls == 1:
                body = {"status": "issues", "issues": [], "missing": ["valoare_estimata"],
                        "confidence": 0.6}
            else:
                body = {"status": "ok", "issues": [], "missing": [], "confidence": 0.95}
            return {"text": json.dumps(body), "input_tokens": 20, "output_tokens": 10}

    monkeypatch.setattr(vfy, "LLMGateway",
                        lambda store, conn: LLMGateway(store, conn, provider=VProvider()))
    monkeypatch.setattr(vfy, "produce_extraction",
                        lambda tender, gw, cfg, hint=None: {
                            "status": "ok",
                            "fields": {"obiect": "x", "valoare_estimata": "100000 MDL"},
                            "sources": [], "source_text": "src", "method": "text",
                            "model": "haiku", "cost": 0.001, "tokens": 100})

    payload = {"tender": {"documents": []}, "tender_id": tid,
               "extraction": {"status": "ok",
                              "fields": {"obiect": "x", "valoare_estimata": None}},
               "extract_source": "text cu valoare estimata 100000 MDL"}
    r = run_pipeline("pipeline.verify_only", store, conn, initial_payload=payload,
                     tender_id=tid)
    assert r["status"] == "done"
    v = conn.execute("SELECT retries, needs_review FROM verifications WHERE tender_id=?",
                     (tid,)).fetchone()
    assert v["retries"] == 1
    assert v["needs_review"] == 0


def test_verifier_flags_when_unfixable(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    tid = seed_tender(conn)

    class AlwaysIssues:
        name = "v"; available = True
        def generate(self, model, system, messages, max_tokens):
            return {"text": json.dumps({"status": "issues", "issues": [],
                                        "missing": ["valoare_estimata"], "confidence": 0.4}),
                    "input_tokens": 20, "output_tokens": 10}

    monkeypatch.setattr(vfy, "LLMGateway",
                        lambda store, conn: LLMGateway(store, conn, provider=AlwaysIssues()))
    monkeypatch.setattr(vfy, "produce_extraction",
                        lambda tender, gw, cfg, hint=None: {
                            "status": "ok", "fields": {"obiect": "x", "valoare_estimata": None},
                            "sources": [], "source_text": "src", "method": "text",
                            "model": "haiku", "cost": 0.001, "tokens": 100})

    payload = {"tender": {"documents": []}, "tender_id": tid,
               "extraction": {"status": "ok", "fields": {"valoare_estimata": None}},
               "extract_source": "source text"}
    run_pipeline("pipeline.verify_only", store, conn, initial_payload=payload, tender_id=tid)
    v = conn.execute("SELECT needs_review FROM verifications WHERE tender_id=?", (tid,)).fetchone()
    assert v["needs_review"] == 1
    status = conn.execute("SELECT status FROM tenders WHERE id=?", (tid,)).fetchone()["status"]
    assert status == "needs_review"


if __name__ == "__main__":
    import tempfile

    class MP:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)

    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as d:
                argn = fn.__code__.co_varnames[:fn.__code__.co_argcount]
                args = [Path(d) if a == "tmp_path" else MP() for a in argn]
                try:
                    fn(*args)
                    print(f"PASS {name}")
                except Exception as exc:
                    print(f"FAIL {name}: {exc}")
                    raise
    print("all tests passed")
