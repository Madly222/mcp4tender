from __future__ import annotations
import datetime as dt, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn); ConfigStore(conn).reload()
    return p, conn
def _ago(days): return time.time() - days*86400
def _iso(n): return (dt.date.today() + dt.timedelta(days=n)).isoformat()
def _add(conn, ext, nj, status, origin="backfill", created_at=None, verdict=None,
         stage="applicability", score=80, margin=None):
    now = created_at if created_at is not None else time.time()
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at) VALUES('mtender',?,?,?,?,?,?,?)",
                 (ext,"h",nj,status,origin,now,now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    if verdict:
        conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) VALUES(?,?,?,?,?)", (tid,stage,verdict,score,time.time()))
    if margin is not None:
        conn.execute("INSERT INTO suppliers(tender_id,margin,created_at) VALUES(?,?,?)", (tid,margin,time.time()))
    conn.commit(); return tid
def test_relevance_filter_general(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"r.db")
    _add(conn,"o1",'{"title":"CCTV","documents":[{"title":"c.pdf","url":"http://x"}]}',"analyzed",verdict="can",margin=0.2)
    _add(conn,"o2",'{"title":"Mobilier"}',"analyzed",verdict="out",stage="triage",score=-3)
    _add(conn,"o3",'{"title":"Canc"}',"triaged",verdict="relevant",stage="triage",score=3)
    conn.close()
    h = TestClient(create_app(p)).get("/results?tab=general").text
    assert "CCTV" in h and "Can execute" in h and "20.0%" in h
    assert "Canc" in h and "pending analysis" in h and "Mobilier" not in h
def test_tab_routing(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"seg.db")
    _add(conn,"n1",json.dumps({"title":"FreshNew"}),"analyzed",origin="incremental",created_at=_ago(1),verdict="can")
    _add(conn,"h1",json.dumps({"title":"OldHistory"}),"analyzed",origin="backfill",created_at=_ago(30),verdict="can")
    _add(conn,"a1",json.dumps({"title":"PastDeadline","deadline":_iso(-2)}),"analyzed",origin="incremental",created_at=_ago(1),verdict="can")
    _add(conn,"j1",json.dumps({"title":"JunkOut"}),"analyzed",origin="incremental",created_at=_ago(1),verdict="out",stage="triage",score=-3)
    c = TestClient(create_app(p))
    new=c.get("/results?tab=new").text; gen=c.get("/results?tab=general").text
    arc=c.get("/results?tab=archive").text; allt=c.get("/results?tab=all").text
    assert "FreshNew" in new and "OldHistory" not in new and "PastDeadline" not in new
    assert "OldHistory" in gen and "FreshNew" not in gen
    assert "PastDeadline" in arc and "FreshNew" not in arc
    assert all(x in allt for x in ("FreshNew","OldHistory","PastDeadline","JunkOut"))
    assert "JunkOut" not in new and "JunkOut" not in gen and "JunkOut" not in arc
def test_tab_counts_shown(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"cnt.db")
    _add(conn,"n1",json.dumps({"title":"N"}),"analyzed",origin="incremental",created_at=_ago(1),verdict="can")
    _add(conn,"h1",json.dumps({"title":"H"}),"analyzed",origin="backfill",created_at=_ago(30),verdict="can")
    h = TestClient(create_app(p)).get("/results?tab=new").text
    assert 'href="/results?tab=new"' in h and 'href="/results?tab=all"' in h
    assert ">General relevant<" in h and ">Archive<" in h
def test_new_days_setting_shortens_window(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"nd.db")
    _add(conn,"n1",json.dumps({"title":"FiveDays"}),"analyzed",origin="incremental",created_at=_ago(5),verdict="can")
    conn.close(); c = TestClient(create_app(p))
    assert "FiveDays" in c.get("/results?tab=new").text
    c.post("/results/settings", data={"new_days":"3"})
    assert "FiveDays" not in c.get("/results?tab=new").text
    assert "FiveDays" in c.get("/results?tab=general").text
def test_search_and_nav(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"s.db")
    _add(conn,"n1",json.dumps({"title":"Only"}),"analyzed",origin="incremental",created_at=_ago(1),verdict="can")
    conn.close(); c = TestClient(create_app(p))
    assert ">Results<" in c.get("/results").text
    assert "0 shown" in c.get("/results?tab=new&q=999999").text
def _add_dated(conn, ext, title, pub, dl, cpv):
    _add(conn, ext, json.dumps({"title":title,"publication_date":pub,"deadline":dl,"cpv":[{"id":cpv,"description":"d"}]}), "analyzed", verdict="can")
def _order(txt):
    import re; return re.findall(r'rtitle">([^<]+)<', txt)
def test_sort_by_date_all(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"so.db")
    _add_dated(conn,"a","Alpha","2026-06-10","2026-08-01","32000000-3")
    _add_dated(conn,"b","Beta","2026-06-20","2026-07-01","30100000-0")
    _add_dated(conn,"c","Gamma","2026-06-01",None,"32000000-3")
    conn.close(); c = TestClient(create_app(p))
    assert _order(c.get("/results?tab=all").text)==["Beta","Alpha","Gamma"]
    assert _order(c.get("/results?tab=all&sort=published").text)==["Beta","Alpha","Gamma"]
def test_group_by_cpv_all(tmp_path, monkeypatch):
    import re
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"cp.db")
    _add_dated(conn,"a","Alpha","2026-06-10","2026-08-01","32000000-3")
    _add_dated(conn,"b","Beta","2026-06-20","2026-07-01","30100000-0")
    conn.close()
    h = TestClient(create_app(p)).get("/results?tab=all&sort=cpv").text
    assert re.findall(r'cpv-h">([0-9-]+)', h)==["30100000-0","32000000-3"]
def test_three_dates_and_estimated_deadline(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"d.db")
    nj = json.dumps({"title":"CCTV","publication_date":"2026-06-01","enquiry_deadline":"2026-06-20","deadline":None})
    tid = _add(conn,"ocds-x",nj,"analyzed",verdict="can")
    conn.execute("INSERT INTO extractions(tender_id,fields_json,method,model,cost,created_at) VALUES(?,?,?,?,?,?)",
                 (tid,'{"data_depunerii":"15.07.2026"}',"llm","m",0,time.time()))
    conn.commit(); conn.close(); c = TestClient(create_app(p))
    d = c.get(f"/tender?id={tid}").text
    assert "data depunerii" in d
    res = c.get("/results?tab=all").text
    assert "Published:" in res and "Enquiry:" in res and "AI-estimated" in res
def test_source_field_and_portal_link(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"src.db")
    tid = _add(conn,"ocds-b3wdp1-MD-1",'{"title":"CCTV","documents":[{"title":"c.pdf","url":"http://x/c.pdf"}]}',"analyzed",verdict="can")
    conn.close(); c = TestClient(create_app(p))
    link = "https://mtender.gov.md/tenders/ocds-b3wdp1-MD-1"
    d = c.get(f"/tender?id={tid}").text
    assert ">source<" in d and link in d and "c.pdf" in d
    res = c.get("/results?tab=all").text
    assert "Source:" in res and link in res and "c.pdf" in res
def test_source_url_helper():
    from web.render import source_url
    assert source_url("mtender","ocds-b3wdp1-MD-123")=="https://mtender.gov.md/tenders/ocds-b3wdp1-MD-123"
    assert source_url("mtender","ocds-x","https://p/{ocid}")=="https://p/ocds-x"
    assert source_url("genericweb","ocds-x") is None
    assert source_url("mtender","not-ocds") is None
