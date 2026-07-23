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
