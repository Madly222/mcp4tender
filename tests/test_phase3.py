from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db
from engine.config_store import ConfigStore
from engine.orchestrator import process_stored_tenders
from workflows.triage import score_tender, bucket_for
import workflows  # noqa: F401


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("pipeline.tender_triage", ["triage"])
    store.set("triage.cpv_weights", {"38": 2, "32": 3, "15": -3})
    store.set("triage.keyword_weights", {"spectru": 2, "dron": 3, "alimentar": -3})
    store.set("triage.value_band", {"min": 5000, "weight_below_min": -1})
    store.set("triage.bucket_thresholds", {"relevant": 3, "gray": 0.5})
    return conn, store


def insert_tender(conn, normalized, status="new"):
    now = time.time()
    cur = conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        ("t", normalized["ocid"], "h", json.dumps(normalized), status, now, now),
    )
    conn.commit()
    return cur.lastrowid


def t(ocid, title="", cpv=None, amount=100000):
    return {"ocid": ocid, "title": title, "description": "", "buyer": "",
            "value_amount": amount,
            "cpv": [{"id": c} for c in (cpv or [])]}


def test_relevant_strong_signal(tmp_path):
    _, store = fresh(tmp_path)
    score, _ = score_tender(t("x", "Analizor de spectru", ["38540000-2"]), store)
    assert score >= 3
    assert bucket_for(score, store) == "relevant"


def test_out_food(tmp_path):
    _, store = fresh(tmp_path)
    score, _ = score_tender(t("x", "Produse alimentare", ["15800000-6"], amount=200), store)
    assert bucket_for(score, store) == "out"


def test_gray_mild(tmp_path):
    _, store = fresh(tmp_path)
    score, _ = score_tender(t("x", "Echipament", ["38000000-5"], amount=100000), store)
    assert bucket_for(score, store) == "gray"


def test_value_below_min_penalty(tmp_path):
    _, store = fresh(tmp_path)
    s_big, _ = score_tender(t("x", "spectru", ["38000000-5"], amount=100000), store)
    s_small, _ = score_tender(t("x", "spectru", ["38000000-5"], amount=200), store)
    assert s_small == s_big - 1


def test_cpv_not_double_counted(tmp_path):
    _, store = fresh(tmp_path)
    score, reasons = score_tender(
        t("x", "", ["38540000-2", "38541000-9"], amount=100000), store)
    cpv_reasons = [r for r in reasons if r["type"] == "cpv"]
    assert len(cpv_reasons) == 1


def test_process_stored_writes_verdicts(tmp_path):
    conn, store = fresh(tmp_path)
    insert_tender(conn, t("a", "Analizor de spectru", ["38540000-2"]))
    insert_tender(conn, t("b", "Produse alimentare", ["15800000-6"], amount=200))
    summary = process_stored_tenders("pipeline.tender_triage", store, conn)
    assert summary["total"] == 2
    assert summary["done"] == 2
    assert summary["buckets"].get("relevant", 0) == 1
    assert summary["buckets"].get("out", 0) == 1
    verdicts = conn.execute("SELECT COUNT(*) AS c FROM verdicts WHERE stage_name='triage'").fetchone()["c"]
    assert verdicts == 2


def test_triage_never_deletes(tmp_path):
    conn, store = fresh(tmp_path)
    insert_tender(conn, t("b", "Produse alimentare", ["15800000-6"], amount=200))
    process_stored_tenders("pipeline.tender_triage", store, conn)
    count = conn.execute("SELECT COUNT(*) AS c FROM tenders").fetchone()["c"]
    assert count == 1
    status = conn.execute("SELECT status FROM tenders").fetchone()["status"]
    assert status == "triaged"


def test_reentrant_single_verdict(tmp_path):
    conn, store = fresh(tmp_path)
    tid = insert_tender(conn, t("a", "spectru", ["38540000-2"]))
    process_stored_tenders("pipeline.tender_triage", store, conn)
    conn.execute("UPDATE tenders SET status='new' WHERE id=?", (tid,))
    conn.commit()
    process_stored_tenders("pipeline.tender_triage", store, conn)
    c = conn.execute("SELECT COUNT(*) AS c FROM verdicts WHERE tender_id=? AND stage_name='triage'", (tid,)).fetchone()["c"]
    assert c == 1


if __name__ == "__main__":
    import tempfile

    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as d:
                try:
                    fn(Path(d))
                    print(f"PASS {name}")
                except Exception as exc:
                    print(f"FAIL {name}: {exc}")
                    raise
    print("all tests passed")
