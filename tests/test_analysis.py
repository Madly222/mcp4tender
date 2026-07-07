from __future__ import annotations

import json
import json as _json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db, run_collector
from engine.config_store import ConfigStore
import workflows  # noqa: F401
import workflows.collectors.genericweb as gw
from workflows.analysis import clear_irrelevant, funnel_counts, run_triage

DEFAULTS = Path(__file__).resolve().parent.parent / "config" / "defaults"


def seeded(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.seed_defaults(DEFAULTS)
    store.set("llm.provider", "stub")
    return conn, store


def _add_tender(conn, ext, status="new", title="Camere de supraveghere video"):
    now = time.time()
    nj = json.dumps({"title": title, "buyer": "STISC"}, ensure_ascii=False)
    conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES('genericweb',?,?,?,?,?,?)",
        (ext, "h-" + ext, nj, status, now, now))
    conn.commit()
    return conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]


def test_funnel_counts(tmp_path):
    conn, store = seeded(tmp_path)
    _add_tender(conn, "a", status="new")
    _add_tender(conn, "b", status="analyzed")
    f = funnel_counts(conn)
    assert f["total"] == 2
    assert f["new"] == 1
    assert f["analyzed"] == 1


def test_run_triage_moves_new_to_triaged(tmp_path):
    conn, store = seeded(tmp_path)
    _add_tender(conn, "a", status="new")
    summary = run_triage(store, conn)
    assert summary["total"] == 1
    row = conn.execute("SELECT status FROM tenders WHERE external_id='a'").fetchone()
    assert row["status"] in ("triaged", "failed")
    assert row["status"] == "triaged"


def test_clear_irrelevant_purges_and_suppresses(tmp_path):
    conn, store = seeded(tmp_path)
    tid = _add_tender(conn, "x", status="analyzed")
    conn.execute(
        "INSERT INTO verdicts(tender_id, stage_name, verdict, score, reason, model, created_at) "
        "VALUES(?,'applicability','cannot',10,'{}','stub',?)", (tid, time.time()))
    conn.commit()
    removed = clear_irrelevant(conn)
    assert removed == 1
    assert conn.execute("SELECT COUNT(*) c FROM tenders").fetchone()["c"] == 0
    assert conn.execute(
        "SELECT 1 FROM dismissed_tenders WHERE external_id='x'").fetchone() is not None


def test_dismissed_not_recollected(tmp_path, monkeypatch):
    conn, store = seeded(tmp_path)
    conn.execute("INSERT INTO dismissed_tenders(external_id) VALUES('s1:"
                 + gw.hashlib.sha1(b'https://a.md/t/1').hexdigest()[:16] + "')")
    conn.commit()
    store.set("sources.genericweb", {"enabled": True})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md", "enabled": True}])
    monkeypatch.setattr(gw, "get_text", lambda url, timeout=30, headers=None: "x")
    monkeypatch.setattr(gw, "_extract",
                        lambda *a, **k: ([{"title": "T", "url": "https://a.md/t/1"}], None, None))
    r = run_collector("genericweb", store, conn, params={"mode": "backfill"})
    assert r["new"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM tenders").fetchone()["c"] == 0


def test_external_id_prefers_ref_over_title():
    a = gw._external_id("s1", {"title": "T", "ref": "OCDS-123"})
    b = gw._external_id("s1", {"title": "Different title", "ref": "OCDS-123"})
    assert a == b
    c = gw._external_id("s1", {"title": "T", "url": "https://a.md/1", "ref": "OCDS-123"})
    assert c != a


def test_url_validation():
    import pytest
    pytest.importorskip("fastapi")
    from web.routes_sites import _validate_url
    assert _validate_url("https://a.md/tenders")[0] is True
    assert _validate_url("a.md/tenders")[0] is False
    assert _validate_url("ftp://a.md")[0] is False
    assert _validate_url("")[0] is False


def test_wipe_collected(tmp_path):
    conn, store = seeded(tmp_path)
    _add_tender(conn, "g1", status="new")
    tid = _add_tender(conn, "g2", status="analyzed")
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,reason,model,created_at) "
                 "VALUES(?,'applicability','can',1,'{}','s',0)", (tid,))
    conn.execute("INSERT INTO crawl_state(site_id,total_collected,total_estimate,next_url) "
                 "VALUES('s1',5,100,'u')")
    conn.commit()
    from workflows.analysis import wipe_collected
    n = wipe_collected(conn, source="genericweb", forget=True)
    assert n == 2
    assert conn.execute("SELECT COUNT(*) c FROM tenders").fetchone()["c"] == 0
    cs = conn.execute("SELECT total_collected, next_url FROM crawl_state WHERE site_id='s1'").fetchone()
    assert cs["total_collected"] == 0 and cs["next_url"] is None


def test_store_verdict_never_null(tmp_path):
    conn, _ = seeded(tmp_path)
    from workflows.applicability import _store_verdict
    now = time.time()
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                 "status,created_at,updated_at) VALUES('genericweb','a','h','{}','extracted',?,?)",
                 (now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id='a'").fetchone()["id"]
    _store_verdict(conn, tid, "not-a-dict", "m")
    v1 = conn.execute("SELECT verdict FROM verdicts WHERE tender_id=?", (tid,)).fetchone()["verdict"]
    _store_verdict(conn, tid, {"readiness_score": 50}, "m")
    v2 = conn.execute("SELECT verdict FROM verdicts WHERE tender_id=?", (tid,)).fetchone()["verdict"]
    assert v1 == "unknown" and v2 == "unknown"


def test_reset_analysis_requeues(tmp_path):
    conn, _ = seeded(tmp_path)
    from workflows.analysis import reset_analysis
    now = time.time()
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                 "status,created_at,updated_at) VALUES('genericweb','b','h','{}','analyzed',?,?)",
                 (now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id='b'").fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,created_at) VALUES(?,?,?,?)",
                 (tid, "applicability", "can", now))
    conn.commit()
    n = reset_analysis(conn)
    assert n == 1
    assert conn.execute("SELECT status FROM tenders WHERE id=?", (tid,)).fetchone()["status"] == "new"
    assert conn.execute("SELECT COUNT(*) c FROM verdicts").fetchone()["c"] == 0


def test_requeue_failed(tmp_path):
    conn, _ = seeded(tmp_path)
    from workflows.analysis import requeue_failed
    now = time.time()
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                 "status,created_at,updated_at) VALUES('mtender','f1','h','{}','failed',?,?)",
                 (now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id='f1'").fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,created_at) VALUES(?,?,?,?)",
                 (tid, "triage", "relevant", now))
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                 "status,created_at,updated_at) VALUES('mtender','f2','h','{}','failed',?,?)",
                 (now, now))
    conn.commit()
    n = requeue_failed(conn)
    assert n == 2
    s1 = conn.execute("SELECT status FROM tenders WHERE external_id='f1'").fetchone()["status"]
    s2 = conn.execute("SELECT status FROM tenders WHERE external_id='f2'").fetchone()["status"]
    assert s1 == "triaged" and s2 == "new"


def test_dedupe_mtender_merges_stage_copies(tmp_path):
    conn, _ = seeded(tmp_path)
    from workflows.analysis import dedupe_mtender
    now = time.time()
    base = "ocds-b3wdp1-MD-1782112506384"

    def add(ext, title, val, status):
        conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                     "status,created_at,updated_at) VALUES('mtender',?,?,?,?,?,?)",
                     (ext, ext, _json.dumps({"title": title, "value_amount": val}),
                      status, now, now))
    add(base, None, None, "new")
    add(base + "-EI-1782112506385", "SERVICII DE TELECOMUNICATII", 169.35, "extracted")
    add(base + "-AC-1700000000000", None, None, "new")
    conn.commit()
    removed = dedupe_mtender(conn)
    assert removed == 2
    rows = conn.execute("SELECT external_id, normalized_json FROM tenders "
                        "WHERE source='mtender'").fetchall()
    assert len(rows) == 1
    assert rows[0]["external_id"] == base
    assert _json.loads(rows[0]["normalized_json"])["title"] == "SERVICII DE TELECOMUNICATII"


def _full_tender(conn, ext, status):
    now = time.time()
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                 "status,created_at,updated_at) VALUES('mtender',?,?,?,?,?,?)",
                 (ext, ext, "{}", status, now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,created_at) VALUES(?,?,?,?)",
                 (tid, "triage", "relevant", now))
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,created_at) VALUES(?,?,?,?)",
                 (tid, "applicability", "can", now))
    conn.execute("INSERT INTO extractions(tender_id,fields_json,model,method,cost,created_at) "
                 "VALUES(?,?,?,?,?,?)", (tid, "{}", "m", "llm", 0, now))
    conn.execute("INSERT INTO suppliers(tender_id,items_json,margin,created_at) VALUES(?,?,?,?)",
                 (tid, "[]", 0.2, now))
    conn.commit()
    return tid


def _counts(conn):
    def c(q, *a):
        return conn.execute(q, a).fetchone()[0]
    return {
        "status": conn.execute("SELECT status FROM tenders").fetchone()["status"],
        "triage": c("SELECT COUNT(*) FROM verdicts WHERE stage_name='triage'"),
        "appl": c("SELECT COUNT(*) FROM verdicts WHERE stage_name='applicability'"),
        "extract": c("SELECT COUNT(*) FROM extractions"),
        "suppliers": c("SELECT COUNT(*) FROM suppliers"),
    }


def test_clear_stage_suppliers(tmp_path):
    conn, _ = seeded(tmp_path)
    from workflows.analysis import clear_stage
    _full_tender(conn, "t1", "sourced")
    assert clear_stage(conn, "suppliers") == 1
    c = _counts(conn)
    assert c["status"] == "analyzed" and c["suppliers"] == 0
    assert c["appl"] == 1 and c["extract"] == 1 and c["triage"] == 1


def test_clear_stage_applicability_cascades_suppliers(tmp_path):
    conn, _ = seeded(tmp_path)
    from workflows.analysis import clear_stage
    _full_tender(conn, "t1", "sourced")
    assert clear_stage(conn, "applicability") == 1
    c = _counts(conn)
    assert c["status"] == "extracted" and c["suppliers"] == 0 and c["appl"] == 0
    assert c["extract"] == 1 and c["triage"] == 1


def test_clear_stage_extract_cascades_downstream(tmp_path):
    conn, _ = seeded(tmp_path)
    from workflows.analysis import clear_stage
    _full_tender(conn, "t1", "analyzed")
    assert clear_stage(conn, "extract") == 1
    c = _counts(conn)
    assert c["status"] == "triaged" and c["extract"] == 0 and c["appl"] == 0 and c["suppliers"] == 0
    assert c["triage"] == 1


def test_clear_stage_triage_resets_all(tmp_path):
    conn, _ = seeded(tmp_path)
    from workflows.analysis import clear_stage
    _full_tender(conn, "t1", "sourced")
    assert clear_stage(conn, "triage") == 1
    c = _counts(conn)
    assert c["status"] == "new"
    assert c["triage"] == 0 and c["appl"] == 0 and c["extract"] == 0 and c["suppliers"] == 0


def test_triage_excludes_buyer_name(tmp_path):
    conn, store = seeded(tmp_path)
    from workflows.triage import score_tender, bucket_for
    tender = {"title": "deservirea tehnica a aparatelor de aer conditionat",
              "buyer": "Batalion de comunicatii si aparare cibernetica",
              "cpv": [{"id": "50800000-3"}], "value_amount": 41666}
    score, reasons = score_tender(tender, store)
    assert bucket_for(score, store) != "relevant"
    assert not any(r["type"] == "keyword" and r["key"] == "cibernetic" for r in reasons)


def test_applicability_trace_captures_llm_io(tmp_path):
    conn, store = seeded(tmp_path)
    from workflows.applicability import produce_applicability

    class GW:
        def complete(self, *a, **k):
            return {"text": '{"can_execute":"can","readiness_score":80}', "model": "m",
                    "input_tokens": 10, "output_tokens": 5, "cost": 0.01}

    out = produce_applicability({"title": "CCTV"}, {"obiect": "cctv"}, "relevant", GW(), store)
    labels = [s[0] for s in out["steps"]]
    assert "Model input · system prompt" in labels
    assert "Model input · content sent" in labels
    assert "Model output · raw response" in labels


def test_cpv_alone_does_not_make_relevant(tmp_path):
    conn, store = seeded(tmp_path)
    from workflows.triage import score_tender, bucket_for
    # CPV 32 (+3) but a generic title with no keyword -> must NOT be relevant
    t = {"title": "Achizitionarea de echipamente", "cpv": [{"id": "32000000-3"}]}
    score, reasons = score_tender(t, store)
    hk = any(r.get("type") == "keyword" and (r.get("w") or 0) > 0 for r in reasons)
    assert bucket_for(score, store, hk) != "relevant"
    # CPV 32 + a subject keyword -> relevant
    t2 = {"title": "Achizitie router de retea", "cpv": [{"id": "32000000-3"}]}
    s2, r2 = score_tender(t2, store)
    hk2 = any(r.get("type") == "keyword" and (r.get("w") or 0) > 0 for r in r2)
    assert bucket_for(s2, store, hk2) == "relevant"
