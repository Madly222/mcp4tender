from engine.dedup import site_token
from web.source_rank import move, sources_in_order


class FakeStore:
    def __init__(self, sites, rank=None, mtender=True):
        self._sites = sites
        self._rank = rank or []
        self._mt = mtender
        self.saved = None

    def get(self, key, default=None):
        if key == "sites.tenders":
            return self._sites
        if key == "sources.rank":
            return self._rank
        if key == "sources.mtender":
            return {"enabled": self._mt}
        return default

    def set(self, key, value, **kw):
        if key == "sources.rank":
            self._rank = value
        self.saved = (key, value)


A = {"id": "achizitii", "label": "achizitii.md", "url": "https://achizitii.md"}
B = {"id": "site-b", "label": "B", "url": "https://b.md"}


def test_default_order_mtender_then_sites():
    order = [t for t, _l, _k in sources_in_order(FakeStore([A, B], rank=[]))]
    assert order == ["mtender", "achizitii", "site-b"]


def test_rank_list_is_honoured_unranked_appended():
    order = [t for t, _l, _k in sources_in_order(
        FakeStore([A, B], rank=["achizitii", "mtender"]))]
    assert order == ["achizitii", "mtender", "site-b"]


def test_move_up_swaps_with_neighbour():
    store = FakeStore([A, B], rank=[])
    order = move(store, "achizitii", "up")
    assert order == ["achizitii", "mtender", "site-b"]


def test_move_down_swaps():
    store = FakeStore([A, B], rank=[])
    order = move(store, "mtender", "down")
    assert order == ["achizitii", "mtender", "site-b"]


def test_move_clamps_at_top():
    store = FakeStore([A, B], rank=[])
    assert move(store, "mtender", "up") == ["mtender", "achizitii", "site-b"]


def test_unknown_token_is_noop():
    store = FakeStore([A, B], rank=[])
    assert move(store, "ghost", "up") == ["mtender", "achizitii", "site-b"]


def test_site_without_id_uses_token():
    s = {"label": "No ID", "url": "https://noid.md"}
    order = [t for t, _l, _k in sources_in_order(FakeStore([s], rank=[]))]
    assert order == ["mtender", site_token(s)]
