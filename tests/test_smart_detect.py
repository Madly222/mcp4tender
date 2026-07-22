from workflows.collectors.genericweb_analyze import smart_detect


class Fakes:
    def __init__(self, detect_map, analyze_map=None, preview_map=None):
        self.detect_map = detect_map
        self.analyze_map = analyze_map or {}
        self.preview_map = preview_map or {}
        self.detect_calls = []

    def detect(self, store, conn, url, auth=None):
        self.detect_calls.append(url)
        return self.detect_map.get(url, {"engine": "builtin", "render": False, "count": 0,
                                         "estimate": None, "needs_login": False})

    def analyze(self, store, conn, url, render=False, auth=None, engine=None):
        return self.analyze_map.get(url, {"follow": []})

    def preview(self, store, conn, url, render=False, engine=None, auth=None):
        return self.preview_map.get(url, {"count": 0, "next": None})


def _run(f, url):
    return smart_detect(None, None, url, detect=f.detect, analyze=f.analyze, preview=f.preview)


def test_landing_has_tenders_and_pagination_confirmed():
    f = Fakes(
        detect_map={"https://s.md/list": {"engine": "builtin", "render": False, "count": 12,
                                          "estimate": None, "needs_login": False}},
        preview_map={"https://s.md/list": {"count": 12, "next": "https://s.md/list?page=2"},
                     "https://s.md/list?page=2": {"count": 10, "next": None}})
    out = _run(f, "https://s.md/list")
    assert out["url"] == "https://s.md/list" and out["count"] == 12
    assert out["paginated"] is True


def test_follows_to_the_real_listing_when_landing_empty():
    f = Fakes(
        detect_map={"https://s.md": {"engine": "builtin", "render": False, "count": 0,
                                     "estimate": None, "needs_login": False},
                    "https://s.md/achizitii": {"engine": "builtin", "render": True, "count": 8,
                                               "estimate": None, "needs_login": False}},
        analyze_map={"https://s.md": {"follow": [{"label": "Achizitii",
                                                  "url": "https://s.md/achizitii"}]}},
        preview_map={"https://s.md/achizitii": {"count": 8, "next": None}})
    out = _run(f, "https://s.md")
    assert out["url"] == "https://s.md/achizitii"
    assert out["count"] == 8 and out["render"] is True
    assert out["paginated"] is False


def test_single_page_site_is_valid_not_paginated():
    f = Fakes(
        detect_map={"https://s.md/t": {"engine": "builtin", "render": False, "count": 5,
                                       "estimate": None, "needs_login": False}},
        preview_map={"https://s.md/t": {"count": 5, "next": None}})
    out = _run(f, "https://s.md/t")
    assert out["paginated"] is False and out["count"] == 5


def test_pagination_next_page_empty_means_not_paginated():
    f = Fakes(
        detect_map={"https://s.md/t": {"engine": "builtin", "render": False, "count": 5,
                                       "estimate": None, "needs_login": False}},
        preview_map={"https://s.md/t": {"count": 5, "next": "https://s.md/t?page=2"},
                     "https://s.md/t?page=2": {"count": 0, "next": None}})
    out = _run(f, "https://s.md/t")
    assert out["paginated"] is False


def test_needs_login_skips_follow():
    f = Fakes(
        detect_map={"https://s.md": {"engine": "builtin", "render": False, "count": 0,
                                     "estimate": None, "needs_login": True}})
    out = _run(f, "https://s.md")
    assert out["needs_login"] is True and out["url"] == "https://s.md"
    assert f.detect_calls == ["https://s.md"]
