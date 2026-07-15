from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest
from engine import accounts, db, user_settings
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn); ConfigStore(conn).reload()
    return p, conn
def _add(conn, ext, title, age_days):
    now = time.time() - age_days*86400
    nj = {"title": title, "buyer": "STISC", "value_amount": 1000, "value_currency": "MDL",
          "cpv": [], "documents": [],
          "deadline": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time()+30*86400))}
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at) VALUES('mtender',?,?,?,'analyzed','incremental',?,?)",
                 (ext, "h"+ext, json.dumps(nj), now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    conn.execute("INSERT INTO verdicts(tender_id,stage_name,verdict,score,created_at) VALUES(?,'applicability','can',90,?)",
                 (tid, time.time()))
    conn.commit(); return tid
def _login(p, login="rl"):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": login, "password": "password1"}).status_code == 303
    return c
def test_clamp_rejects_junk_and_out_of_range():
    with pytest.raises(ValueError):
        user_settings.clamp("results.new_days", "abc")
    with pytest.raises(ValueError):
        user_settings.clamp("results.new_days", 0)
    with pytest.raises(ValueError):
        user_settings.clamp("results.new_days", 500)
    assert user_settings.clamp("results.new_days", " 14 ") == 14
def test_settings_are_per_account(tmp_path):
    p, conn = _fresh(tmp_path,"p1.db")
    user_settings.set_many(conn, 1, {"results.new_days": 20})
    user_settings.set_many(conn, 2, {"results.new_days": 3})
    assert user_settings.raw(conn, 1) == {"results.new_days": "20"}
    assert user_settings.raw(conn, 2) == {"results.new_days": "3"}
    conn.close()
def test_overlay_falls_back_to_the_global_store(tmp_path):
    p, conn = _fresh(tmp_path,"p2.db")
    store = ConfigStore(conn); store.reload()
    assert user_settings.view(conn, store, 1) is store
    user_settings.set_many(conn, 1, {"results.new_days": 21})
    v = user_settings.view(conn, store, 1)
    assert v.get("results.new_days") == 21
    assert v.get("results.archive_after_days", 90) == store.get("results.archive_after_days", 90)
    conn.close()
def test_new_days_actually_moves_a_tender_into_the_inbox(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"p3.db")
    _add(conn, "a1", "Vechiul de zece zile", age_days=10)
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    assert "Vechiul de zece zile" not in c.get("/app/inbox").text
    c.post("/app/preferences", data={"results.new_days": "20",
                                     "results.archive_after_days": "90"})
    assert "Vechiul de zece zile" in c.get("/app/inbox").text
def test_preferences_page_marks_yours_versus_default(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"p4.db")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    assert ">default</span>" in c.get("/app/preferences").text
    c.post("/app/preferences", data={"results.new_days": "14",
                                     "results.archive_after_days": "90"})
    h = c.get("/app/preferences?saved=1").text
    assert ">yours</span>" in h and "Saved" in h
def test_bad_input_is_refused_with_a_message(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"p5.db")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    c = _login(p)
    r = c.post("/app/preferences", data={"results.new_days": "999",
                                         "results.archive_after_days": "90"})
    assert "error=" in r.headers["location"]
    assert user_settings.raw(db.connect(p), 1) == {}
def test_reset_clears_only_your_rows(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"p6.db")
    accounts.create(conn, "rl", "password1", role="admin")
    accounts.create(conn, "other", "password1", role="user")
    user_settings.set_many(conn, 2, {"results.new_days": 30}); conn.close()
    c = _login(p)
    c.post("/app/preferences", data={"results.new_days": "14",
                                     "results.archive_after_days": "90"})
    c.post("/app/preferences", data={"reset": "1"})
    conn = db.connect(p)
    assert user_settings.raw(conn, 1) == {}
    assert user_settings.raw(conn, 2) == {"results.new_days": "30"}
def test_read_only_blocks_saving(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"p7.db")
    accounts.create(conn, "rl", "password1", role="admin")
    ConfigStore(conn).set("web.read_only", True); conn.commit(); conn.close()
    c = _login(p)
    c.post("/app/preferences", data={"results.new_days": "14",
                                     "results.archive_after_days": "90"})
    assert user_settings.raw(db.connect(p), 1) == {}
def test_page_is_honest_about_shared_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"p8.db")
    accounts.create(conn, "rl", "password1", role="admin"); conn.close()
    h = _login(p).get("/app/preferences").text
    assert "Set for everyone, not for you" in h
    assert "Capability profile" in h and "Keywords" in h
    assert "costs real money per company" in h
