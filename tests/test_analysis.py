from __future__ import annotations

import json
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
