from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from workflows import notify, work

DEFAULTS = str(Path(__file__).resolve().parent.parent / "config" / "defaults")


def _fresh(tmp_path, name):
    p = str(tmp_path / name)
    conn = db.connect(p)
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.seed_defaults(DEFAULTS)
    store.reload()
    return p, conn, store


def _add(conn, ext="a1", title="Retea de calculatoare"):
    now = time.time()
    nj = {"title": title, "buyer": "STISC", "value_amount": 500000,
          "value_currency": "MDL", "deadline": "2026-08-30",
          "url": "https://achizitii.md/t/1",
          "documents": [{"title": "Caiet.pdf", "url": "http://x/1.pdf"}]}
    conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "origin, created_at, updated_at) VALUES('genericweb',?,?,?,'analyzed',"
        "'incremental',?,?)", (ext, "h" + ext, json.dumps(nj), now, now))
    tid = conn.execute("SELECT id FROM tenders WHERE external_id=?", (ext,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO verdicts(tender_id, stage_name, verdict, score, reason, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (tid, "applicability", "can", 85,
         json.dumps({"reasoning": "profil potrivit", "gaps": ["certificare X"],
                     "required_equipment": ["switch 48p"]}), now))
    conn.execute(
        "INSERT INTO extractions(tender_id, fields_json, sources_json, model, method, "
        "tokens, cost, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (tid, json.dumps({"obiect": "retea", "valoare_estimata": "500000 MDL"}),
         "[]", "m", "metadata", 0, 0, now))
    conn.commit()
    return tid


def test_build_message_contains_the_essentials(tmp_path):
    p, conn, store = _fresh(tmp_path, "n1.db")
    tid = _add(conn)
    msg = notify.build_message(store, conn, tid)
    assert "Retea de calculatoare" in msg["subject"]
    assert "STISC" in msg["text"] and "https://achizitii.md/t/1" in msg["text"]
    md = msg["content"].decode("utf-8")
    assert "certificare X" in md and "switch 48p" in md and "Caiet.pdf" in md
    assert msg["filename"].endswith(".md")
    conn.close()


def test_notify_off_by_default(tmp_path):
    p, conn, store = _fresh(tmp_path, "n2.db")
    tid = _add(conn)
    res = notify.notify_tender(store, conn, tid)
    assert res["status"] == "off"
    conn.close()


def test_notify_sends_only_where_enabled(tmp_path):
    p, conn, store = _fresh(tmp_path, "n3.db")
    tid = _add(conn)
    store.set("notify.telegram.enabled", True)
    store.set("notify.telegram.chat_id", "-100123")
    calls = []
    res = notify.notify_tender(store, conn, tid,
                               emailer=lambda s, m: calls.append("email") or "sent",
                               telegrammer=lambda s, m: calls.append("tg") or "sent")
    assert calls == ["tg"]
    assert res["status"] == "ok"
    conn.close()


def test_notify_both_when_both_enabled(tmp_path):
    p, conn, store = _fresh(tmp_path, "n4.db")
    tid = _add(conn)
    store.set("notify.email.enabled", True)
    store.set("notify.telegram.enabled", True)
    calls = []
    res = notify.notify_tender(store, conn, tid,
                               emailer=lambda s, m: calls.append("email") or "sent",
                               telegrammer=lambda s, m: calls.append("tg") or "sent")
    assert calls == ["email", "tg"]
    assert res["status"] == "ok"
    conn.close()


def test_send_email_reports_missing_fields(tmp_path):
    p, conn, store = _fresh(tmp_path, "n5.db")
    tid = _add(conn)
    msg = notify.build_message(store, conn, tid)
    out = notify.send_email(store, msg, password="")
    assert out.startswith("skipped")
    assert "host" in out and "from" not in out.replace("sender", "")
    conn.close()


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=30):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        FakeSMTP.sent.append("tls")

    def login(self, user, password):
        FakeSMTP.sent.append(("login", user, password))

    def send_message(self, m):
        FakeSMTP.sent.append(("msg", m["Subject"], m["To"]))


def test_send_email_happy_path(tmp_path):
    p, conn, store = _fresh(tmp_path, "n6.db")
    tid = _add(conn)
    store.set("notify.email.host", "10.0.0.5")
    store.set("notify.email.from", "tenders@rapid.md")
    store.set("notify.email.to", "victor@rapid.md, sales@rapid.md")
    store.set("notify.email.login", "tenders@rapid.md")
    FakeSMTP.sent = []
    msg = notify.build_message(store, conn, tid)
    out = notify.send_email(store, msg, password="secret", smtp_cls=FakeSMTP)
    assert out == "sent"
    assert "tls" in FakeSMTP.sent
    assert ("login", "tenders@rapid.md", "secret") in FakeSMTP.sent
    assert any(x[0] == "msg" and "victor@rapid.md" in x[2] for x in FakeSMTP.sent
               if isinstance(x, tuple))
    conn.close()


def test_send_telegram_message_and_document(tmp_path):
    p, conn, store = _fresh(tmp_path, "n7.db")
    tid = _add(conn)
    store.set("notify.telegram.chat_id", "-100123")
    posts = []
    msg = notify.build_message(store, conn, tid)
    out = notify.send_telegram(store, msg, token="123:abc",
                               post=lambda url, data, ct: posts.append((url, ct)))
    assert out == "sent"
    assert posts[0][0].endswith("/sendMessage")
    assert posts[1][0].endswith("/sendDocument")
    assert "multipart/form-data" in posts[1][1]
    assert "123:abc" in posts[0][0]
    conn.close()


def test_send_telegram_skips_without_token(tmp_path):
    p, conn, store = _fresh(tmp_path, "n8.db")
    tid = _add(conn)
    store.set("notify.telegram.chat_id", "-100123")
    msg = notify.build_message(store, conn, tid)
    out = notify.send_telegram(store, msg, token="")
    assert out.startswith("skipped") and "bot token" in out
    conn.close()


def _login(p, conn):
    accounts.create(conn, "rapid", "password123", company="Rapid Link")
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rapid",
                                  "password": "password123"}).status_code == 303
    return c


def test_send_button_and_route(tmp_path, monkeypatch):
    p, conn, store = _fresh(tmp_path, "n9.db")
    tid = _add(conn)
    work.set_stage(conn, tid, 1, "qualified")
    c = _login(p, conn)
    page = c.get("/app/qualified").text
    assert f"/app/qualified/{tid}/send" in page
    sent = []
    monkeypatch.setattr(notify, "notify_tender",
                        lambda s, cn, t, **k: sent.append(t) or
                        {"status": "ok", "detail": "email sent"})
    r = c.post(f"/app/qualified/{tid}/send", data={"back": "/app/qualified"})
    assert r.status_code == 303 and sent == [tid]
    assert "msg=" in r.headers["location"]
    page = c.get(r.headers["location"]).text
    assert "email sent" in page


def test_send_route_reports_off(tmp_path):
    p, conn, store = _fresh(tmp_path, "n10.db")
    tid = _add(conn)
    work.set_stage(conn, tid, 1, "qualified")
    c = _login(p, conn)
    r = c.post(f"/app/qualified/{tid}/send", data={"back": "/app/qualified"})
    assert "err=" in r.headers["location"]
    page = c.get(r.headers["location"]).text
    assert "Not sent" in page and "Sending results" in page


def test_settings_page_has_the_section(tmp_path):
    p, conn, store = _fresh(tmp_path, "n11.db")
    c = _login(p, conn)
    hub = c.get("/app/settings").text
    assert "Sending results" in hub
    page = c.get("/app/settings/sending").text
    assert "Sending credentials" in page
    assert "smtp_password" in page and "tg_token" in page
    assert "Send by email" in page and "Telegram chat or group ID" in page
