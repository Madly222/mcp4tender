from __future__ import annotations
import json, sys
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
def _collect(p):
    return settings_ops.collect_job(_store(p))
def test_parse_times_drops_junk_and_sorts():
    assert settings_ops.parse_times("06:00, 18:00") == ["06:00", "18:00"]
    assert settings_ops.parse_times("18:00 06:00") == ["06:00", "18:00"]
    assert settings_ops.parse_times("6:00") == ["06:00"]
    assert settings_ops.parse_times("25:00, nonsense, 12:61") == []
    assert settings_ops.parse_times("06:00, 06:00") == ["06:00"]
    assert len(settings_ops.parse_times(",".join(f"{h:02d}:00" for h in range(24)) + ",23:30")) == 24
def test_schedule_form_replaces_the_raw_json(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"sc1.db"); conn.close()
    h = _login(p).get("/app/settings/schedule").text
    assert "When we scan" in h and 'name="times"' in h and 'name="day_0"' in h
    assert 'name="src_mtender"' in h and 'name="timezone"' in h
    assert "schedule.jobs" not in h and "schedule.timezone" not in h
    assert "analyze.batch_size" in h
def test_saving_a_schedule(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"sc2.db"); conn.close()
    r = _login(p).post("/app/settings/schedule/save", data={
        "enabled": "on", "times": "07:30, 19:00", "day_0": "on", "day_4": "on",
        "timezone": "Europe/Chisinau", "src_mtender": "on", "analyze": "on"})
    assert r.status_code == 303 and "saved=" in r.headers["location"]
    job = _collect(p)
    assert job["enabled"] is True and job["at"] == ["07:30", "19:00"]
    assert job["days"] == [0, 4] and job["sources"] == ["mtender"] and job["analyze"] is True
    assert _store(p).get("schedule.timezone") == "Europe/Chisinau"
def test_unticked_boxes_mean_off_not_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"sc3.db"); conn.close()
    c = _login(p)
    c.post("/app/settings/schedule/save",
           data={"enabled": "on", "times": "07:00", "analyze": "on", "src_mtender": "on"})
    assert _collect(p)["analyze"] is True
    c.post("/app/settings/schedule/save", data={"times": "07:00"})
    job = _collect(p)
    assert job["enabled"] is False and job["analyze"] is False
    assert job["sources"] == ["mtender", "genericweb"], "no source ticked means all of them"
def test_bad_timezone_warns_but_still_saves(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"sc4.db"); conn.close()
    r = _login(p).post("/app/settings/schedule/save",
                       data={"enabled": "on", "times": "07:00", "timezone": "Mars/Olympus"})
    assert "warning" in r.headers["location"]
    assert _store(p).get("schedule.timezone") == "Mars/Olympus"
def test_enabled_without_valid_times_warns(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"sc5.db"); conn.close()
    r = _login(p).post("/app/settings/schedule/save",
                       data={"enabled": "on", "times": "nonsense"})
    assert "will+not+fire" in r.headers["location"] or "will%20not%20fire" in r.headers["location"]
def test_other_jobs_are_left_alone(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"sc6.db")
    ConfigStore(conn).set("schedule.jobs", [{"pipeline": "tender_triage", "at": ["03:00"],
                                             "enabled": True}])
    conn.commit(); conn.close()
    c = _login(p)
    assert "1 other job(s) are configured" in c.get("/app/settings/schedule").text
    c.post("/app/settings/schedule/save", data={"enabled": "on", "times": "07:00"})
    jobs = _store(p).get("schedule.jobs")
    assert any(j.get("pipeline") == "tender_triage" for j in jobs)
    assert any(j.get("kind") == "collect" for j in jobs)
def test_read_only_blocks_the_schedule(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"sc7.db")
    ConfigStore(conn).set("web.read_only", True); conn.commit(); conn.close()
    before = json.dumps(_store(p).get("schedule.jobs"))
    r = _login(p).post("/app/settings/schedule/save", data={"enabled": "on", "times": "07:00"})
    assert "err=" in r.headers["location"]
    assert json.dumps(_store(p).get("schedule.jobs")) == before
