from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db
from engine.config_store import ConfigStore
from engine.llm import LLMGateway
import workflows  # noqa: F401
import workflows.supervisor as sv
import workflows.applicability as ap


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("llm.provider", "stub")
    store.set("supervisor.autonomy", "auto")
    store.set("supervisor.rank_weights", {"score": 0.6, "margin": 0.4})
    return conn, store


def seed_full(conn, title, score, verdict, margin, unmatched=0, status="sourced"):
    now = time.time()
    nj = json.dumps({"title": title, "buyer": "MAI"}, ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        ("t", title, title, nj, status, now, now))
    tid = cur.lastrowid
    conn.execute(
        "INSERT INTO verdicts(tender_id, stage_name, verdict, score, confidence, reason, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (tid, "applicability", verdict, score, 0.8,
         json.dumps({"gaps": ["gap A", "gap B"]}), now))
    conn.execute(
        "INSERT INTO extractions(tender_id, fields_json, method, created_at) VALUES(?,?,?,?)",
        (tid, json.dumps({"termen_livrare": "120 zile"}), "text", now))
    conn.execute(
        "INSERT INTO suppliers(tender_id, total_cost, tender_value, currency, margin, "
        "matched_count, unmatched_count, margin_partial, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (tid, 1000, 5000, "MDL", margin, 2, unmatched, 1 if unmatched else 0, now))
    conn.commit()
    return tid


def test_digest_ranks_by_score_and_margin(tmp_path):
    conn, store = fresh(tmp_path)
    low = seed_full(conn, "Low", score=50, verdict="partial", margin=0.2)
    high = seed_full(conn, "High", score=90, verdict="can", margin=0.5)
    digest = sv.build_digest(conn, store)
    assert digest[0]["tender_id"] == high
    assert digest[-1]["tender_id"] == low
    assert digest[0]["rank_score"] > digest[-1]["rank_score"]


def test_digest_excludes_cannot(tmp_path):
    conn, store = fresh(tmp_path)
    seed_full(conn, "Nope", score=80, verdict="cannot", margin=0.4)
    seed_full(conn, "Yes", score=70, verdict="can", margin=0.4)
    digest = sv.build_digest(conn, store)
    assert len(digest) == 1
    assert digest[0]["title"] == "Yes"


def test_coverage_detects_stale(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("supervisor.coverage_stale_hours", 24)
    old = time.time() - 72 * 3600
    conn.execute(
        "INSERT INTO source_runs(source, started_at, finished_at, fetched, new_items, status) "
        "VALUES(?,?,?,?,?,?)", ("mtender", old, old, 100, 5, "ok"))
    conn.commit()
    cov = sv.check_coverage(conn, store)
    assert any("mtender" in w for w in cov["warnings"])


def test_coverage_done_status_is_healthy(tmp_path):
    conn, store = fresh(tmp_path)
    now = time.time()
    conn.execute(
        "INSERT INTO source_runs(source, started_at, fetched, new_items, status) "
        "VALUES(?,?,?,?,?)", ("mtender", now, 100, 50, "done"))
    conn.commit()
    cov = sv.check_coverage(conn, store)
    assert not any("status=done" in w for w in cov["warnings"])


def test_coverage_detects_drop(tmp_path):
    conn, store = fresh(tmp_path)
    now = time.time()
    for n in [50, 48, 52, 49]:
        conn.execute(
            "INSERT INTO source_runs(source, started_at, fetched, new_items, status) "
            "VALUES(?,?,?,?,?)", ("mtender", now, 100, n, "ok"))
    conn.execute(
        "INSERT INTO source_runs(source, started_at, fetched, new_items, status) "
        "VALUES(?,?,?,?,?)", ("mtender", now, 100, 2, "ok"))
    conn.commit()
    cov = sv.check_coverage(conn, store)
    assert any("sharp drop" in w for w in cov["warnings"])


def test_escalation_advisory_does_not_spend(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("supervisor.autonomy", "advise")
    tid = seed_full(conn, "Flagged", score=55, verdict="partial", margin=0.3)
    conn.execute(
        "INSERT INTO verifications(tender_id, stage, status, needs_review, created_at) "
        "VALUES(?,?,?,?,?)", (tid, "applicability", "issues", 1, time.time()))
    conn.commit()
    out = sv.run_escalations(conn, store)
    assert out["spent"] == 0
    assert len(out["human_needed"]) == 1


def test_escalation_suppliers_always_human(tmp_path):
    conn, store = fresh(tmp_path)
    tid = seed_full(conn, "Gap", score=60, verdict="partial", margin=0.4, unmatched=1)
    conn.execute(
        "INSERT INTO verifications(tender_id, stage, status, needs_review, created_at) "
        "VALUES(?,?,?,?,?)", (tid, "suppliers", "issues", 1, time.time()))
    conn.commit()
    out = sv.run_escalations(conn, store)
    assert out["spent"] == 0
    assert out["human_needed"][0]["stage"] == "suppliers"


def test_escalation_auto_applicability(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    tid = seed_full(conn, "Borderline", score=55, verdict="partial", margin=0.3)
    conn.execute(
        "INSERT INTO verifications(tender_id, stage, status, needs_review, created_at) "
        "VALUES(?,?,?,?,?)", (tid, "applicability", "issues", 1, time.time()))
    conn.commit()

    def fake_produce(tender, extraction, bucket, gw, store, hint=None):
        assert gw.model_override.get("applicability") == "claude-opus-4-8"
        return {"status": "ok", "verdict": {"can_execute": "can", "readiness_score": 88,
                                            "confidence": 0.95, "reasoning": "x",
                                            "matched": [], "gaps": [], "required_equipment": []},
                "source_text": "ctx", "model": "claude-opus-4-8", "cost": 0.05, "tokens": 500}

    def fake_verify(gw, store, src, produced, prompt, model_stage="verify"):
        return {"status": "ok", "issues": [], "missing": [], "confidence": 0.95,
                "cost": 0.001, "tokens": 50, "model": "haiku"}

    monkeypatch.setattr(ap, "produce_applicability", fake_produce)
    monkeypatch.setattr(sv, "verify_against_source", fake_verify)
    out = sv.run_escalations(conn, store)
    assert out["spent"] == 1
    assert len(out["done"]) == 1
    assert out["done"][0]["resolved"] is True
    st = conn.execute("SELECT status FROM tenders WHERE id=?", (tid,)).fetchone()["status"]
    assert st != "needs_review"


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
