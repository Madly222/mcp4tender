from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web import settings_ops
from web.server import create_app
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="user")
    conn.commit(); return p, conn
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def _store(p):
    s = ConfigStore(db.connect(p)); s.reload(); return s
def _row(i, name, price="100", cur="EUR", **kw):
    d = {f"cat{i}_denumire": name, f"cat{i}_price": price, f"cat{i}_currency": cur,
         f"cat{i}_id": kw.get("id", ""), f"cat{i}_supplier": kw.get("supplier", ""),
         f"cat{i}_model": kw.get("model", ""), f"cat{i}_vendor": kw.get("vendor", ""),
         f"cat{i}_specs": kw.get("specs", "")}
    if kw.get("remove"):
        d[f"cat{i}_remove"] = "on"
    return d
def test_currencies_come_from_the_fx_table():
    class S:
        def get(self, k, d=None):
            return {"EUR->MDL": 19.6, "USD->MDL": 18.0} if k == "suppliers.fx_rates" else d
    assert settings_ops.catalog_currencies(S()) == ["EUR", "MDL", "USD"]
def test_rate_known():
    rates = {"EUR->MDL": 19.6}
    assert settings_ops._rate_known("MDL", rates)
    assert settings_ops._rate_known("EUR", rates)
    assert settings_ops._rate_known("", rates)
    assert not settings_ops._rate_known("GBP", rates)
def test_form_replaces_the_raw_catalog_json(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"c1.db"); conn.close()
    h = _login(p).get("/app/settings/suppliers").text
    assert "Supplier catalog" in h and 'name="cat0_denumire"' in h
    assert "Cameră ANPR 4K edge" in h and "Jenoptik VECTOR ANPR" in h
    assert "suppliers.catalog" not in h
    assert "suppliers.fx_rates" in h and "suppliers.margin_min" in h
def test_saving_edits_adds_and_removes(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"c2.db"); conn.close()
    c = _login(p)
    data = {}
    data.update(_row(0, "Switch acces 48p", "820", "EUR", id="sw-48", supplier="Cisco",
                     model="C9200-48P", vendor="Cisco", specs="48x1G PoE+"))
    data.update(_row(1, "Vechi", "1", "EUR", id="old-one", remove=True))
    data.update(_row(2, "Cameră nouă", "300", "MDL"))
    r = c.post("/app/settings/catalog/save", data=data)
    assert r.status_code == 303 and "saved=" in r.headers["location"]
    cat = _store(p).get("suppliers.catalog")
    assert [i["denumire"] for i in cat] == ["Switch acces 48p", "Cameră nouă"]
    first = cat[0]
    assert first["id"] == "sw-48" and first["price"] == 820 and first["currency"] == "EUR"
    assert first["model"] == "C9200-48P" and first["specs"] == "48x1G PoE+"
def test_new_row_gets_a_slug_id_and_stays_unique(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"c3.db"); conn.close()
    data = {}
    data.update(_row(0, "Cameră ANPR 4K", "100"))
    data.update(_row(1, "Cameră ANPR 4K", "200"))
    _login(p).post("/app/settings/catalog/save", data=data)
    cat = _store(p).get("suppliers.catalog")
    ids = [i["id"] for i in cat]
    assert ids == ["camer-anpr-4k", "camer-anpr-4k-2"], ids
def test_blank_name_deletes_the_line(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"c4.db"); conn.close()
    data = {}
    data.update(_row(0, "Keep me", "10"))
    data.update(_row(1, "", "10"))
    _login(p).post("/app/settings/catalog/save", data=data)
    assert [i["denumire"] for i in _store(p).get("suppliers.catalog")] == ["Keep me"]
def test_currency_without_a_rate_warns_loudly(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"c5.db"); conn.close()
    c = _login(p)
    r = c.post("/app/settings/catalog/save", data=_row(0, "Ceva", "10", "GBP"))
    loc = r.headers["location"]
    assert "no+exchange+rate" in loc or "no%20exchange%20rate" in loc
    assert "GBP" in loc
    assert _store(p).get("suppliers.catalog")[0]["currency"] == "GBP"
    assert "No exchange rate for GBP" in c.get("/app/settings/suppliers").text
def test_price_junk_becomes_zero_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"c6.db"); conn.close()
    _login(p).post("/app/settings/catalog/save", data=_row(0, "Ceva", "abc", "MDL"))
    assert _store(p).get("suppliers.catalog")[0]["price"] == 0
def test_read_only_blocks_the_catalog(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"c7.db")
    ConfigStore(conn).set("web.read_only", True); conn.commit(); conn.close()
    before = _store(p).get("suppliers.catalog")
    r = _login(p).post("/app/settings/catalog/save", data=_row(0, "Hacked", "1"))
    assert "err=" in r.headers["location"]
    assert _store(p).get("suppliers.catalog") == before
