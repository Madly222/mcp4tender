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
import workflows.applicability as ap


PROFILE = {"company": "Rapid Link", "vendor_partnerships": {"Cisco": "net"},
           "verticals": ["video surveillance", "ANPR"]}


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("pipeline.tender_applicability", ["applicability", "applicability_verify"])
    store.set("pipeline.appl_only", ["applicability"])
    store.set("llm.provider", "stub")
    store.set("capabilities.profile", PROFILE)
    store.set("applicability.model_by_bucket",
              {"relevant": "applicability", "gray": "applicability_gray"})
    store.set("llm.models", {"applicability": "claude-sonnet-4-6",
                             "applicability_gray": "claude-haiku-4-5-20251001",
                             "verify": "claude-haiku-4-5-20251001"})
    store.set("verify.strictness", "strict")
    return conn, store


def seed_tender(conn, title, cpv, bucket="relevant", status="extracted"):
    now = time.time()
    nj = json.dumps({"ocid": "x", "title": title, "value_amount": 1000000,
                     "cpv": [{"id": cpv}]}, ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        ("t", title, "h", nj, status, now, now))
    tid = cur.lastrowid
    conn.execute(
        "INSERT INTO verdicts(tender_id, stage_name, verdict, score, created_at) "
        "VALUES(?,?,?,?,?)", (tid, "triage", bucket, 5, now))
    conn.execute(
        "INSERT INTO extractions(tender_id, fields_json, method, created_at) VALUES(?,?,?,?)",
        (tid, json.dumps({"obiect": title, "echipamente": []}), "text", now))
    conn.commit()
    return tid


class VerdictProvider:
    name = "v"; available = True

    def __init__(self, can="can", score=80, conf=0.9):
        self.can, self.score, self.conf = can, score, conf
        self.models_used = []

    def generate(self, model, system, messages, max_tokens):
        self.models_used.append(model)
        body = {"can_execute": self.can, "readiness_score": self.score,
                "confidence": self.conf, "reasoning": "ok", "matched": ["Cisco"],
                "gaps": [], "required_equipment": ["camera"]}
        return {"text": json.dumps(body), "input_tokens": 200, "output_tokens": 100}


def test_produce_applicability(tmp_path):
    conn, store = fresh(tmp_path)
    gw = LLMGateway(store, conn, provider=VerdictProvider(can="can", score=85))
    out = ap.produce_applicability({"title": "ANPR"}, {"echipamente": []}, "relevant", gw, store)
    assert out["status"] == "ok"
    assert out["verdict"]["can_execute"] == "can"
    assert out["verdict"]["readiness_score"] == 85


def test_model_by_bucket(tmp_path):
    conn, store = fresh(tmp_path)
    prov = VerdictProvider()
    gw = LLMGateway(store, conn, provider=prov)
    ap.produce_applicability({"title": "x"}, None, "relevant", gw, store)
    ap.produce_applicability({"title": "x"}, None, "gray", gw, store)
    assert "claude-sonnet-4-6" in prov.models_used
    assert "claude-haiku-4-5-20251001" in prov.models_used


def test_applicability_stage_stores_verdict(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    tid = seed_tender(conn, "ANPR cameras", "35125300-2")
    monkeypatch.setattr(ap, "LLMGateway",
                        lambda store, conn: LLMGateway(store, conn,
                                                       provider=VerdictProvider(can="partial", score=60)))
    tender = json.loads(conn.execute("SELECT normalized_json FROM tenders WHERE id=?", (tid,)).fetchone()[0])
    r = run_pipeline("pipeline.appl_only", store, conn,
                     initial_payload={"tender": tender, "tender_id": tid}, tender_id=tid)
    assert r["status"] == "done"
    v = conn.execute("SELECT verdict, score FROM verdicts WHERE tender_id=? AND stage_name='applicability'",
                     (tid,)).fetchone()
    assert v["verdict"] == "partial"
    assert v["score"] == 60


def test_applicability_verify_pass_on_confident(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    tid = seed_tender(conn, "ANPR", "35125300-2")

    class VProv:
        name = "v"; available = True
        def __init__(self):
            self.n = 0
        def generate(self, model, system, messages, max_tokens):
            self.n += 1
            if "applicability" in system.lower() or "PROFIL" in messages[0]["content"]:
                return {"text": json.dumps({"can_execute": "can", "readiness_score": 80,
                                            "confidence": 0.9, "reasoning": "x",
                                            "matched": [], "gaps": [], "required_equipment": []}),
                        "input_tokens": 100, "output_tokens": 50}
            return {"text": json.dumps({"status": "ok", "issues": [], "missing": [],
                                        "confidence": 0.9}), "input_tokens": 50, "output_tokens": 20}

    monkeypatch.setattr(ap, "LLMGateway",
                        lambda store, conn: LLMGateway(store, conn, provider=VProv()))
    tender = json.loads(conn.execute("SELECT normalized_json FROM tenders WHERE id=?", (tid,)).fetchone()[0])
    run_pipeline("pipeline.tender_applicability", store, conn,
                 initial_payload={"tender": tender, "tender_id": tid}, tender_id=tid)
    ver = conn.execute("SELECT needs_review FROM verifications WHERE tender_id=? AND stage='applicability'",
                       (tid,)).fetchone()
    assert ver["needs_review"] == 0


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
