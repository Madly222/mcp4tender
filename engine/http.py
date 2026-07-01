from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

USER_AGENT = "tenderengine/1.0 (+https://rapidlink.md)"


def get_json(url, timeout=30, retries=2, backoff=2, sleep_fn=time.sleep):
    last_err = None
    attempt = 0
    while attempt <= retries:
        attempt += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                       "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError) as exc:
            last_err = exc
            if attempt <= retries:
                sleep_fn(backoff)
    raise RuntimeError(f"GET failed after {attempt} attempts: {url}: {last_err}")


def get_text(url, timeout=30, retries=2, backoff=2, sleep_fn=time.sleep, headers=None):
    last_err = None
    attempt = 0
    base_headers = {"User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml"}
    if headers:
        base_headers.update(headers)
    while attempt <= retries:
        attempt += 1
        try:
            req = urllib.request.Request(url, headers=base_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_err = exc
            if attempt <= retries:
                sleep_fn(backoff)
    raise RuntimeError(f"GET text failed after {attempt} attempts: {url}: {last_err}")
