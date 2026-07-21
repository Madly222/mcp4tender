import json

from engine import db, dedup
from engine.collectors import _store_item, CollectedItem


class FakeStore:
    def __init__(self, rank):
        self._rank = rank

    def get(self, key, default=None):
        if key == "sources.rank":
            return self._rank
        return default


def _conn(tmp_path):
    conn = db.connect(str(tmp_path / "t.db"))
    db.init_schema(conn)
    return conn


def _item(site_id, title, buyer, extra=None):
    ext = f"{site_id}:{abs(hash(title + buyer)) % (10 ** 12):x}"
    nj = {"title": title, "buyer": buyer}
    if extra:
        nj.update(extra)
    return CollectedItem(external_id=ext, raw={"site": site_id}, normalized=nj)


def _rows(conn):
    return conn.execute(
        "SELECT source, external_id, normalized_json, dedup_key FROM tenders ORDER BY id"
    ).fetchall()


def test_dedup_key_normalises_title_and_buyer():
    a = dedup.dedup_key("Compresor de aer  (repetat)", "Primăria Chișinău")
    b = dedup.dedup_key("compresor de aer (repetat)", "primaria chisinau")
    assert a == b and a is not None


def test_dedup_key_needs_both_fields():
    assert dedup.dedup_key("has title", "") is None
    assert dedup.dedup_key("", "has buyer") is None


def test_stronger_source_overwrites_weaker(tmp_path):
    conn = _conn(tmp_path)
    store = FakeStore(["achizitii", "site2"])
    _store_item(conn, "genericweb", _item("site2", "Air compressor", "Town Hall"), "incremental", store)
    _store_item(conn, "genericweb", _item("achizitii", "Air compressor", "Town Hall"), "incremental", store)
    rows = _rows(conn)
    assert len(rows) == 1
    assert rows[0]["external_id"].startswith("achizitii:")


def test_weaker_source_cannot_overwrite(tmp_path):
    conn = _conn(tmp_path)
    store = FakeStore(["achizitii", "site2"])
    _store_item(conn, "genericweb", _item("achizitii", "Air compressor", "Town Hall"), "incremental", store)
    _store_item(conn, "genericweb", _item("site2", "Air compressor", "Town Hall"), "incremental", store)
    rows = _rows(conn)
    assert len(rows) == 1
    assert rows[0]["external_id"].startswith("achizitii:")


def test_different_buyer_is_not_a_duplicate(tmp_path):
    conn = _conn(tmp_path)
    store = FakeStore(["achizitii", "site2"])
    _store_item(conn, "genericweb", _item("achizitii", "Air compressor", "Buyer A"), "incremental", store)
    _store_item(conn, "genericweb", _item("site2", "Air compressor", "Buyer B"), "incremental", store)
    assert len(_rows(conn)) == 2


def test_overwrite_keeps_closed_signal(tmp_path):
    conn = _conn(tmp_path)
    store = FakeStore(["achizitii", "mtender"])
    _store_item(conn, "mtender",
                _item("mtender", "Air compressor", "Town Hall",
                      {"awarded": True, "status_details": "awarding"}),
                "incremental", store)
    _store_item(conn, "genericweb", _item("achizitii", "Air compressor", "Town Hall"),
                "incremental", store)
    rows = _rows(conn)
    assert len(rows) == 1
    nj = json.loads(rows[0]["normalized_json"])
    assert nj.get("awarded") is True
    assert nj.get("status_details") == "awarding"


def test_no_rank_list_still_dedupes_first_seen_wins(tmp_path):
    conn = _conn(tmp_path)
    store = FakeStore([])
    _store_item(conn, "genericweb", _item("site1", "Air compressor", "Town Hall"), "incremental", store)
    _store_item(conn, "genericweb", _item("site2", "Air compressor", "Town Hall"), "incremental", store)
    rows = _rows(conn)
    assert len(rows) == 1
    assert rows[0]["external_id"].startswith("site1:")
