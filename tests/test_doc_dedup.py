import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

from workflows.collectors.mtender import (dedupe_documents, _doc_title_key,
                                          _doc_version)


def _d(title, ts):
    return {"title": title, "url": f"http://s/get/uuid-{ts}",
            "type": None, "format": "docx", "datePublished": "2026-06-05"}


def test_title_key_normalizes_case_and_space():
    assert _doc_title_key("Anexa 22.docx", "x") == "anexa 22.docx"
    assert _doc_title_key("  ANEXA 22.docx ", "x") == "anexa 22.docx"


def test_title_key_falls_back_to_url_filename_without_timestamp():
    a = _doc_title_key(None, "http://s/get/abc-1780657928243")
    b = _doc_title_key("", "http://s/get/abc-1780658057876")
    assert a == b == "abc"


def test_version_prefers_url_timestamp():
    assert _doc_version(_d("x", 1780658376344)) > _doc_version(_d("x", 1780657928243))


def test_keeps_newest_of_same_title():
    docs = [_d("anexa 22.docx", 1780657928243),
            _d("anexa 22.docx", 1780658057876),
            _d("anexa 22.docx", 1780658376344)]
    out = dedupe_documents(docs)
    assert len(out) == 1
    assert out[0]["url"].endswith("1780658376344")


def test_distinct_titles_all_kept():
    docs = [_d("anunt.pdf", 1), _d("caiet.pdf", 2), _d("anexa 5.docx", 3)]
    assert len(dedupe_documents(docs)) == 3


def test_first_seen_order_preserved():
    docs = [_d("a.pdf", 1), _d("b.pdf", 1), _d("a.pdf", 9)]
    out = dedupe_documents(docs)
    assert [_doc_title_key(d["title"], d["url"]) for d in out] == ["a.pdf", "b.pdf"]
    assert out[0]["url"].endswith("-9")


def test_real_tender_386_collapses_18_to_10():
    raw = [
        ("anunț de participare.pdf", 1780645751516),
        ("caiet de sarcini echipament etd.pdf", 1780645774897),
        ("caiet de sarcini echipament leds.pdf", 1780645846539),
        ("cerere de participare anexa 7.docx", 1780645863171),
        ("declarație anexa 5.docx", 1780645878771),
        ("declarație privind valabilitatea oferte.docx", 1780645996314),
        ("garanția de bună execuție anexa 10.docx", 1780646023494),
        ("garanție de ofertă anexa 9.docx", 1780646037297),
        ("specificații de preț anexa 23.docx", 1780657915009),
        ("specificații tehnice anexa 22.docx", 1780657928243),
        ("anunț de participare.pdf", 1780646649147),
        ("caiet de sarcini echipament leds.pdf", 1780646669214),
        ("specificații de preț anexa 23.docx", 1780658043855),
        ("specificații tehnice anexa 22.docx", 1780658057876),
        ("anunț de participare.pdf", 1780658279971),
        ("caiet de sarcini echipament etd.pdf", 1780658306944),
        ("specificații de preț anexa 23.docx", 1780658361284),
        ("specificații tehnice anexa 22.docx", 1780658376344),
    ]
    docs = [_d(t, ts) for t, ts in raw]
    out = dedupe_documents(docs)
    assert len(out) == 10
    titles = {_doc_title_key(d["title"], d["url"]) for d in out}
    assert len(titles) == 10
    by = {_doc_title_key(d["title"], d["url"]): d["url"] for d in out}
    assert by["specificații tehnice anexa 22.docx"].endswith("1780658376344")
    assert by["anunț de participare.pdf"].endswith("1780658279971")


def test_dedupe_documents_db():
    from workflows.analysis import dedupe_documents_db
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE tenders(id INTEGER PRIMARY KEY, source TEXT, "
                 "normalized_json TEXT)")
    duped = {"documents": [_d("a.pdf", 1), _d("a.pdf", 9), _d("b.pdf", 2)]}
    clean = {"documents": [_d("c.pdf", 1)]}
    conn.execute("INSERT INTO tenders(source,normalized_json) VALUES('mtender',?)",
                 (json.dumps(duped),))
    conn.execute("INSERT INTO tenders(source,normalized_json) VALUES('mtender',?)",
                 (json.dumps(clean),))
    conn.execute("INSERT INTO tenders(source,normalized_json) VALUES('genericweb',?)",
                 (json.dumps(duped),))
    res = dedupe_documents_db(conn)
    assert res == {"tenders_changed": 1, "documents_removed": 1}
    row = conn.execute("SELECT normalized_json FROM tenders WHERE id=1").fetchone()
    docs = json.loads(row["normalized_json"])["documents"]
    assert len(docs) == 2
    assert docs[0]["url"].endswith("-9")
