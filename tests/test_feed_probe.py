from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from workflows.collectors.feed_probe import best, probe
RSS = '<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
ATOM = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>'
SITEMAP = '<?xml version="1.0"?><urlset><url><loc>a</loc><lastmod>2026-01-01</lastmod></url></urlset>'
def _fetcher(pages):
    def f(u):
        if u in pages:
            return pages[u]
        raise RuntimeError("404")
    return f
def test_finds_a_wordpress_api():
    pages = {"https://s.md/ach": "<html></html>",
             "https://s.md/wp-json/wp/v2/posts?per_page=1": '[{"id":1}]'}
    got = probe("https://s.md/ach", fetch=_fetcher(pages))
    assert best(got)["kind"] == "wordpress"
    assert best(got)["url"] == "https://s.md/wp-json/wp/v2/posts?per_page=1"
def test_a_declared_feed_wins_over_a_guessed_path():
    pages = {"https://s.md/ach":
             '<html><head><link rel="alternate" type="application/rss+xml" '
             'href="/news/feed.xml"></head></html>',
             "https://s.md/news/feed.xml": RSS,
             "https://s.md/rss.xml": RSS}
    got = probe("https://s.md/ach", fetch=_fetcher(pages))
    assert best(got)["url"] == "https://s.md/news/feed.xml"
    assert "declared by the page" in best(got)["note"]
def test_relative_and_absolute_declared_hrefs():
    pages = {"https://s.md/a/b": '<html><link rel=alternate type="application/atom+xml" '
                                 'href="https://other.md/f.xml"></html>',
             "https://other.md/f.xml": ATOM}
    assert best(probe("https://s.md/a/b", fetch=_fetcher(pages)))["url"] == "https://other.md/f.xml"
def test_sitemap_is_recognised():
    pages = {"https://s.md/ach": "<html></html>", "https://s.md/sitemap.xml": SITEMAP}
    assert best(probe("https://s.md/ach", fetch=_fetcher(pages)))["kind"] == "sitemap"
def test_a_page_that_merely_returns_200_is_not_a_feed():
    """Plenty of sites answer every path with their homepage. Verify the body, not the status."""
    pages = {"https://s.md/ach": "<html>home</html>",
             "https://s.md/feed": "<html>home</html>",
             "https://s.md/rss.xml": "<html>home</html>",
             "https://s.md/sitemap.xml": "<html>home</html>",
             "https://s.md/wp-json/wp/v2/posts?per_page=1": "<html>home</html>"}
    assert probe("https://s.md/ach", fetch=_fetcher(pages)) == []
def test_wp_json_must_be_a_list_not_any_json():
    pages = {"https://s.md/ach": "<html></html>",
             "https://s.md/wp-json/wp/v2/posts?per_page=1": '{"code":"rest_no_route"}'}
    assert probe("https://s.md/ach", fetch=_fetcher(pages)) == []
def test_probe_never_raises_even_if_everything_fails():
    def boom(_u):
        raise RuntimeError("network down")
    assert probe("https://s.md/ach", fetch=boom) == []
    assert best([]) is None
def test_the_button_stores_what_it_found(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path/"f.db"); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    s.set("sites.tenders", [{"id": "ch", "label": "Primaria", "url": "https://s.md/ach",
                             "enabled": True}])
    accounts.create(conn, "rl", "password1", role="user"); conn.commit(); conn.close()
    import workflows.collectors.feed_probe as fp
    monkeypatch.setattr(fp, "probe", lambda url, **k: [
        {"kind": "wordpress", "url": "https://s.md/wp-json/wp/v2/posts", "note": "n"}])
    c = TestClient(create_app(p), follow_redirects=False)
    c.post("/login", data={"login": "rl", "password": "password1"})
    r = c.post("/app/settings/sites/probe", data={"id": "ch"})
    assert r.status_code == 303 and "found+wordpress" in r.headers["location"].replace("%20", "+")
    conn = db.connect(p); s2 = ConfigStore(conn); s2.reload()
    site = s2.get("sites.tenders")[0]
    assert site["feed_kind"] == "wordpress" and "wp-json" in site["feed_url"]
    h = c.get("/app/settings/sources").text
    assert "wordpress available" in h
    conn.close()
def test_nothing_found_is_recorded_too(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p = str(tmp_path/"f2.db"); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    s.set("sites.tenders", [{"id": "ch", "label": "P", "url": "https://s.md/a", "enabled": True}])
    accounts.create(conn, "rl", "password1", role="user"); conn.commit(); conn.close()
    import workflows.collectors.feed_probe as fp
    monkeypatch.setattr(fp, "probe", lambda url, **k: [])
    c = TestClient(create_app(p), follow_redirects=False)
    c.post("/login", data={"login": "rl", "password": "password1"})
    c.post("/app/settings/sites/probe", data={"id": "ch"})
    assert "no feed" in c.get("/app/settings/sources").text
