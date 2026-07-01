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
import workflows.suppliers as sup
from workflows.suppliers import compute_costs, _qty, _tender_value


CATALOG = [
    {"id": "cam1", "supplier": "Jenoptik", "model": "VECTOR", "price": 2800,
     "currency": "EUR", "specs": "ANPR 4K"},
    {"id": "sw1", "supplier": "Rapid Link", "model": "Cisco CBS350", "price": 650,
     "currency": "EUR", "specs": "PoE++"},
]


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("pipeline.tender_suppliers", ["suppliers", "suppliers_verify"])
    store.set("pipeline.sup_only", ["suppliers"])
    store.set("llm.provider", "stub")
    store.set("suppliers.catalog", CATALOG)
    store.set("llm.models", {"suppliers": "claude-haiku-4-5-20251001",
                             "verify": "claude-haiku-4-5-20251001"})
    return conn, store


def test_qty_parsing():
    assert _qty(25) == 25
    assert _qty("18") == 18
    assert _qty("16 buc") == 16
    assert _qty(None) == 1


def test_tender_value_from_amount():
    v, c = _tender_value({"value_amount": 5400000, "value_currency": "MDL"}, None)
    assert v == 5400000.0
    assert c == "MDL"


def test_tender_value_from_estimate_string():
    v, _ = _tender_value({}, "5.400.000 MDL")
    assert v == 5400000.0


def test_compute_costs_and_margin():
    reqs = [{"index": 0, "denumire": "ANPR", "cantitate": 10},
            {"index": 1, "denumire": "Switch", "cantitate": 4},
            {"index": 2, "denumire": "Mystery", "cantitate": 1}]
    matches = [{"req_index": 0, "catalog_id": "cam1", "spec_fit": "full", "confidence": 0.9},
               {"req_index": 1, "catalog_id": "sw1", "spec_fit": "full", "confidence": 0.9},
               {"req_index": 2, "catalog_id": None, "spec_fit": "none", "confidence": 0.8}]
    summary = compute_costs(reqs, matches, CATALOG, tender_value=50000, tender_currency="EUR")
    assert summary["total_cost"] == 10 * 2800 + 4 * 650
    assert summary["matched_count"] == 2
    assert summary["unmatched_count"] == 1
    assert summary["margin_partial"] is True  # one unmatched item
    expected_margin = (50000 - 30600) / 50000
    assert abs(summary["margin"] - expected_margin) < 1e-9


def test_fx_normalization():
    reqs = [{"index": 0, "denumire": "ANPR", "cantitate": 1}]
    matches = [{"req_index": 0, "catalog_id": "cam1", "spec_fit": "full", "confidence": 0.9}]
    # catalog price 2800 EUR, tender in MDL, rate 19.6 -> 54880 MDL
    summary = compute_costs(reqs, matches, CATALOG, tender_value=5400000,
                            tender_currency="MDL", fx_rates={"EUR->MDL": 19.6})
    assert abs(summary["total_cost"] - 2800 * 19.6) < 1e-6
    assert summary["currency"] == "MDL"
    assert summary["fx_incomplete"] is False
    expected = (5400000 - 2800 * 19.6) / 5400000
    assert abs(summary["margin"] - expected) < 1e-9


def test_fx_missing_rate_flags_incomplete():
    reqs = [{"index": 0, "denumire": "ANPR", "cantitate": 1}]
    matches = [{"req_index": 0, "catalog_id": "cam1", "spec_fit": "full", "confidence": 0.9}]
    summary = compute_costs(reqs, matches, CATALOG, tender_value=5400000,
                            tender_currency="MDL", fx_rates={})
    assert summary["fx_incomplete"] is True
    assert summary["margin_partial"] is True


def test_fx_inverse_rate():
    from workflows.suppliers import _to_currency
    assert abs(_to_currency(100, "MDL", "EUR", {"EUR->MDL": 20.0}) - 5.0) < 1e-9


def test_compute_costs_no_tender_value():
    reqs = [{"index": 0, "denumire": "ANPR", "cantitate": 1}]
    matches = [{"req_index": 0, "catalog_id": "cam1", "spec_fit": "full", "confidence": 0.9}]
    summary = compute_costs(reqs, matches, CATALOG, tender_value=None, tender_currency='EUR')
    assert summary["margin"] is None
    assert summary["total_cost"] == 2800


def _seed(conn, echipamente, value_amount=None):
    now = time.time()
    nj = json.dumps({"title": "t", "value_amount": value_amount}, ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        ("t", "x", "h", nj, "analyzed", now, now))
    tid = cur.lastrowid
    conn.execute(
        "INSERT INTO extractions(tender_id, fields_json, method, created_at) VALUES(?,?,?,?)",
        (tid, json.dumps({"echipamente": echipamente, "valoare_estimata": None}), "text", now))
    conn.commit()
    return tid


def test_suppliers_stage(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    tid = _seed(conn, [{"denumire": "ANPR", "cantitate": 10},
                       {"denumire": "Switch", "cantitate": 4}], value_amount=50000)

    class MatchProvider:
        name = "m"; available = True
        def generate(self, model, system, messages, max_tokens):
            return {"text": json.dumps({"matches": [
                {"req_index": 0, "catalog_id": "cam1", "spec_fit": "full", "confidence": 0.9},
                {"req_index": 1, "catalog_id": "sw1", "spec_fit": "full", "confidence": 0.9}]}),
                "input_tokens": 100, "output_tokens": 50}

    monkeypatch.setattr(sup, "LLMGateway",
                        lambda store, conn: LLMGateway(store, conn, provider=MatchProvider()))
    tender = json.loads(conn.execute("SELECT normalized_json FROM tenders WHERE id=?", (tid,)).fetchone()[0])
    r = run_pipeline("pipeline.sup_only", store, conn,
                     initial_payload={"tender": tender, "tender_id": tid}, tender_id=tid)
    assert r["status"] == "done"
    row = conn.execute("SELECT total_cost, margin, matched_count FROM suppliers WHERE tender_id=?",
                       (tid,)).fetchone()
    assert row["total_cost"] == 30600
    assert row["matched_count"] == 2
    assert abs(row["margin"] - (50000 - 30600) / 50000) < 1e-9


def test_suppliers_no_requirements(tmp_path):
    conn, store = fresh(tmp_path)
    tid = _seed(conn, [], value_amount=50000)
    tender = json.loads(conn.execute("SELECT normalized_json FROM tenders WHERE id=?", (tid,)).fetchone()[0])
    r = run_pipeline("pipeline.sup_only", store, conn,
                     initial_payload={"tender": tender, "tender_id": tid}, tender_id=tid)
    assert r["status"] == "done"
    row = conn.execute("SELECT id FROM suppliers WHERE tender_id=?", (tid,)).fetchone()
    assert row is None


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
