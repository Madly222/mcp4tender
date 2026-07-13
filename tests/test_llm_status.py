from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import db
from engine.config_store import ConfigStore
from engine.health import (classify_api_error, collect_issues, error_counts, llm_status,
                           provider_in_use, recent_llm_errors)
from fastapi.testclient import TestClient
from web.server import create_app

DEFAULTS = Path(__file__).resolve().parent.parent / "config" / "defaults"


def _db(tmp_path, name="l.db"):
    p = str(tmp_path / name)
    conn = db.connect(p); db.init_schema(conn)
    store = ConfigStore(conn); store.reload(); store.seed_defaults(DEFAULTS)
    return p, conn, store


def _err(conn, stage, msg, ago_h=1, tender_id=None):
    conn.execute("INSERT INTO stage_runs(run_id,stage_name,tender_id,status,started_at,error)"
                 " VALUES('r',?,?,'error',?,?)",
                 (stage, tender_id, time.time() - ago_h * 3600, msg))
    conn.commit()


# ---- classification of the messages the API actually returns ----

def test_classify_credit():
    assert classify_api_error("Error code: 400 - Your credit balance is too low")[0] == "credit"

def test_classify_auth():
    assert classify_api_error("authentication_error: invalid x-api-key")[0] == "auth"

def test_classify_rate_and_overloaded():
    assert classify_api_error("429 rate limit")[0] == "rate"
    assert classify_api_error("529 overloaded_error")[0] == "rate"

def test_classify_model_and_network():
    assert classify_api_error("404 model does not exist")[0] == "model"
    assert classify_api_error("Connection timeout to api.anthropic.com")[0] == "network"

def test_classify_empty_prompt():
    assert classify_api_error("empty prompt content - nothing to send")[0] == "prompt"


# ---- the log ----

def test_recent_errors_newest_first(tmp_path):
    _, conn, _ = _db(tmp_path)
    _err(conn, "extract", "429 rate limit", ago_h=5)
    _err(conn, "applicability", "credit balance is too low", ago_h=1, tender_id=42)
    errs = recent_llm_errors(conn, days=7)
    assert errs[0]["code"] == "credit" and errs[0]["tender_id"] == 42
    assert errs[1]["code"] == "rate"
    assert "credit balance" in errs[0]["raw"]


def test_errors_outside_window_ignored(tmp_path):
    _, conn, _ = _db(tmp_path)
    _err(conn, "extract", "429 rate limit", ago_h=24 * 30)
    assert recent_llm_errors(conn, days=7) == []


def test_error_counts_group(tmp_path):
    _, conn, _ = _db(tmp_path)
    _err(conn, "extract", "429 rate limit")
    _err(conn, "extract", "rate limit exceeded")
    _err(conn, "verify", "invalid x-api-key")
    assert error_counts(conn, days=7) == {"rate": 2, "auth": 1}


def test_successful_runs_are_not_errors(tmp_path):
    _, conn, _ = _db(tmp_path)
    conn.execute("INSERT INTO stage_runs(run_id,stage_name,status,started_at,error)"
                 " VALUES('r','extract','done',?,NULL)", (time.time(),))
    conn.execute("INSERT INTO stage_runs(run_id,stage_name,status,started_at,error)"
                 " VALUES('r','extract','done',?,'')", (time.time(),))
    conn.commit()
    assert recent_llm_errors(conn) == []


# ---- status ----

def test_status_ok_when_no_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    _, conn, store = _db(tmp_path)
    store.set("llm.provider", "anthropic")
    st = llm_status(conn, store)
    assert st["state"] == "ok" and "No LLM errors" in st["why"]


def test_status_fail_on_credit_error(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    _, conn, store = _db(tmp_path)
    store.set("llm.provider", "anthropic")
    _err(conn, "extract", "Your credit balance is too low")
    st = llm_status(conn, store)
    assert st["state"] == "fail" and "Out of credits" in st["why"]


def test_status_warn_on_transient_error(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    _, conn, store = _db(tmp_path)
    store.set("llm.provider", "anthropic")
    _err(conn, "extract", "429 rate limit")
    assert llm_status(conn, store)["state"] == "warn"


def test_status_fail_when_stub(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _, conn, store = _db(tmp_path)
    st = llm_status(conn, store, env_path=tmp_path / "absent.env")
    assert st["provider"] == "stub" and st["state"] == "fail"


def test_provider_in_use(tmp_path, monkeypatch):
    _, conn, store = _db(tmp_path)
    store.set("llm.provider", "stub")
    assert provider_in_use(store) == "stub"


# ---- issues: no more crying wolf about missing per-stage models ----

def test_no_false_alarm_for_unset_stage_models(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    _, conn, store = _db(tmp_path)
    store.set("llm.models", {"default": "claude-haiku-4-5-20251001"})
    issues = collect_issues(conn, store)
    assert not any("No model set" in i["title"] for i in issues)


def test_credit_error_is_promoted_to_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    _, conn, store = _db(tmp_path)
    _err(conn, "extract", "Your credit balance is too low")
    issues = collect_issues(conn, store)
    assert any(i["level"] == "fail" and "LLM calls are failing: credit" in i["title"]
               for i in issues)


def test_rate_limit_is_not_promoted_to_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    _, conn, store = _db(tmp_path)
    _err(conn, "extract", "429 rate limit")
    assert not any("LLM calls are failing" in i["title"] for i in collect_issues(conn, store))


# ---- page ----

def test_page_shows_llm_section_and_raw_error(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    p, conn, store = _db(tmp_path)
    store.set("llm.provider", "anthropic")
    _err(conn, "extract", "Error 400: Your credit balance is too low", tender_id=7)
    conn.close()
    h = TestClient(create_app(p)).get("/user-settings").text
    assert ">LLM status<" in h
    assert "provider in use" in h and "credit balance" in h
    assert "Last LLM failures" in h
    assert "Your credit balance is too low" in h      # the raw API message is shown
    assert "tender #7" in h


def test_page_says_no_failures_when_clean(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    p, conn, store = _db(tmp_path)
    store.set("llm.provider", "anthropic")
    conn.close()
    h = TestClient(create_app(p)).get("/user-settings").text
    assert "No LLM call has failed in the last 7 days" in h
    assert "No model set" not in h
