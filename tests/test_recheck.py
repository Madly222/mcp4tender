import json
import time

from engine import db
from workflows.recheck import run_recheck


class FakeStore:
    def get(self, key, default=None):
        return default


class FakeGW:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete(self, stage, system, messages, max_tokens=200, prefill=None):
        self.calls += 1
        return {"text": json.dumps(self.payload)}


def _conn(tmp_path):
    conn = db.connect(str(tmp_path / "t.db"))
    db.init_schema(conn)
    return conn


def _add(conn, tid, url, verdict="can"):
    now = time.time()
    conn.execute(
        "INSERT INTO tenders(id, source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (tid, "genericweb", f"achizitii:{tid}", f"h{tid}",
         json.dumps({"title": f"T{tid}", "buyer": "B", "url": url}), "new", now, now))
    conn.execute(
        "INSERT INTO verdicts(tender_id, stage_name, verdict, score, created_at) "
        "VALUES(?,?,?,?,?)", (tid, "applicability", verdict, 1.0, now))
    conn.commit()


def _nj(conn, tid):
    return json.loads(conn.execute(
        "SELECT normalized_json FROM tenders WHERE id=?", (tid,)).fetchone()["normalized_json"])


def test_scope_only_relevant(tmp_path):
    conn = _conn(tmp_path)
    _add(conn, 1, "https://achizitii.md/t/1", verdict="can")
    _add(conn, 2, "https://achizitii.md/t/2", verdict="no")
    fetched = []
    run_recheck(FakeStore(), conn, fetch=lambda u: fetched.append(u) or "page",
                gw=FakeGW({"status": "open"}))
    assert fetched == ["https://achizitii.md/t/1"]


def test_marks_cancelled(tmp_path):
    conn = _conn(tmp_path)
    _add(conn, 1, "https://achizitii.md/t/1")
    run_recheck(FakeStore(), conn, fetch=lambda u: "the page says Anulat",
                gw=FakeGW({"cancelled": True, "status": "Anulat"}))
    nj = _nj(conn, 1)
    assert nj["status"] == "cancelled" and nj["status_details"] == "Anulat"


def test_marks_awarded(tmp_path):
    conn = _conn(tmp_path)
    _add(conn, 1, "https://achizitii.md/t/1")
    run_recheck(FakeStore(), conn, fetch=lambda u: "winner announced",
                gw=FakeGW({"awarded": True}))
    assert _nj(conn, 1).get("awarded") is True


def test_unchanged_page_skips_llm(tmp_path):
    conn = _conn(tmp_path)
    _add(conn, 1, "https://achizitii.md/t/1")
    gw = FakeGW({"status": "open"})
    run_recheck(FakeStore(), conn, fetch=lambda u: "same page", gw=gw)
    stats = run_recheck(FakeStore(), conn, fetch=lambda u: "same page", gw=gw)
    assert gw.calls == 1 and stats["unchanged"] == 1


def test_no_url_is_skipped(tmp_path):
    conn = _conn(tmp_path)
    now = time.time()
    conn.execute(
        "INSERT INTO tenders(id, source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (1, "genericweb", "achizitii:1", "h", json.dumps({"title": "T", "buyer": "B"}),
         "new", now, now))
    conn.execute("INSERT INTO verdicts(tender_id, stage_name, verdict, score, created_at) "
                 "VALUES(?,?,?,?,?)", (1, "applicability", "can", 1.0, now))
    conn.commit()
    gw = FakeGW({"status": "open"})
    stats = run_recheck(FakeStore(), conn, fetch=lambda u: "x", gw=gw)
    assert stats["skip"] == 1 and gw.calls == 0


def test_closed_tender_is_not_fetched(tmp_path):
    conn = _conn(tmp_path)
    now = time.time()
    conn.execute(
        "INSERT INTO tenders(id, source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (9, "genericweb", "achizitii:9", "h9",
         json.dumps({"title": "T9", "buyer": "B", "url": "https://achizitii.md/t/9",
                     "status": "cancelled"}), "new", now, now))
    conn.execute(
        "INSERT INTO verdicts(tender_id, stage_name, verdict, score, created_at) "
        "VALUES(?,?,?,?,?)", (9, "applicability", "can", 1.0, now))
    conn.commit()
    gw = FakeGW({"status": "open"})
    fetched = {"n": 0}

    def fetch(url):
        fetched["n"] += 1
        return "page"

    stats = run_recheck(FakeStore(), conn, fetch=fetch, gw=gw)
    assert stats["closed"] == 1
    assert fetched["n"] == 0
    assert gw.calls == 0


def test_past_deadline_tender_is_not_fetched(tmp_path):
    conn = _conn(tmp_path)
    now = time.time()
    conn.execute(
        "INSERT INTO tenders(id, source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (8, "genericweb", "achizitii:8", "h8",
         json.dumps({"title": "T8", "buyer": "B", "url": "https://achizitii.md/t/8",
                     "deadline": "2020-01-01"}), "new", now, now))
    conn.execute(
        "INSERT INTO verdicts(tender_id, stage_name, verdict, score, created_at) "
        "VALUES(?,?,?,?,?)", (8, "applicability", "can", 1.0, now))
    conn.commit()
    gw = FakeGW({"status": "open"})
    stats = run_recheck(FakeStore(), conn, fetch=lambda u: "page", gw=gw)
    assert stats["closed"] == 1
    assert gw.calls == 0


def test_dynamic_html_noise_does_not_defeat_the_hash(tmp_path):
    conn = _conn(tmp_path)
    _add(conn, 7, "https://achizitii.md/t/7")
    gw = FakeGW({"status": "open"})
    pages = ['<script>var t=111</script><p>Tender body</p>',
             '<script>var t=222</script><p>Tender body</p>']

    def fetch(url):
        return pages.pop(0)

    run_recheck(FakeStore(), conn, fetch=fetch, gw=gw)
    stats = run_recheck(FakeStore(), conn, fetch=fetch, gw=gw)
    assert gw.calls == 1
    assert stats["unchanged"] == 1
