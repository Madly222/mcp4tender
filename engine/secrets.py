from __future__ import annotations

import os
import re
import stat
from pathlib import Path

ENV_FILENAME = ".env"
KEY_NAME = "ANTHROPIC_API_KEY"

_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def env_path(base=None):
    base = base or os.environ.get("TENDERENGINE_HOME") or Path.cwd()
    return Path(base) / ENV_FILENAME


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def read_env(path=None):
    path = Path(path) if path else env_path()
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if m:
            out[m.group(1)] = _unquote(m.group(2))
    return out


def write_env_var(name, value, path=None):
    path = Path(path) if path else env_path()
    lines = path.read_text().splitlines() if path.exists() else []
    out = []
    replaced = False
    for line in lines:
        m = _LINE_RE.match(line)
        if m and m.group(1) == name:
            if not replaced:
                out.append(f"{name}={value}")
                replaced = True
            continue
        out.append(line)
    if not replaced:
        out.append(f"{name}={value}")
    path.write_text("\n".join(out).strip() + "\n")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return path


def mask(value):
    if not value:
        return ""
    v = str(value)
    if len(v) <= 12:
        return v[:3] + "..."
    return v[:7] + "\u2026" + v[-4:]


def get_api_key(path=None):
    from_env = os.environ.get(KEY_NAME)
    if from_env:
        return from_env
    return read_env(path).get(KEY_NAME) or ""


def set_api_key(value, path=None):
    value = (value or "").strip()
    if not value:
        return None
    p = write_env_var(KEY_NAME, value, path)
    os.environ[KEY_NAME] = value
    return p


def key_source(path=None):
    if os.environ.get(KEY_NAME):
        return "environment"
    if read_env(path).get(KEY_NAME):
        return "env file"
    return "missing"
