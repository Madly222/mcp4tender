from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from workflows.collectors.genericweb import api_covered
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="user")
    conn.commit(); return p, conn, s
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def test_matches_the_host_not_the_string():
    assert api_covered("https://mtender.md/tenders")
    assert api_covered("http://WWW.MTender.MD/x")
    assert api_covered("https://public.mtender.gov.md/tenders")
    assert not api_covered("https://chisinau.md/achizitii")
    assert not api_covered("")
def test_a_lookalike_domain_is_not_covered():
    """Substring matching would have let this through and silently stopped collecting it."""
    assert not api_covered("https://notmtender.md.evil.com/tenders")
    assert not api_covered("https://mtender.md.attacker.io/x")
def test_the_scraper_refuses_to_spend_tokens_on_an_api_site(tmp_path, caplog):
    import logging
    p, conn, s = _fresh(tmp_path,"a1.db")
    s.set("sites.tenders", [
        {"id": "mt", "label": "MTender", "url": "https://mtender.md/tenders", "enabled": True},
        {"id": "ch", "label": "Chisinau", "url": "https://chisinau.md/ach", "enabled": False}])
    conn.commit()
    from workflows.collectors.genericweb import GenericWebCollector
    from engine.collectors import CollectContext
    sc = dict(s.get("sources.genericweb", {}), enabled=True)
    s.set("sources.genericweb", sc); conn.commit()
    ctx = CollectContext(config=s, cursor=None, source_config=sc, params={})
    with caplog.at_level(logging.WARNING):
        r = GenericWebCollector().collect(ctx)
    assert r.items == []
    assert any("already collected via its API" in m for m in caplog.messages)
    conn.close()
def test_the_site_is_visible_and_removable_again(tmp_path, monkeypatch):
    """It used to be filtered out of the list, which meant it could never be deleted."""
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn, s = _fresh(tmp_path,"a2.db")
    s.set("sites.tenders", [{"id": "mt", "label": "MTender scrape",
                             "url": "https://mtender.md/tenders", "enabled": True}])
    conn.commit(); conn.close()
    c = _login(p)
    h = c.get("/app/settings/sources").text
    assert "MTender scrape" in h
    assert "Already collected through its API" in h
    assert 'name="id" value="mt"' in h
    c.post("/app/settings/sites/remove", data={"kind": "tenders", "id": "mt"})
    conn = db.connect(p); s2 = ConfigStore(conn); s2.reload()
    assert s2.get("sites.tenders") == []
    conn.close()
def test_a_normal_site_gets_no_warning(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn, s = _fresh(tmp_path,"a3.db")
    s.set("sites.tenders", [{"id": "ch", "label": "Primaria", "url": "https://chisinau.md/ach",
                             "enabled": True}])
    conn.commit(); conn.close()
    h = _login(p).get("/app/settings/sources").text
    assert "Primaria" in h and "Already collected through its API" not in h
