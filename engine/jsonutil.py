from __future__ import annotations

import json
import re


def loads_loose(text):
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    i = s.find("{")
    j = s.rfind("}")
    if 0 <= i < j:
        try:
            return json.loads(s[i:j + 1])
        except json.JSONDecodeError:
            return None
    return None
