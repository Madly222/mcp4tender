from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import accounts, alerts, db, llm
from engine.config_store import ConfigStore
from engine.llm import LLMGateway
from fastapi.testclient import TestClient
from web.server import create_app
import workflows  # noqa: F401
from workflows import work

DEFAULTS = str(Path(__file__).resolve().parent.parent / "config" / "defaults")


def _fresh(tmp_path, name):
    p = str(tmp_path / name)
    conn = db.connect(p)
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.seed_defaults(DEFAULTS)
    store.reload()
    store.set("llm.provider", "stub")
    return p, conn, store


class PaidProvider:
    name = "anthropic"
    available = True

    def generate(self, model, system, messages, max_tokens):
        return {"text": "ok", "input_tokens": 1000, "output_tokens": 100}


def test_every_call_lands_in_llm_spend(tmp_path):
    p, conn, store = _fresh(tmp_path, "c1.db")
    g = LLMGateway(store, conn, provider=PaidProvider())
    llm.set_context(tender_id=7)
    g.complete("extract", "sys", [{"role": "user", "content": "hi"}])
    g.complete("extract", "sys", [{"role": "user", "content": "hi"}])
    llm.set_context(site_id="s1")
    g.complete("site_collect", "sys", [{"role": "user", "content": "page"}])
    llm.set_context()
    rows = conn.execute("SELECT stage, cached, tender_id, site_id, cost "
                        "FROM llm_spend ORDER BY id").fetchall()
    assert len(rows) == 3
    assert rows[0]["tender_id"] == 7 and rows[0]["cached"] == 0 and rows[0]["cost"] > 0
    assert rows[1]["cached"] == 1 and rows[1]["cost"] == 0
    assert rows[2]["site_id"] == "s1" and rows[2]["tender_id"] is None
    conn.close()


def _err_run(conn, error, tender_id=1, ago=100):
    now = time.time()
    conn.execute(
        "INSERT INTO stage_runs(run_id, tender_id, stage_name, status, input_hash, "
        "started_at, finished_at, tokens, cost, error) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("r1", tender_id, "applicability", "error", "h", now - ago - 1, now - ago,
         0, 0, error))
    conn.commit()


def test_alerts_collects_and_translates_errors(tmp_path):
    p, conn, store = _fresh(tmp_path, "c2.db")
    _err_run(conn, "Your credit balance is too low to access the Anthropic API")
    _add(conn, "q2", "2026-09-01", time.time())
    tid2 = conn.execute("SELECT id FROM tenders WHERE external_id='q2'").fetchone()["id"]
    conn.execute(
        "INSERT INTO qualify_runs(tender_id, account_id, status, step, error, "
        "started_at, finished_at) VALUES(?,?,?,?,?,?,?)",
        (tid2, 1, "failed", "extract", "boom", time.time() - 50, time.time() - 40))
    conn.commit()
    items = alerts.recent(conn)
    assert len(items) == 2
    assert items[0]["kind"] == "qualify"
    assert "run out of credit" in (items[1]["hint"] or "")
    assert alerts.unseen_count(conn, store) == 2
    store.set("alerts.seen_until", time.time())
    assert alerts.unseen_count(conn, store) == 0
    conn.close()


def _login(p, conn):
    accounts.create(conn, "rapid", "password123", company="Rapid Link")
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rapid",
                                  "password": "password123"}).status_code == 303
    return c


def _add(conn, ext, deadline, created):
    nj = {"title": f"T {ext}", "buyer": "B", "deadline": deadline}
    conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "origin, created_at, updated_at) VALUES('mtender',?,?,?,'new','incremental',?,?)",
        (ext, "h" + ext, json.dumps(nj), created, created))
    conn.commit()
    return conn.execute("SELECT id FROM tenders WHERE external_id=?",
                        (ext,)).fetchone()["id"]


def test_alerts_page_and_badge(tmp_path):
    p, conn, store = _fresh(tmp_path, "c3.db")
    tid = _add(conn, "a1", "2026-09-01", time.time())
    _err_run(conn, "invalid x-api-key", tender_id=tid)
    c = _login(p, conn)
    page = c.get("/app/alerts").text
    assert "invalid x-api-key" in page
    assert "wrong or revoked" in page
    home = c.get("/app").text
    assert "Alerts" in home
    r = c.post("/app/alerts/seen")
    assert r.status_code == 303
    store.reload()
    assert float(store.get("alerts.seen_until")) > 0


def test_costs_page_lists_sites_and_tenders(tmp_path):
    p, conn, store = _fresh(tmp_path, "c4.db")
    tid = _add(conn, "a1", "2026-09-01", time.time())
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md", "label": "Primaria"}])
    now = time.time()
    conn.execute("INSERT INTO llm_spend(ts, stage, model, provider, input_tokens, "
                 "output_tokens, cost, cached, tender_id, site_id) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (now, "site_collect", "m", "anthropic", 100, 10, 0.05, 0, None, "s1"))
    conn.execute("INSERT INTO llm_spend(ts, stage, model, provider, input_tokens, "
                 "output_tokens, cost, cached, tender_id, site_id) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (now, "applicability", "m", "anthropic", 200, 20, 0.12, 0, tid, None))
    conn.commit()
    c = _login(p, conn)
    page = c.get("/app/costs").text
    assert "Primaria" in page and "$0.05" in page
    assert "T a1" in page and "$0.12" in page
    tpage = c.get(f"/app/tender/{tid}").text
    assert "AI spend on this tender" in tpage and "$0.12" in tpage
    sites = c.get("/app/settings/sources").text
    assert "spent" in sites and "$0.05" in sites


def test_nav_counts_show_zero_for_pipeline_stages(tmp_path):
    p, conn, store = _fresh(tmp_path, "c5.db")
    c = _login(p, conn)
    home = c.get("/app").text
    assert "In progress" in home and "Submitted" in home
    from web.user.counts import nav_counts
    counts = nav_counts(conn, store, 1)
    assert counts["qualified"] == 0
    assert counts["in_progress"] == 0
    assert counts["submitted"] == 0


def test_qualified_sorts_by_deadline_default(tmp_path):
    p, conn, store = _fresh(tmp_path, "c6.db")
    now = time.time()
    late = _add(conn, "late", "2026-12-01", now)
    soon = _add(conn, "soon", "2026-08-01", now - 100)
    nodl = _add(conn, "nodl", None, now - 50)
    for t in (late, soon, nodl):
        work.set_stage(conn, t, 1, "qualified")
    c = _login(p, conn)
    page = c.get("/app/qualified").text
    assert page.index("T soon") < page.index("T late") < page.index("T nodl")
    page = c.get("/app/qualified?sort=new").text
    assert page.index("T late") < page.index("T nodl") < page.index("T soon")


def _spend_row(conn, ts, stage, cost, itok, tender_id=None, site_id=None, cached=0):
    conn.execute("INSERT INTO llm_spend(ts, stage, model, provider, input_tokens, "
                 "output_tokens, cost, cached, tender_id, site_id) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (ts, stage, "m", "anthropic", itok, 10, cost, cached, tender_id, site_id))
    conn.commit()


def test_calls_page_filters_by_tender(tmp_path):
    p, conn, store = _fresh(tmp_path, "c7.db")
    t1 = _add(conn, "a1", "2026-09-01", time.time())
    t2 = _add(conn, "a2", "2026-09-01", time.time())
    now = time.time()
    _spend_row(conn, now - 30, "extract", 0.02, 5000, tender_id=t1)
    _spend_row(conn, now - 20, "applicability", 0.10, 8000, tender_id=t1, cached=0)
    _spend_row(conn, now - 10, "extract", 0.50, 90000, tender_id=t2)
    _spend_row(conn, now - 5, "site_collect", 0.03, 3000, site_id="s1")
    c = _login(p, conn)
    page = c.get(f"/app/costs/calls?tender_id={t1}").text
    assert page.count("<tr>") == 3
    assert "T a1" in page and "T a2" not in page and "site s1" not in page
    allpage = c.get("/app/costs/calls").text
    assert allpage.count("<tr>") == 5


def test_calls_page_sorts_by_cost_and_tokens(tmp_path):
    p, conn, store = _fresh(tmp_path, "c8.db")
    t1 = _add(conn, "a1", "2026-09-01", time.time())
    now = time.time()
    _spend_row(conn, now - 30, "cheap", 0.01, 100, tender_id=t1)
    _spend_row(conn, now - 20, "pricey", 0.90, 200, tender_id=t1)
    _spend_row(conn, now - 10, "fat", 0.05, 99000, tender_id=t1)
    c = _login(p, conn)
    page = c.get("/app/costs/calls?sort=cost").text
    assert page.index("pricey") < page.index("fat") < page.index("cheap")
    page = c.get("/app/costs/calls?sort=tokens").text
    assert page.index("fat") < page.index("pricey") < page.index("cheap")
    page = c.get("/app/costs/calls").text
    assert page.index("fat") < page.index("pricey") < page.index("cheap")


def test_costs_page_links_to_calls_and_tender_line_links(tmp_path):
    p, conn, store = _fresh(tmp_path, "c9.db")
    t1 = _add(conn, "a1", "2026-09-01", time.time())
    store.set("sites.tenders", [{"id": "s1", "url": "https://a.md", "label": "Primaria"}])
    _spend_row(conn, time.time(), "applicability", 0.12, 8000, tender_id=t1)
    _spend_row(conn, time.time(), "site_collect", 0.05, 3000, site_id="s1")
    c = _login(p, conn)
    page = c.get("/app/costs").text
    assert f"/app/costs/calls?tender_id={t1}" in page
    assert "/app/costs/calls?site_id=s1" in page
    assert "Most expensive calls" in page
    tpage = c.get(f"/app/tender/{t1}").text
    assert f"/app/costs/calls?tender_id={t1}" in tpage
