from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db, run_collector
from engine.config_store import ConfigStore
import workflows  # noqa: F401
import workflows.collectors.genericweb as gw
import workflows.collectors.genericweb_analyze as gwa


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("llm.provider", "stub")
    return conn, store


def test_html_to_text_inlines_links():
    out = gw._html_to_text(
        '<a href="/t/1">Tender A</a> mid <a href="https://x.md/2">B</a>',
        "https://a.md", 5000)
    assert "Tender A [https://a.md/t/1]" in out
    assert "B [https://x.md/2]" in out


def test_parse_value():
    assert gw._parse_value("1 200 000 MDL") == 1200000.0
    assert gw._parse_value("1.250,50") == 1250.5
    assert gw._parse_value(None) is None


def test_increment_page():
    assert gw._increment_page("https://a.md/x?page=2") == "https://a.md/x?page=3"
    assert gw._increment_page("https://a.md/x?Search.Status=0&page=9") == \
        "https://a.md/x?Search.Status=0&page=10"
    assert gw._increment_page("https://a.md/x") is None


def test_auth_headers():
    h = gw._auth_headers({"type": "basic", "user": "u", "pass": "p"})
    assert h["Authorization"] == "Basic " + base64.b64encode(b"u:p").decode()
    assert gw._auth_headers({"type": "cookie", "value": "sid=abc"})["Cookie"] == "sid=abc"
    assert gw._auth_headers(None) is None


def test_collector_disabled_by_default(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md", "enabled": True}])
    assert run_collector("genericweb", store, conn)["status"] == "disabled"


def _fake_extract(g, store, text, current_url, sc):
    import re
    m = re.search(r"page=(\d+)", current_url)
    n = int(m.group(1)) if m else 1
    if n > 5:
        return [], None, None
    nxt = f"https://a.md/list?page={n + 1}"
    return [{"title": f"T{n}", "url": f"https://a.md/t/{n}"}], nxt, None


def test_backfill_cursor_resumes(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True, "max_pages_per_run": 60, "fallback_batch": 2})
    store.set("sites.tenders", [{"id": "s1", "label": "X",
                                 "url": "https://a.md/list?page=1", "enabled": True}])
    monkeypatch.setattr(gw, "get_text", lambda url, timeout=30, headers=None: "x")
    monkeypatch.setattr(gw, "_extract", _fake_extract)

    r1 = run_collector("genericweb", store, conn, params={"mode": "backfill"})
    assert r1["new"] == 2
    cur = conn.execute("SELECT next_url, total_collected FROM crawl_state WHERE site_id='s1'").fetchone()
    assert cur["next_url"] == "https://a.md/list?page=3"
    assert cur["total_collected"] == 2

    r2 = run_collector("genericweb", store, conn, params={"mode": "backfill"})
    assert r2["new"] == 2
    cur2 = conn.execute("SELECT next_url, total_collected FROM crawl_state WHERE site_id='s1'").fetchone()
    assert cur2["next_url"] == "https://a.md/list?page=5"
    assert cur2["total_collected"] == 4
    titles = {json.loads(x["normalized_json"])["title"]
              for x in conn.execute("SELECT normalized_json FROM tenders WHERE source='genericweb'").fetchall()}
    assert {"T1", "T2", "T3", "T4"} <= titles


def test_backfill_exhausts(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True, "fallback_batch": 100})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md/list?page=1",
                                 "enabled": True}])
    monkeypatch.setattr(gw, "get_text", lambda url, timeout=30, headers=None: "x")
    monkeypatch.setattr(gw, "_extract", _fake_extract)
    run_collector("genericweb", store, conn, params={"mode": "backfill"})
    row = conn.execute("SELECT next_url, exhausted FROM crawl_state WHERE site_id='s1'").fetchone()
    assert row["exhausted"] == 1
    assert row["next_url"] is None


def test_incremental_stops_on_no_new(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True, "incremental_max_pages": 5})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md/list?page=1",
                                 "enabled": True}])
    urls = []
    monkeypatch.setattr(gw, "get_text",
                        lambda url, timeout=30, headers=None: urls.append(url) or "x")
    monkeypatch.setattr(gw, "_extract", _fake_extract)
    run_collector("genericweb", store, conn, params={"mode": "backfill"})
    n_first = len(urls)
    urls.clear()
    run_collector("genericweb", store, conn, params={"mode": "incremental"})
    assert len(urls) == 1
    assert n_first >= 1


def test_incremental_does_not_touch_backfill_cursor(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True, "fallback_batch": 2})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md/list?page=1",
                                 "enabled": True}])
    monkeypatch.setattr(gw, "get_text", lambda url, timeout=30, headers=None: "x")
    monkeypatch.setattr(gw, "_extract", _fake_extract)
    run_collector("genericweb", store, conn, params={"mode": "backfill"})
    before = conn.execute("SELECT next_url FROM crawl_state WHERE site_id='s1'").fetchone()["next_url"]
    run_collector("genericweb", store, conn, params={"mode": "incremental"})
    after = conn.execute("SELECT next_url FROM crawl_state WHERE site_id='s1'").fetchone()["next_url"]
    assert before == after


def test_collector_uses_auth_headers(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md", "enabled": True}])
    conn.execute("INSERT INTO crawl_state(site_id, auth_json) VALUES('s1',?)",
                 (json.dumps({"type": "basic", "user": "u", "pass": "p"}),))
    conn.commit()
    seen = {}
    monkeypatch.setattr(gw, "get_text",
                        lambda url, timeout=30, headers=None: seen.update(headers or {}) or "x")
    monkeypatch.setattr(gw, "_extract", lambda *a, **k: ([{"title": "T", "url": "u"}], None, None))
    run_collector("genericweb", store, conn, params={"mode": "backfill"})
    assert seen.get("Authorization", "").startswith("Basic ")


def test_extract_object(tmp_path):
    conn, store = fresh(tmp_path)

    class FakeGW:
        def complete(self, *a, **k):
            return {"text": '{"tenders":[{"title":"A","url":"u1"}],"next_page_url":"https://a.md/2","total_estimate":"1234 results"}',
                    "model": "stub", "output_tokens": 9}
    tenders, nxt, est = gw._extract(FakeGW(), store, "page", "https://a.md/1", {})
    assert tenders[0]["title"] == "A" and nxt == "https://a.md/2" and est == 1234


def test_sites_web_add_with_batch_and_login(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from web.server import create_app
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    conn, store = fresh(Path(tmp_path))
    conn.close()
    c = TestClient(create_app(p))
    c.post("/sites/add", data={"kind": "tenders", "label": "Portal",
                               "url": "https://a.md/tenders", "batch_size": "30",
                               "login": "user1", "password": "secret"},
           follow_redirects=False)
    conn2 = db.connect(p)
    s2 = ConfigStore(conn2)
    s2.reload()
    site = s2.get("sites.tenders")[0]
    assert site["batch_size"] == 30 and site["url"] == "https://a.md/tenders"
    auth = conn2.execute("SELECT auth_json FROM crawl_state WHERE site_id=?",
                         (site["id"],)).fetchone()
    assert json.loads(auth["auth_json"])["user"] == "user1"
    conn2.close()


def test_sites_web_settings_and_reset(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from web.server import create_app
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    conn, store = fresh(Path(tmp_path))
    store.set("sites.tenders", [{"id": "s1", "label": "X", "url": "https://a.md",
                                 "enabled": True, "step_percent": 10}])
    conn.execute("INSERT INTO crawl_state(site_id, next_url) VALUES('s1','https://a.md/2')")
    conn.commit()
    conn.close()
    c = TestClient(create_app(p))
    c.post("/sites/settings", data={"id": "s1", "batch_size": "35"}, follow_redirects=False)
    c.post("/sites/reset-cursor", data={"id": "s1"}, follow_redirects=False)
    conn2 = db.connect(p)
    s2 = ConfigStore(conn2)
    s2.reload()
    assert s2.get("sites.tenders")[0]["batch_size"] == 35
    cur = conn2.execute("SELECT next_url FROM crawl_state WHERE site_id='s1'").fetchone()
    assert cur["next_url"] is None
    conn2.close()


def test_sites_web_search_toggle(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from web.server import create_app
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    conn, store = fresh(Path(tmp_path))
    conn.close()
    c = TestClient(create_app(p))
    c.post("/sites/search-toggle", follow_redirects=False)
    conn2 = db.connect(p)
    s2 = ConfigStore(conn2)
    s2.reload()
    assert s2.get("sources.genericweb")["enabled"] is True
    conn2.close()


def test_estimate_mode_saves_total(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md", "enabled": True}])
    monkeypatch.setattr(gw, "get_text", lambda url, timeout=30, headers=None: "x")
    monkeypatch.setattr(gw, "_extract", lambda *a, **k: ([], None, 500))
    run_collector("genericweb", store, conn, params={"mode": "estimate"})
    row = conn.execute("SELECT total_estimate FROM crawl_state WHERE site_id='s1'").fetchone()
    assert row["total_estimate"] == 500
    assert conn.execute("SELECT COUNT(*) c FROM tenders").fetchone()["c"] == 0


def _fake_inf(g, store, text, url, sc):
    import re
    m = re.search(r"page=(\d+)", url)
    n = int(m.group(1)) if m else 1
    return [{"title": f"P{n}", "url": f"https://a.md/t/{n}"}], f"https://a.md/list?page={n + 1}", None


def test_batch_size_targets_count(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True, "max_pages_per_run": 200})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md/list?page=1",
                                 "enabled": True, "batch_size": 50}])
    monkeypatch.setattr(gw, "get_text", lambda url, timeout=30, headers=None: "x")
    monkeypatch.setattr(gw, "_extract", _fake_inf)
    r = run_collector("genericweb", store, conn, params={"mode": "backfill"})
    assert r["new"] == 50


def test_estimate_sets_js_note(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md", "enabled": True}])
    monkeypatch.setattr(gw, "get_text", lambda url, timeout=30, headers=None: "<html></html>")
    monkeypatch.setattr(gw, "_extract", lambda *a, **k: ([], None, None))
    run_collector("genericweb", store, conn, params={"mode": "estimate"})
    note = conn.execute("SELECT note FROM crawl_state WHERE site_id='s1'").fetchone()["note"]
    assert "JavaScript" in note


def test_preview_site(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True})
    monkeypatch.setattr(gw, "get_text",
                        lambda url, timeout=30, headers=None: "<a href=/t/1>Lot A</a> " + "text " * 60)
    monkeypatch.setattr(gw, "_extract",
                        lambda *a, **k: ([{"title": "Lot A", "url": "u"}], None, 12))
    from workflows.collectors.genericweb_analyze import preview_site
    r = preview_site(store, conn, "https://bank.md/achizitii")
    assert r["count"] == 1 and r["titles"] == ["Lot A"]
    assert r["estimate"] == 12 and r["rendered"] is False


def test_render_executes_js(tmp_path):
    import importlib.util
    if importlib.util.find_spec("playwright") is None:
        import pytest
        pytest.skip("playwright not installed")
    from engine.render import get_text_rendered
    f = tmp_path / "p.html"
    f.write_text("<html><body><div id=x>EMPTY</div>"
                 "<script>document.getElementById('x').textContent='INJECTED_BY_JS';</script>"
                 "</body></html>")
    try:
        html = get_text_rendered("file://" + str(f), timeout=15, wait_ms=300)
    except Exception:
        import pytest
        pytest.skip("chromium not runnable here")
    assert "INJECTED_BY_JS" in html


def test_extract_estimates_from_last_page(tmp_path):
    conn, store = fresh(tmp_path)

    class FakeGW:
        def complete(self, *a, **k):
            tenders = ",".join('{"title":"T%d","url":"u%d"}' % (i, i) for i in range(10))
            return {"text": '{"tenders":[' + tenders + '],"next_page_url":"https://a.md/2",'
                            '"total_estimate":null,"last_page":250}',
                    "model": "stub", "output_tokens": 9}
    tenders, nxt, est = gw._extract(FakeGW(), store, "page", "https://a.md/1", {})
    assert len(tenders) == 10 and est == 2500


class _FakeAnalyzeGW:
    def complete(self, *a, **k):
        return {"text": '{"page_type":"hub","has_tenders":false,"tender_count":0,'
                        '"follow":[{"label":"Tenders","url":"/tenders"},'
                        '{"label":"Documents","url":"https://x.md/docs"}],'
                        '"needs_login":false,"recommendation":"Follow the Tenders link."}',
                "model": "stub", "output_tokens": 5}


def test_analyze_site(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True})
    monkeypatch.setattr(gw, "get_text",
                        lambda url, timeout=30, headers=None: "Home page " + "text " * 90)
    monkeypatch.setattr(gwa, "LLMGateway", lambda *a, **k: _FakeAnalyzeGW())
    from workflows.collectors.genericweb_analyze import analyze_site
    r = analyze_site(store, conn, "https://org.md/")
    assert r["page_type"] == "hub" and r["has_tenders"] is False
    assert r["follow"][0]["url"] == "https://org.md/tenders"
    assert r["follow"][1]["url"] == "https://x.md/docs"
    assert r["recommendation"]


def test_web_analyze_renders(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from web.server import create_app
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    monkeypatch.setattr(gw, "get_text",
                        lambda url, timeout=30, headers=None: "Home " + "text " * 90)
    monkeypatch.setattr(gwa, "LLMGateway", lambda *a, **k: _FakeAnalyzeGW())
    p = str(tmp_path / "t.db")
    conn, store = fresh(Path(tmp_path))
    store.set("sources.genericweb", {"enabled": True})
    conn.close()
    c = TestClient(create_app(p))
    r = c.post("/sites/analyze", data={"url": "https://org.md/"}, follow_redirects=False)
    assert r.status_code == 200
    assert "page type" in r.text and "add as site" in r.text


def test_stall_below_estimate_is_not_all_collected(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True, "max_pages_per_run": 60,
                                     "fallback_batch": 1000})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md/list?page=1",
                                 "enabled": True, "step_percent": 100}])
    conn.execute("INSERT INTO crawl_state(site_id, total_estimate) VALUES('s1', 500)")
    conn.commit()

    def fake(g, st, text, url, sc):
        import re
        m = re.search(r"page=(\d+)", url)
        n = int(m.group(1)) if m else 1
        if n > 3:
            return [], None, 500
        return [{"title": f"P{n}-{i}", "url": f"u{n}-{i}"} for i in range(10)], None, 500
    monkeypatch.setattr(gw, "get_text", lambda url, timeout=30, headers=None: "x")
    monkeypatch.setattr(gw, "_extract", fake)
    run_collector("genericweb", store, conn, params={"mode": "backfill"})
    row = conn.execute("SELECT exhausted, note, total_collected FROM crawl_state "
                       "WHERE site_id='s1'").fetchone()
    assert row["exhausted"] == 0
    assert row["total_collected"] == 30
    assert "JavaScript" in row["note"]


def test_md_links_to_inline():
    out = gw._md_links_to_inline("See [Tender A](/t/1) and ![img](/x.png) end", "https://a.md")
    assert "Tender A [https://a.md/t/1]" in out
    assert "[https://a.md/x.png]" in out


def test_page_text_crawl4ai_engine(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    import engine.crawl4ai_fetch as c4
    monkeypatch.setattr(c4, "crawl4ai_available", lambda: True)
    monkeypatch.setattr(c4, "fetch_markdown",
                        lambda url, timeout=30, wait_ms=1500, headers=None: "Row [Tender A](/t/1)")
    text, rendered = gw._page_text("https://a.md/list", {"engine": "crawl4ai"}, None, False, 5000)
    assert rendered is True
    assert "Tender A [https://a.md/t/1]" in text


def test_page_text_falls_back_when_crawl4ai_missing(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    import engine.crawl4ai_fetch as c4
    monkeypatch.setattr(c4, "crawl4ai_available", lambda: False)
    monkeypatch.setattr(gw, "get_text", lambda url, timeout=30, headers=None: '<a href="/t/1">A</a>')
    text, rendered = gw._page_text("https://a.md/", {"engine": "crawl4ai"}, None, False, 5000)
    assert "A [https://a.md/t/1]" in text


def test_collect_uses_crawl4ai_engine(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True, "engine": "crawl4ai", "fallback_batch": 5})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md/list?page=1",
                                 "enabled": True, "step_percent": 100}])
    import engine.crawl4ai_fetch as c4
    calls = {"n": 0}
    monkeypatch.setattr(c4, "crawl4ai_available", lambda: True)

    def fm(url, timeout=30, wait_ms=1500, headers=None):
        calls["n"] += 1
        return "md"
    monkeypatch.setattr(c4, "fetch_markdown", fm)

    def fake_extract(g, st, text, url, sc):
        import re
        m = re.search(r"page=(\d+)", url)
        n = int(m.group(1)) if m else 1
        if n > 1:
            return [], None, None
        return [{"title": "T1", "url": "u1"}], None, None
    monkeypatch.setattr(gw, "_extract", fake_extract)
    r = run_collector("genericweb", store, conn, params={"mode": "backfill"})
    assert calls["n"] >= 1 and r["new"] == 1


def test_web_engine_toggle(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from web.server import create_app
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    conn, store = fresh(Path(tmp_path))
    conn.close()
    c = TestClient(create_app(p))
    c.post("/sites/engine-toggle", follow_redirects=False)
    conn2 = db.connect(p)
    s2 = ConfigStore(conn2)
    s2.reload()
    assert s2.get("sources.genericweb")["engine"] == "crawl4ai"
    conn2.close()


def test_max_age_filters_old_tenders(tmp_path, monkeypatch):
    import json as _json
    import datetime as _dt
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True, "fallback_batch": 100})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md/list?page=1",
                                 "enabled": True, "step_percent": 100}])
    store.set("collect.max_age_days", 120)
    recent = _dt.date.today().isoformat()

    def fake_extract(g, st, text, url, sc):
        import re
        m = re.search(r"page=(\d+)", url)
        n = int(m.group(1)) if m else 1
        if n > 1:
            return [], None, None
        return ([{"title": "Old", "url": "uo", "date": "2020-01-01"},
                 {"title": "New", "url": "un", "date": recent}], None, None)
    monkeypatch.setattr(gw, "get_text", lambda url, timeout=30, headers=None: "x")
    monkeypatch.setattr(gw, "_extract", fake_extract)
    r = run_collector("genericweb", store, conn, params={"mode": "backfill"})
    assert r["new"] == 1 and r["too_old"] == 1
    titles = [_json.loads(row["normalized_json"])["title"]
              for row in conn.execute("SELECT normalized_json FROM tenders").fetchall()]
    assert titles == ["New"]


def test_age_boundary_note(tmp_path, monkeypatch):
    import datetime as _dt
    conn, store = fresh(tmp_path)
    store.set("sources.genericweb", {"enabled": True, "fallback_batch": 100})
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md/list?page=1",
                                 "enabled": True, "batch_size": 100}])
    store.set("collect.max_age_days", 90)
    recent = _dt.date.today().isoformat()
    kept = (_dt.date.today() - _dt.timedelta(days=40)).isoformat()

    def fake(g, st, text, url, sc):
        import re
        m = re.search(r"page=(\d+)", url)
        n = int(m.group(1)) if m else 1
        if n > 1:
            return [], None, None
        return ([{"title": "Fresh", "url": "u1", "date": recent},
                 {"title": "Edge", "url": "u2", "date": kept},
                 {"title": "Old", "url": "u3", "date": "2020-01-01"}],
                "https://a.md/list?page=2", None)
    monkeypatch.setattr(gw, "get_text", lambda url, timeout=30, headers=None: "x")
    monkeypatch.setattr(gw, "_extract", fake)
    r = run_collector("genericweb", store, conn, params={"mode": "backfill"})
    assert r["new"] == 2 and r["too_old"] == 1
    note = conn.execute("SELECT note FROM crawl_state WHERE site_id='s1'").fetchone()["note"]
    assert "reached age limit" in note and kept in note


def test_tender_detail_survives_bad_extraction(tmp_path, monkeypatch):
    import json as _json
    import time as _time
    from fastapi.testclient import TestClient
    from web.server import create_app
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path / "t.db")
    conn, store = fresh(Path(tmp_path))
    now = _time.time()
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,"
                 "status,created_at,updated_at) VALUES('mtender','z1','h',?,'extracted',?,?)",
                 (_json.dumps({"title": "T"}), now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id='z1'").fetchone()["id"]
    conn.execute("INSERT INTO extractions(tender_id,fields_json,model,method,cost,created_at) "
                 "VALUES(?,?,?,?,?,?)", (tid, _json.dumps("raw non-json text"), "m", "llm", 0, now))
    conn.commit()
    conn.close()
    c = TestClient(create_app(p))
    r = c.get(f"/tender?id={tid}", follow_redirects=False)
    assert r.status_code == 200
