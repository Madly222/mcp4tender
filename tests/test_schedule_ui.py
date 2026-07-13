from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
DEFAULTS = Path(__file__).resolve().parent.parent/"config"/"defaults"
def _app(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults(DEFAULTS); conn.close(); return p
def _reload(p):
    s = ConfigStore(db.connect(p)); s.reload(); return s
def _collect(store):
    for j in store.get("schedule.jobs", []):
        if j.get("kind")=="collect": return j
def test_schedule_page_renders(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    h = TestClient(create_app(_app(tmp_path,"a.db"))).get("/schedule").text
    assert ">Schedule<" in h and 'name="timezone"' in h and 'name="times"' in h
    assert "Mon" in h and "Sun" in h and "mtender" in h and "genericweb" in h
def test_schedule_nav_present(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    assert 'href="/schedule"' in TestClient(create_app(_app(tmp_path,"nav.db"))).get("/schedule").text
def test_schedule_save(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p=_app(tmp_path,"s.db"); c=TestClient(create_app(p))
    c.post("/schedule", data={"enabled":"on","timezone":"Europe/Chisinau","day_1":"on","day_3":"on",
                              "times":"06:00, 25:99, 14:30","src_mtender":"on","analyze":"on"})
    store=_reload(p); job=_collect(store)
    assert store.get("schedule.timezone")=="Europe/Chisinau"
    assert job["enabled"] is True and job["days"]==[1,3] and job["at"]==["06:00","14:30"]
    assert job["sources"]==["mtender"] and job["analyze"] is True
    assert any(j.get("pipeline")=="pipeline.demo" for j in store.get("schedule.jobs", []))
def test_schedule_defaults_sources_and_everyday(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p=_app(tmp_path,"d.db"); TestClient(create_app(p)).post("/schedule", data={"enabled":"on","times":"09:00","analyze":"on"})
    job=_collect(_reload(p))
    assert job["days"]==[] and set(job["sources"])=={"mtender","genericweb"}
def test_schedule_caps_times_at_24(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p=_app(tmp_path,"cap.db")
    times=", ".join(("%02d:00"%h) for h in range(24))+", 12:30, 13:30"
    TestClient(create_app(p)).post("/schedule", data={"enabled":"on","times":times,"src_mtender":"on"})
    assert len(_collect(_reload(p))["at"])==24
def test_schedule_single_collect_job(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p=_app(tmp_path,"one.db"); c=TestClient(create_app(p))
    c.post("/schedule", data={"enabled":"on","times":"06:00"}); c.post("/schedule", data={"enabled":"on","times":"07:00"})
    collects=[j for j in _reload(p).get("schedule.jobs", []) if j.get("kind")=="collect"]
    assert len(collects)==1 and collects[0]["at"]==["07:00"]
