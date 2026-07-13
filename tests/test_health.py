from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import db, secrets
from engine.config_store import ConfigStore
from engine.health import (check_api_key, classify_api_error, collect_issues, spend,
                           spend_by_stage)

DEFAULTS = Path(__file__).resolve().parent.parent / "config" / "defaults"


def _db(tmp_path):
    conn = db.connect(tmp_path / "h.db"); db.init_schema(conn)
    store = ConfigStore(conn); store.reload(); store.seed_defaults(DEFAULTS)
    store.set("llm.provider", "anthropic")
    return conn, store


def _no_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path / "absent.env"


def test_env_write_read_roundtrip(tmp_path):
    p = tmp_path / ".env"
    p.write_text("OTHER=1\nANTHROPIC_API_KEY=old\n")
    secrets.write_env_var("ANTHROPIC_API_KEY", "sk-ant-new", p)
    env = secrets.read_env(p)
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-new" and env["OTHER"] == "1"


def test_env_preserves_other_lines_and_comments(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# comment\nFOO=bar\n")
    secrets.write_env_var("ANTHROPIC_API_KEY", "sk-x", p)
    txt = p.read_text()
    assert "# comment" in txt and "FOO=bar" in txt and "ANTHROPIC_API_KEY=sk-x" in txt


def test_env_file_is_private(tmp_path):
    p = tmp_path / ".env"
    secrets.write_env_var("ANTHROPIC_API_KEY", "sk-x", p)
    assert oct(p.stat().st_mode)[-3:] == "600"


def test_env_quoted_values(tmp_path):
    p = tmp_path / ".env"
    p.write_text('ANTHROPIC_API_KEY="sk-quoted"\n')
    assert secrets.read_env(p)["ANTHROPIC_API_KEY"] == "sk-quoted"


def test_mask_never_leaks_full_key():
    m = secrets.mask("sk-ant-api03-SECRETSECRETSECRET-9f2a")
    assert "SECRET" not in m and m.endswith("9f2a") and m.startswith("sk-ant-")
    assert secrets.mask("") == ""


def test_key_source(tmp_path, monkeypatch):
    p = _no_key(monkeypatch, tmp_path)
    assert secrets.key_source(p) == "missing"
    secrets.write_env_var("ANTHROPIC_API_KEY", "sk-x", p)
    assert secrets.key_source(p) == "env file"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert secrets.key_source(p) == "environment"


class _FakeMessages:
    def __init__(self, exc=None): self.exc = exc
    def create(self, **kw):
        if self.exc: raise self.exc
        return {"ok": True}


class _FakeClient:
    def __init__(self, exc=None): self.messages = _FakeMessages(exc)


def test_key_valid():
    r = check_api_key(client=_FakeClient(), key="sk-x")
    assert r["status"] == "ok" and r["code"] == "valid"


def test_key_missing(tmp_path, monkeypatch):
    absent = _no_key(monkeypatch, tmp_path)
    assert check_api_key(client=_FakeClient(), key=None, env_path=absent)["code"] == "missing"


def test_blank_key_falls_back_to_stored_one(tmp_path, monkeypatch):
    p = _no_key(monkeypatch, tmp_path)
    secrets.write_env_var("ANTHROPIC_API_KEY", "sk-stored", p)
    assert check_api_key(client=_FakeClient(), key="", env_path=p)["code"] == "valid"


def test_key_credit_exhausted():
    exc = Exception("Error 400: Your credit balance is too low to access the Anthropic API")
    r = check_api_key(client=_FakeClient(exc), key="sk-x")
    assert r["code"] == "credit" and "three different causes" in r["detail"]


def test_key_invalid_auth():
    exc = Exception("401 authentication_error: invalid x-api-key")
    assert check_api_key(client=_FakeClient(exc), key="sk-x")["code"] == "auth"


def test_key_rate_limited():
    exc = Exception("429 rate limit exceeded")
    assert check_api_key(client=_FakeClient(exc), key="sk-x")["code"] == "rate"


def test_classify_unknown_is_truncated():
    code, detail = classify_api_error(Exception("x" * 500))
    assert code == "unknown" and len(detail) <= 300


def _run(conn, stage, cost, tokens, ago_days=0):
    conn.execute("INSERT INTO stage_runs(run_id,stage_name,status,started_at,tokens,cost)"
                 " VALUES('r',?,'done',?,?,?)", (stage, time.time() - ago_days*86400, tokens, cost))
    conn.commit()


def test_spend_windows(tmp_path):
    conn, store = _db(tmp_path)
    _run(conn, "extract", 0.50, 1000, ago_days=0)
    _run(conn, "extract", 2.00, 4000, ago_days=10)
    _run(conn, "applicability", 1.00, 500, ago_days=40)
    assert round(spend(conn, 1)["cost"], 2) == 0.50
    assert round(spend(conn, 30)["cost"], 2) == 2.50
    top = spend_by_stage(conn, 30)
    assert top[0]["stage"] == "extract" and round(top[0]["cost"], 2) == 2.50


def test_issue_missing_api_key(tmp_path, monkeypatch):
    absent = _no_key(monkeypatch, tmp_path)
    conn, store = _db(tmp_path)
    assert any("stub" in i["title"] for i in collect_issues(conn, store, env_path=absent))


def test_no_stub_issue_when_key_present(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    conn, store = _db(tmp_path)
    assert not any("stub" in i["title"] for i in collect_issues(conn, store))


def test_issue_unpriced_model(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    conn, store = _db(tmp_path)
    m = dict(store.get("llm.models")); m["default"] = "claude-made-up-9"
    store.set("llm.models", m)
    assert any("llm.pricing" in i["title"] for i in collect_issues(conn, store))


def test_issue_schedule_without_times(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    conn, store = _db(tmp_path)
    store.set("schedule.jobs", [{"kind": "collect", "enabled": True, "at": [], "analyze": False}])
    issues = collect_issues(conn, store)
    assert any("no run times" in i["title"] for i in issues)
    assert any(i["level"] == "fail" for i in issues)


def test_issue_bad_timezone(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    conn, store = _db(tmp_path)
    store.set("schedule.timezone", "Mars/Olympus")
    store.set("schedule.jobs", [{"kind": "collect", "enabled": True, "at": ["06:00"]}])
    assert any("not recognised" in i["title"] for i in collect_issues(conn, store))


def test_issue_sites_but_genericweb_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    conn, store = _db(tmp_path)
    store.set("sites.tenders", [{"url": "http://a"}])
    assert any("genericweb' is disabled" in i["title"] for i in collect_issues(conn, store))


def test_issue_backlog_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    conn, store = _db(tmp_path)
    now = time.time()
    for i in range(250):
        conn.execute("INSERT INTO tenders(source,external_id,content_hash,status,created_at,updated_at)"
                     " VALUES('mtender',?,?,'new',?,?)", (f"t{i}", "h", now, now))
    conn.commit()
    store.set("schedule.jobs", [{"kind": "collect", "enabled": True, "at": ["06:00"], "analyze": True}])
    assert any("await analysis" in i["title"] for i in collect_issues(conn, store))


def test_no_issues_when_healthy(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    conn, store = _db(tmp_path)
    mt = dict(store.get("sources.mtender")); mt["enabled"] = True
    store.set("sources.mtender", mt)
    store.set("schedule.jobs", [])
    store.set("sites.tenders", [])
    assert collect_issues(conn, store) == []
