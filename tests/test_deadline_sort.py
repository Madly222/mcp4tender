import datetime as dt
import json

from web.user import cards


def _row(nj, ex_fields=None):
    return {"external_id": "s:1", "ex_fields": json.dumps(ex_fields) if ex_fields else None,
            "normalized_json": json.dumps(nj)}


def _iso(days):
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


def test_cell_when_shows_na_without_deadline():
    html = cards.cell_when(_row({"title": "T"}), {"title": "T"}, __import__("time").time())
    assert ">N/A<" in html


def test_cell_when_shows_deadline():
    nj = {"title": "T", "deadline": _iso(5)}
    html = cards.cell_when(_row(nj), nj, __import__("time").time())
    assert "N/A" not in html


def test_deadline_ts_none_when_absent():
    assert cards.deadline_ts(_row({"title": "T"}), {"title": "T"}) is None


def test_deadline_ts_uses_extracted_fallback():
    nj = {"title": "T"}
    row = _row(nj, ex_fields={"data_depunerii": _iso(3)})
    assert cards.deadline_ts(row, nj) is not None


def test_deadline_sort_orders_soonest_first_na_last():
    items = [
        ("far", {"deadline": _iso(30)}),
        ("na", {}),
        ("soon", {"deadline": _iso(2)}),
    ]

    def key(it):
        ts = cards.deadline_ts(_row(it[1]), it[1])
        return (ts is None, ts or 0)

    order = [name for name, _ in sorted(items, key=key)]
    assert order == ["soon", "far", "na"]
