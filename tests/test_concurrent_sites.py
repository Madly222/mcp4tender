from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db
from engine.config_store import ConfigStore
from web.sites_common import append_site, mutate_sites

DEFAULTS = str(Path(__file__).resolve().parent.parent / "config" / "defaults")


def _fresh(tmp_path):
    conn = db.connect(str(tmp_path / "t.db"))
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.seed_defaults(DEFAULTS)
    store.reload()
    return conn, store


def test_two_tabs_adding_sites_keep_both(tmp_path):
    conn, store = _fresh(tmp_path)
    tab_a = ConfigStore(conn)
    tab_a.reload()
    tab_b = ConfigStore(conn)
    tab_b.reload()
    append_site(tab_b, {"id": "bbb", "label": "Site B", "url": "https://b.md"},
                "tab B adds while tab A detects")
    append_site(tab_a, {"id": "aaa", "label": "Site A", "url": "https://a.md"},
                "tab A finishes its slow detect")
    fresh = ConfigStore(conn)
    fresh.reload()
    ids = {s["id"] for s in fresh.get("sites.tenders", [])}
    assert ids == {"aaa", "bbb"}


def test_settings_edit_does_not_erase_a_concurrent_add(tmp_path):
    conn, store = _fresh(tmp_path)
    append_site(store, {"id": "one", "label": "One", "url": "https://one.md",
                        "batch_size": 30}, "seed")
    stale = ConfigStore(conn)
    stale.reload()
    append_site(store, {"id": "two", "label": "Two", "url": "https://two.md"},
                "added from another tab")

    def apply(lst):
        for s in lst:
            if s.get("id") == "one":
                s["batch_size"] = 99

    mutate_sites(stale, apply, "edit from the stale tab")
    fresh = ConfigStore(conn)
    fresh.reload()
    sites = {s["id"]: s for s in fresh.get("sites.tenders", [])}
    assert set(sites) == {"one", "two"}
    assert sites["one"]["batch_size"] == 99


def test_remove_via_helper_removes_only_the_target(tmp_path):
    conn, store = _fresh(tmp_path)
    append_site(store, {"id": "one", "label": "One", "url": "https://one.md"}, "seed")
    append_site(store, {"id": "two", "label": "Two", "url": "https://two.md"}, "seed")

    def apply(lst):
        lst[:] = [s for s in lst if s.get("id") != "one"]

    mutate_sites(store, apply, "remove")
    fresh = ConfigStore(conn)
    fresh.reload()
    assert [s["id"] for s in fresh.get("sites.tenders", [])] == ["two"]
