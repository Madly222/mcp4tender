from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db
from engine.config_store import ConfigStore
from engine.runner import run_pipeline
import engine.documents as documents
import workflows  # noqa: F401
from workflows.extract import (extract_technical_section, dedupe_documents,
                               select_documents)


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("pipeline.tender_extract", ["extract"])
    store.set("llm.provider", "stub")
    store.set("extract.slice_min_chars", 100)
    store.set("extract.min_offset_ratio", 0.15)
    store.set("extract.section_markers", ["cerinte tehnice", "specificatii tehnice"])
    store.set("extract.section_prefix_chars", 0)
    return conn, store


def test_slice_short_returns_whole(tmp_path):
    _, store = fresh(tmp_path)
    text = "scurt text tehnic"
    out, meta = extract_technical_section(text, store)
    assert out == text
    assert meta["sliced"] is False


def test_slice_cuts_boilerplate(tmp_path):
    _, store = fresh(tmp_path)
    boiler = "documentatia standard minfin " * 50
    tech = "CERINTE TEHNICE tabel detaliat rezolutie 8MP"
    text = boiler + tech
    out, meta = extract_technical_section(text, store)
    assert "CERINTE TEHNICE" in out
    assert "documentatia standard" not in out.lower()
    assert meta["reason"] == "marker"


def test_slice_fallback_tail(tmp_path):
    _, store = fresh(tmp_path)
    store.set("extract.fallback_tail_chars", 50)
    text = "x" * 500
    out, meta = extract_technical_section(text, store)
    assert meta["reason"] == "fallback_tail"
    assert len(out) == 50


def test_dedupe_prefers_pdf(tmp_path):
    docs = [
        {"title": "ds_echip.semnat.pdf", "format": "pdf", "type": "biddingDocuments"},
        {"title": "ds_echip.docx", "format": "docx", "type": "biddingDocuments"},
    ]
    out = dedupe_documents(docs)
    assert len(out) == 1
    assert out[0]["format"] == "pdf"


def test_select_skips_duae_and_doc(tmp_path):
    _, store = fresh(tmp_path)
    tender = {"documents": [
        {"title": "ds_echip.pdf", "format": "pdf", "type": "biddingDocuments"},
        {"title": "duae_ro.pdf", "format": "pdf", "type": "biddingDocuments"},
        {"title": "old.doc", "format": "doc", "type": "biddingDocuments"},
    ]}
    out = select_documents(tender, store)
    titles = [d["title"] for d in out]
    assert "ds_echip.pdf" in titles
    assert "duae_ro.pdf" not in titles
    assert "old.doc" not in titles


def _seed_tender(conn, docs):
    now = time.time()
    nj = json.dumps({"ocid": "x", "title": "t", "documents": docs}, ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        ("t", "x", "h", nj, "triaged", now, now))
    conn.commit()
    return cur.lastrowid


def test_extract_stage_stores_fields(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    tid = _seed_tender(conn, [{"title": "ds.pdf", "format": "pdf",
                               "type": "biddingDocuments", "url": "http://x/ds"}])

    monkeypatch.setattr(documents, "get_document_text",
                        lambda d, gw, cfg: {"text": "cerinte tehnice: camera 8MP", "method": "text",
                                            "cost": 0, "tokens": 0})

    class JSONProvider:
        name = "stub"
        available = True

        def generate(self, model, system, messages, max_tokens):
            payload = json.dumps({"obiect": "Camere", "echipamente":
                                  [{"denumire": "camera", "model": "X", "cantitate": 5}],
                                  "cerinte_tehnice": ["8MP"]}, ensure_ascii=False)
            return {"text": payload, "input_tokens": 100, "output_tokens": 50}

    import workflows.extract as ext
    monkeypatch.setattr(ext, "get_document_text", documents.get_document_text)
    from engine.llm import LLMGateway
    monkeypatch.setattr(ext, "LLMGateway",
                        lambda store, conn: LLMGateway(store, conn, provider=JSONProvider()))

    r = run_pipeline("pipeline.tender_extract", store, conn,
                     initial_payload={"tender": json.loads(
                         conn.execute("SELECT normalized_json FROM tenders WHERE id=?", (tid,)).fetchone()[0]),
                         "tender_id": tid}, tender_id=tid)
    assert r["status"] == "done"
    row = conn.execute("SELECT fields_json FROM extractions WHERE tender_id=?", (tid,)).fetchone()
    fields = json.loads(row["fields_json"])
    assert fields["obiect"] == "Camere"
    assert len(fields["echipamente"]) == 1


def test_extract_no_documents(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    tid = _seed_tender(conn, [])
    r = run_pipeline("pipeline.tender_extract", store, conn,
                     initial_payload={"tender": {"documents": []}, "tender_id": tid},
                     tender_id=tid)
    assert r["status"] == "done"
    row = conn.execute("SELECT method FROM extractions WHERE tender_id=?", (tid,)).fetchone()
    assert row["method"] == "metadata"


if __name__ == "__main__":
    import tempfile

    class MP:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)

    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as d:
                argn = fn.__code__.co_varnames[:fn.__code__.co_argcount]
                args = [Path(d) if a == "tmp_path" else MP() for a in argn]
                try:
                    fn(*args)
                    print(f"PASS {name}")
                except Exception as exc:
                    print(f"FAIL {name}: {exc}")
                    raise
    print("all tests passed")
