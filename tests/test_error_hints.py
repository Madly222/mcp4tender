from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.alerts import friendly
from workflows.verify import hint_items


def test_hint_items_survives_dict_issues():
    result = {"missing": ["valoare_estimata"],
              "issues": [{"field": "termen", "problem": "nu corespunde sursei"},
                         "obiect neclar", None, 7]}
    out = hint_items(result)
    assert "valoare_estimata" in out
    assert "termen nu corespunde sursei" in out
    assert "obiect neclar" in out and "7" in out
    assert "{" not in out


def test_hint_items_empty():
    assert hint_items({}) == ""
    assert hint_items({"missing": [], "issues": []}) == ""


def test_alert_translates_the_join_crash():
    hint = friendly("sequence item 4: expected str instance, dict found")
    assert hint and "Retry failed" in hint


def test_friendly_always_returns_a_human_sentence():
    for raw in ["", "sequence item 4: expected str instance, dict found",
                "HTTPSConnectionPool: getaddrinfo failed",
                "Read timed out after 30s", "429 Too Many Requests",
                "credit balance is too low", "Expecting value: line 1 column 1",
                "GET failed after 3 attempts: https://x: boom",
                "some totally novel error nobody mapped"]:
        out = friendly(raw)
        assert isinstance(out, str) and out.strip() and out[0].isupper()


def test_friendly_uses_stage_for_unknown_errors():
    out = friendly("weird unmapped failure", "extract")
    assert "reading the tender documents" in out
    out2 = friendly("weird unmapped failure", "suppliers")
    assert "looking up suppliers" in out2


def test_friendly_network_and_http_cases():
    assert "unreachable" in friendly("GET failed after 3 attempts: https://x: conn refused")
    assert "took too long" in friendly("Read timed out")
    assert "404" in friendly("HTTP 404 Not Found")
    assert "server error" in friendly("502 Bad Gateway")
    assert "JavaScript" in friendly("empty prompt content — nothing to send to the model")

