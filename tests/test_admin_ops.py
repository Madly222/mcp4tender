import json
import time

from engine import db
from workflows.analysis import wipe_all


def _conn(tmp_path):
    conn = db.connect(str(tmp_path / "t.db"))
    db.init_schema(conn)
    return conn


def test_wipe_all_clears_tenders_and_resets_cursor(tmp_path):
    conn = _conn(tmp_path)
    now = time.time()
    conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        ("genericweb", "s:1", "h", json.dumps({"title": "A", "buyer": "B"}), "new", now, now))
    conn.execute(
        "INSERT INTO raw_documents(source, external_id, content_hash, fetched_at, payload_json) "
        "VALUES(?,?,?,?,?)", ("genericweb", "s:1", "h", now, "{}"))
    conn.execute(
        "INSERT INTO crawl_state(site_id, next_url, total_collected, exhausted) VALUES(?,?,?,?)",
        ("s", "https://x/page2", 40, 1))
    conn.commit()

    removed = wipe_all(conn)
    assert removed == 1
    assert conn.execute("SELECT COUNT(*) c FROM tenders").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM raw_documents").fetchone()["c"] == 0
    cs = conn.execute("SELECT next_url, total_collected, exhausted FROM crawl_state").fetchone()
    assert cs["next_url"] is None and cs["total_collected"] == 0 and cs["exhausted"] == 0


def test_wipe_all_keeps_dismissed_by_default(tmp_path):
    conn = _conn(tmp_path)
    conn.execute("INSERT INTO dismissed_tenders(source, external_id) VALUES(?,?)",
                 ("genericweb", "s:9"))
    conn.commit()
    wipe_all(conn)
    assert conn.execute("SELECT COUNT(*) c FROM dismissed_tenders").fetchone()["c"] == 1
    wipe_all(conn, forget=True)
    assert conn.execute("SELECT COUNT(*) c FROM dismissed_tenders").fetchone()["c"] == 0
