from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from web.user import lifecycle
NOW = time.time()
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="user")
    conn.commit(); return p, conn
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def _iso(days):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(NOW + days*86400))
def _add(conn, ext, title, *, status="active", details=None, deadline_days=10,
         found_days_ago=1):
    nj = {"title": title, "buyer": "STISC", "value_amount": 1000, "value_currency": "MDL",
          "cpv": [], "documents": [], "status": status, "status_details": details}
    if deadline_days is not None:
        nj["deadline"] = _iso(deadline_days)
    found = NOW - found_days_ago*86400
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at) VALUES('mtender',?,?,?,'analyzed','incremental',?,?)",
                 (ext, "h"+ext, json.dumps(nj), found, found))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) VALUES(?,'applicability','can',90,?)", (tid, NOW))
    conn.commit(); return tid
CLOSED = {"complete", "cancelled", "unsuccessful", "withdrawn"}
def _nj(status="active", details=None):
    return {"status": status, "status_details": details}
def test_open_while_bids_are_accepted():
    assert lifecycle.state_of(_nj(), _iso(5), CLOSED, now=NOW) == lifecycle.OPEN
def test_closed_once_the_deadline_passed():
    assert lifecycle.state_of(_nj(), _iso(-2), CLOSED, now=NOW) == lifecycle.CLOSED
def test_deadline_today_is_still_open():
    assert lifecycle.state_of(_nj(), _iso(0), CLOSED, now=NOW) == lifecycle.OPEN
def test_dead_status_beats_a_future_deadline():
    for st in ("complete", "CANCELLED", " unsuccessful "):
        assert lifecycle.state_of(_nj(st), _iso(30), CLOSED, now=NOW) == lifecycle.CLOSED, st
def test_status_details_are_checked_too():
    closed = CLOSED | {"calificarea ofertantilor"}
    nj = _nj("active", "Calificarea ofertantilor")
    assert lifecycle.state_of(nj, _iso(30), closed, now=NOW) == lifecycle.CLOSED
def test_an_active_status_alone_is_not_proof_that_bidding_is_open():
    """OCDS keeps status=active through qualification and award. Only a live submission
    deadline proves we can still bid; without one the honest answer is 'unknown'."""
    assert lifecycle.state_of(_nj("active"), None, CLOSED, now=NOW) == lifecycle.UNKNOWN
    assert lifecycle.state_of(_nj("active", "Calificarea ofertantilor"), None,
                              CLOSED, now=NOW) == lifecycle.UNKNOWN
def test_unknown_when_nothing_is_known():
    assert lifecycle.state_of({}, None, CLOSED, now=NOW) == lifecycle.UNKNOWN
    assert lifecycle.state_of(_nj("", ""), "", CLOSED, now=NOW) == lifecycle.UNKNOWN
def test_an_unparseable_deadline_is_not_evidence():
    assert lifecycle.state_of(_nj("active"), "sometime soon", CLOSED, now=NOW) == lifecycle.UNKNOWN
def test_chip_shows_the_real_stage_so_it_can_be_acted_on():
    assert lifecycle.chip(lifecycle.OPEN, {}) == ""
    assert "Bidding closed" in lifecycle.chip(lifecycle.CLOSED, {})
    h = lifecycle.chip(lifecycle.UNKNOWN, _nj("active", "Calificarea ofertanților"))
    assert "Calificarea ofertan" in h, "the operator must see what the portal actually says"
    assert "N/A" in lifecycle.chip(lifecycle.UNKNOWN, {})
def test_status_text_prefers_the_detailed_stage():
    assert lifecycle.status_text(_nj("active", "Depunerea ofertelor")) == "Depunerea ofertelor"
    assert lifecycle.status_text(_nj("active", None)) == "active"
    assert lifecycle.status_text({}) == ""
def test_inbox_hides_a_dead_status_and_says_so(tmp_path, monkeypatch):
    """A signed contract with a future deadline is the case only the status can catch —
    segments.partition cannot, because by its dates the tender still looks alive."""
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"l1.db")
    _add(conn, "a1", "Inca se poate", deadline_days=6)
    _add(conn, "a3", "Contract semnat", status="complete", deadline_days=20)
    conn.close()
    h = _login(p).get("/app/inbox").text
    assert "Inca se poate" in h
    assert "Contract semnat" not in h
    assert "1 tender(s) hidden" in h and "bidding has closed" in h
def test_a_passed_deadline_never_reaches_the_inbox(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"l1b.db")
    _add(conn, "a2", "Deja inchis", deadline_days=-3)
    conn.close()
    assert "Deja inchis" not in _login(p).get("/app/inbox").text
def test_unknown_status_is_shown_with_na(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"l2.db")
    _add(conn, "b1", "Fara status", status=None, deadline_days=None)
    conn.close()
    h = _login(p).get("/app/inbox").text
    assert "Fara status" in h and "N/A" in h
def test_inbox_is_newest_first(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"l3.db")
    _add(conn, "c1", "Cel mai vechi", found_days_ago=5)
    _add(conn, "c2", "De ieri", found_days_ago=1)
    _add(conn, "c3", "Chiar acum", found_days_ago=0)
    conn.close()
    h = _login(p).get("/app/inbox").text
    order = [h.index(t) for t in ("Chiar acum", "De ieri", "Cel mai vechi")]
    assert order == sorted(order), "newest found must come first"
def test_closed_statuses_are_configurable(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"l4.db")
    _add(conn, "d1", "In calificare", status="qualification", deadline_days=9)
    conn.close()
    c = _login(p)
    assert "In calificare" in c.get("/app/inbox").text
    conn = db.connect(p); s = ConfigStore(conn)
    s.set("results.closed_statuses", ["complete", "qualification"]); conn.commit(); conn.close()
    assert "In calificare" not in c.get("/app/inbox").text
def test_search_still_shows_everything(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"l5.db")
    _add(conn, "e1", "Deja inchis", deadline_days=-3)
    conn.close()
    assert "Deja inchis" in _login(p).get("/app/search?q=inchis").text
def test_countdown_labels_are_not_off_by_one():
    from web.user import cards
    def label(days):
        h = cards._left(_iso(days), NOW) or ""
        for junk in ('<div class="t-left bad">', '<div class="t-left warn">',
                     '<div class="t-left">', "</div>"):
            h = h.replace(junk, "")
        return h
    assert label(-1) == "closed"
    assert label(0) == "today", "a tender closing today is still biddable"
    assert label(1) == "tomorrow"
    assert label(2) == "2 days left"
    assert label(3) == "3 days left"
def test_day_end_ts_uses_the_end_of_the_day():
    import datetime as dt
    from engine.dateparse import day_end_ts
    ts = day_end_ts("2026-07-17")
    got = dt.datetime.fromtimestamp(ts)
    assert (got.hour, got.minute, got.second) == (23, 59, 59)
    assert day_end_ts(None) is None and day_end_ts("nonsense") is None
def test_badge_matches_the_list(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"n1.db")
    _add(conn, "n1", "Viu", deadline_days=6)
    _add(conn, "n2", "Contract semnat", status="complete", deadline_days=20)
    _add(conn, "n3", "Anulat", status="cancelled", deadline_days=15)
    conn.close()
    from web.user.counts import nav_counts
    from engine.config_store import ConfigStore
    conn = db.connect(p); s = ConfigStore(conn); s.reload()
    assert nav_counts(conn, s, 1)["inbox"] == 1, "the badge must not count what the list hides"
    conn.close()
def test_sweep_skips_only_the_closed_ones(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"n2.db")
    live = _add(conn, "s1", "Viu", deadline_days=6)
    dead = _add(conn, "s2", "Contract semnat", status="complete", deadline_days=20)
    conn.close()
    c = _login(p)
    r = c.post("/app/inbox/sweep")
    assert r.status_code == 303 and "swept=1" in r.headers["location"]
    from workflows import work
    conn = db.connect(p)
    assert work.stage_of(conn, dead, 1) == "skipped"
    assert work.stage_of(conn, live, 1) == "inbox", "a live tender must never be swept"
    conn.close()
    h = c.get("/app/inbox?swept=1").text
    assert "moved to Skipped" in h and "Viu" in h
def test_sweep_is_reversible(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"n3.db")
    dead = _add(conn, "r1", "Contract semnat", status="complete", deadline_days=20)
    conn.close()
    c = _login(p)
    c.post("/app/inbox/sweep")
    assert "Contract semnat" in c.get("/app/qualified?stage=skipped").text
def test_sweep_leaves_nothing_to_hide(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"n4.db")
    _add(conn, "z1", "Viu", deadline_days=6)
    _add(conn, "z2", "Contract semnat", status="complete", deadline_days=20)
    conn.close()
    c = _login(p)
    assert "1 tender(s) hidden" in c.get("/app/inbox").text
    c.post("/app/inbox/sweep")
    h = c.get("/app/inbox").text
    assert "tender(s) hidden" not in h and "Skip them for good" not in h
def test_read_only_blocks_the_sweep(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"n5.db")
    dead = _add(conn, "ro1", "Contract semnat", status="complete", deadline_days=20)
    ConfigStore(conn).set("web.read_only", True); conn.commit(); conn.close()
    _login(p).post("/app/inbox/sweep")
    from workflows import work
    conn = db.connect(p)
    assert work.stage_of(conn, dead, 1) == "inbox"
    conn.close()
def test_qualification_stage_no_longer_leaks_into_the_inbox(tmp_path, monkeypatch):
    """The exact leak Victor hit: OCDS status stays 'active' during qualification and the
    record carries no submission deadline, so the old rule called it open."""
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"q1.db")
    _add(conn, "q1", "In calificare", status="active",
         details="Calificarea ofertanților", deadline_days=None)
    conn.close()
    c = _login(p)
    h = c.get("/app/inbox").text
    assert "Calificarea ofertan" in h, "its real stage must be visible, not a bare N/A"
    conn = db.connect(p); s = ConfigStore(conn)
    s.set("results.closed_statuses", ["complete", "cancelled", "calificarea ofertanților"])
    conn.commit(); conn.close()
    h = c.get("/app/inbox").text
    assert "In calificare" not in h
    assert "1 tender(s) hidden" in h
def test_the_collector_keeps_status_details():
    from workflows.collectors.mtender import normalize_record
    pkg = {"records": [{"compiledRelease": {
        "tender": {"title": "T", "status": "active", "statusDetails": "qualification",
                   "tenderPeriod": {"endDate": "2026-08-01T16:00:00Z"}}}}]}
    nj = normalize_record(pkg, "ocds-1")
    assert nj["status"] == "active" and nj["status_details"] == "qualification"
    assert nj["deadline"] == "2026-08-01T16:00:00Z"
def test_missing_status_details_stays_none():
    from workflows.collectors.mtender import normalize_record
    pkg = {"records": [{"compiledRelease": {"tender": {"title": "T", "status": "active"}}}]}
    assert normalize_record(pkg, "ocds-2")["status_details"] is None
