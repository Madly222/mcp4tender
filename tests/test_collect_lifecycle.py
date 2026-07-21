import datetime as dt

from engine import db, lifecycle
from engine.collectors import _store_item, CollectedItem


class FakeStore:
    def __init__(self, closed=("cancelled", "anulat"), pending=("planning", "planned")):
        self._closed = list(closed)
        self._pending = list(pending)

    def get(self, key, default=None):
        if key == "results.closed_statuses":
            return self._closed
        if key == "results.pending_statuses":
            return self._pending
        return default


def _conn(tmp_path):
    conn = db.connect(str(tmp_path / "t.db"))
    db.init_schema(conn)
    return conn


def _iso(days):
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


def _put(conn, store, ext, nj):
    return _store_item(conn, "genericweb", CollectedItem(external_id=ext, raw={}, normalized=nj),
                       "incremental", store)


def _count(conn):
    return conn.execute("SELECT COUNT(*) AS n FROM tenders").fetchone()["n"]


def test_keeps_open_future_deadline(tmp_path):
    conn, store = _conn(tmp_path), FakeStore()
    assert _put(conn, store, "s:1", {"title": "A", "buyer": "B", "deadline": _iso(10)}) is True
    assert _count(conn) == 1


def test_drops_past_deadline(tmp_path):
    conn, store = _conn(tmp_path), FakeStore()
    assert _put(conn, store, "s:2", {"title": "A", "buyer": "B", "deadline": _iso(-3)}) is False
    assert _count(conn) == 0


def test_drops_awarded(tmp_path):
    conn, store = _conn(tmp_path), FakeStore()
    assert _put(conn, store, "s:3", {"title": "A", "buyer": "B", "awarded": True,
                                     "deadline": _iso(10)}) is False
    assert _count(conn) == 0


def test_drops_cancelled_status(tmp_path):
    conn, store = _conn(tmp_path), FakeStore()
    assert _put(conn, store, "s:4", {"title": "A", "buyer": "B", "status_details": "Anulat"}) is False
    assert _count(conn) == 0


def test_keeps_planning_without_deadline(tmp_path):
    conn, store = _conn(tmp_path), FakeStore()
    assert _put(conn, store, "s:5", {"title": "A", "buyer": "B", "status": "planning"}) is True
    assert _count(conn) == 1


def test_keeps_undated_unknown(tmp_path):
    conn, store = _conn(tmp_path), FakeStore()
    assert _put(conn, store, "s:6", {"title": "A", "buyer": "B"}) is True
    assert _count(conn) == 1


def test_no_store_disables_gate(tmp_path):
    conn = _conn(tmp_path)
    r = _store_item(conn, "genericweb",
                    CollectedItem(external_id="s:7", raw={},
                                  normalized={"title": "A", "buyer": "B", "deadline": _iso(-3)}),
                    "incremental")
    assert r is True and _count(conn) == 1


def test_keep_on_collect_matches_state_of(tmp_path):
    store = FakeStore()
    live = {"title": "A", "buyer": "B", "deadline": _iso(5)}
    dead = {"title": "A", "buyer": "B", "deadline": _iso(-5)}
    assert lifecycle.keep_on_collect(live, store) is True
    assert lifecycle.keep_on_collect(dead, store) is False
