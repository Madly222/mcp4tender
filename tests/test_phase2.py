from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datetime as dt

from engine import db
from engine.config_store import ConfigStore
from engine.collectors import run_collector
import workflows  # noqa: F401
import workflows.collectors.mtender as mt


def _iso(days_from_today, hour=10):
    d = dt.date.today() + dt.timedelta(days=days_from_today)
    return f"{d.isoformat()}T{hour:02d}:00:00Z"


PUB = _iso(-5)
PUB2 = _iso(-5, 11)
DEADLINE = _iso(20)
ENQUIRY = _iso(10)
DEADLINE2 = _iso(25)


RECORD = {
    "records": [
        {"ocid": "ocds-b3wdp1-MD-1", "compiledRelease": {
            "ocid": "ocds-b3wdp1-MD-1",
            "date": PUB,
            "buyer": {"id": "MD-1", "name": "IGPF"},
            "parties": [{"id": "MD-1", "name": "IGPF", "roles": ["buyer"]}],
            "tender": {
                "id": "t1", "title": "Spectrum analyzer", "description": "Portable",
                "status": "active",
                "value": {"amount": 1500000, "currency": "MDL"},
                "procurementMethod": "open", "mainProcurementCategory": "goods",
                "classification": {"scheme": "CPV", "id": "38540000-2",
                                   "description": "Test machines"},
                "items": [{"id": "i1", "classification": {"scheme": "CPV",
                                                          "id": "38540000-2"}}],
                "tenderPeriod": {"endDate": DEADLINE},
                "enquiryPeriod": {"endDate": ENQUIRY},
                "documents": [{"id": "d1", "documentType": "tenderNotice",
                               "title": "Caiet", "format": "application/pdf",
                               "url": "https://storage.mtender.gov.md/get/abc-1"}],
            },
        }}
    ]
}

LIST = {"data": [{"ocid": "ocds-b3wdp1-MD-1", "date": PUB},
                 {"ocid": "ocds-b3wdp1-MD-2", "date": PUB2}],
        "offset": PUB2}


MULTI = {
    "records": [
        {"ocid": "ocds-b3wdp1-MD-9-plan", "compiledRelease": {
            "date": PUB,
            "planning": {},
            "parties": [{"id": "MD-9", "name": "Gimnaziul X", "roles": ["buyer"]}],
            "tender": {
                "title": "Cerneala PU Xerox", "status": "active", "method": None,
                "value": {"amount": 283.33, "currency": "MDL"},
                "procurementMethod": "limited", "mainProcurementCategory": "goods",
                "classification": {"scheme": "CPV", "id": "22600000-6",
                                   "description": "Cerneala"},
                "documents": [],
            },
        }},
        {"ocid": "ocds-b3wdp1-MD-9-notice", "compiledRelease": {
            "date": PUB2,
            "awards": [{"id": "a1"}],
            "tender": {
                "documents": [{"id": "d1", "documentType": "tenderNotice",
                               "title": "Caiet de sarcini", "format": "application/pdf",
                               "url": "https://storage.mtender.gov.md/get/xyz-1"}],
                "tenderPeriod": {"endDate": DEADLINE2},
            },
        }},
    ]
}


def fake_get_json(url, timeout=30, **kw):
    if "/tenders/ocds" in url:
        return RECORD
    return LIST


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("sources.mtender", {
        "enabled": True,
        "list_url": "https://public.mtender.gov.md/tenders",
        "record_url_template": "https://public.mtender.gov.md/tenders/{ocid}",
        "page_limit": 1, "max_records_per_run": 10, "backfill_days": 14,
    })
    return conn, store


def test_normalize_full():
    n = mt.normalize_record(RECORD, "ocds-b3wdp1-MD-1")
    assert n["title"] == "Spectrum analyzer"
    assert n["buyer"] == "IGPF"
    assert n["value_amount"] == 1500000
    assert n["value_currency"] == "MDL"
    assert n["status"] == "active"
    assert n["deadline"] == DEADLINE
    assert any(c["id"] == "38540000-2" for c in n["cpv"])
    assert len(n["documents"]) == 1


def test_normalize_sparse():
    n = mt.normalize_record({"records": [{"compiledRelease": {}}]}, "ocds-x")
    assert n["title"] is None
    assert n["value_amount"] is None
    assert n["cpv"] == []
    assert n["documents"] == []


def test_normalize_data_wrapped():
    pkg = {"data": {"records": RECORD["records"]}}
    n = mt.normalize_record(pkg, "ocds-b3wdp1-MD-1")
    assert n["title"] == "Spectrum analyzer"


def test_normalize_merges_across_records():
    n = mt.normalize_record(MULTI, "ocds-b3wdp1-MD-9")
    assert n["title"] == "Cerneala PU Xerox"
    assert n["value_amount"] == 283.33
    assert n["buyer"] == "Gimnaziul X"
    assert any(c["id"] == "22600000-6" for c in n["cpv"])
    assert len(n["documents"]) == 1
    assert n["documents"][0]["url"].endswith("xyz-1")
    assert n["deadline"] == DEADLINE2


def test_document_format_inferred_from_title():
    pkg = {"records": [{"compiledRelease": {"tender": {"documents": [
        {"id": "d1", "url": "http://storage.mtender.gov.md/get/a-1",
         "title": "Documentatia standard.docx", "documentType": "biddingDocuments"},
        {"id": "d2", "url": "http://storage.mtender.gov.md/get/a-2",
         "title": "Anunt.signed.pdf", "documentType": "tenderNotice"},
    ]}}}]}
    n = mt.normalize_record(pkg, "ocds-x")
    fmts = {d["url"][-1]: d["format"] for d in n["documents"]}
    assert fmts["1"] == "docx"
    assert fmts["2"] == "pdf"
    types = {d["type"] for d in n["documents"]}
    assert "biddingDocuments" in types


def test_renormalize_source(tmp_path):
    conn, store = fresh(tmp_path)
    mt.get_json = fake_get_json
    run_collector("mtender", store, conn)
    from engine.collectors import renormalize_source
    r = renormalize_source("mtender", store, conn)
    assert r["status"] == "done"
    assert r["updated"] == 2


def test_collector_stores_and_counts(tmp_path):
    conn, store = fresh(tmp_path)
    mt.get_json = fake_get_json
    r = run_collector("mtender", store, conn)
    assert r["status"] == "done"
    assert r["fetched"] == 2
    assert r["new"] == 2
    tenders = conn.execute("SELECT COUNT(*) AS c FROM tenders").fetchone()["c"]
    raw = conn.execute("SELECT COUNT(*) AS c FROM raw_documents").fetchone()["c"]
    assert tenders == 2 and raw == 2
    state = conn.execute("SELECT cursor FROM source_state WHERE source='mtender'").fetchone()
    assert state["cursor"] == PUB2


def test_collector_disabled(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("sources.mtender", {"enabled": False})
    r = run_collector("mtender", store, conn)
    assert r["status"] == "disabled"


def test_collector_dedup_on_repeat(tmp_path):
    conn, store = fresh(tmp_path)
    mt.get_json = fake_get_json
    run_collector("mtender", store, conn)
    r2 = run_collector("mtender", store, conn)
    assert r2["new"] == 0
    tenders = conn.execute("SELECT COUNT(*) AS c FROM tenders").fetchone()["c"]
    assert tenders == 2


def test_source_runs_logged(tmp_path):
    conn, store = fresh(tmp_path)
    mt.get_json = fake_get_json
    run_collector("mtender", store, conn)
    runs = conn.execute("SELECT status, fetched, new_items FROM source_runs").fetchall()
    assert len(runs) == 1
    assert runs[0]["status"] == "done"


if __name__ == "__main__":
    import tempfile

    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as d:
                try:
                    if fn.__code__.co_argcount:
                        fn(Path(d))
                    else:
                        fn()
                    print(f"PASS {name}")
                except Exception as exc:
                    print(f"FAIL {name}: {exc}")
                    raise
    print("all tests passed")


def test_collector_skips_expired_tenders(tmp_path, monkeypatch):
    import copy
    expired = copy.deepcopy(RECORD)
    expired["records"][0]["compiledRelease"]["tender"]["tenderPeriod"]["endDate"] = _iso(-2)
    calls = {"n": 0}

    def fake_get_json(url, timeout=30):
        if "/tenders/" in url:
            return expired
        calls["n"] += 1
        if calls["n"] > 1:
            return {"data": []}
        return {"data": [{"ocid": "ocds-b3wdp1-MD-1", "date": PUB}], "offset": PUB}

    monkeypatch.setattr(mt, "get_json", fake_get_json)
    conn = db.connect(tmp_path / "x.db"); db.init_schema(conn)
    store = ConfigStore(conn); store.reload()
    store.set("sources.mtender", {"enabled": True, "backfill_days": 30})
    store.set("results.archive_after_days", 90)
    r = run_collector("mtender", store, conn)
    assert r["new"] == 0
    assert r["too_old"] == 1
    assert conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0] == 0
