from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import db, documents
from engine.config_store import ConfigStore
from engine.llm import LLMGateway, StubProvider


def fresh(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    store = ConfigStore(conn)
    store.reload()
    store.set("documents.cache_dir", str(tmp_path / "docs"))
    store.set("documents.vision_enabled", True)
    store.set("documents.scanned_threshold", 100)
    store.set("llm.provider", "stub")
    return conn, store


def make_text_pdf(path, text):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in text.split("\n"):
        page.insert_text((72, y), line)
        y += 14
    doc.save(str(path))
    doc.close()


def make_blank_pdf(path):
    import fitz
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()


def make_docx(path, text):
    import docx
    d = docx.Document()
    d.add_paragraph(text)
    d.save(str(path))


def test_extract_pdf_text(tmp_path):
    pdf = tmp_path / "a.pdf"
    make_text_pdf(pdf, "Caiet de sarcini analizor de spectru")
    text, pages = documents.extract_pdf_text(str(pdf))
    assert "analizor" in text
    assert pages == 1


def test_extract_docx_text(tmp_path):
    d = tmp_path / "a.docx"
    make_docx(d, "Documentatie standard achizitie")
    text, _ = documents.extract_docx_text(str(d))
    assert "achizitie" in text


def test_is_scanned():
    assert documents.is_scanned("", 1) is True
    assert documents.is_scanned("x" * 500, 1) is False


def test_get_document_text_pdf(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    pdf = tmp_path / "b.pdf"
    make_text_pdf(pdf, "\n".join(f"cerinte tehnice linia {i}" for i in range(20)))
    monkeypatch.setattr(documents, "fetch_document", lambda url, cache_dir, timeout=60: str(pdf))
    gw = LLMGateway(store, conn, provider=StubProvider())
    r = documents.get_document_text({"url": "http://x/d", "format": "pdf"}, gw, store)
    assert r["method"] == "text"
    assert "cerinte" in r["text"]


def test_get_document_text_scanned_uses_vision(tmp_path, monkeypatch):
    conn, store = fresh(tmp_path)
    pdf = tmp_path / "scan.pdf"
    make_blank_pdf(pdf)
    monkeypatch.setattr(documents, "fetch_document", lambda url, cache_dir, timeout=60: str(pdf))

    class FakeVision(StubProvider):
        def generate(self, model, system, messages, max_tokens):
            return {"text": "TEXT FROM VISION OCR " * 10,
                    "input_tokens": 800, "output_tokens": 200}

    gw = LLMGateway(store, conn, provider=FakeVision())
    r = documents.get_document_text({"url": "http://x/scan", "format": "pdf"}, gw, store)
    assert r["method"] == "vision"
    assert "VISION OCR" in r["text"]


def test_skip_doc_format(tmp_path):
    conn, store = fresh(tmp_path)
    store.set("documents.skip_formats", ["doc"])
    gw = LLMGateway(store, conn, provider=StubProvider())
    r = documents.get_document_text({"url": "http://x/d", "format": "doc"}, gw, store)
    assert r["method"] == "skipped"


def test_fetch_caches(tmp_path):
    import fitz  # noqa
    pdf = tmp_path / "c.pdf"
    make_text_pdf(pdf, "data")
    data = pdf.read_bytes()
    calls = {"n": 0}
    cache = tmp_path / "cache"

    import engine.documents as docmod
    real_urlopen = None

    class FakeResp:
        def __init__(self, d):
            self._d = d
        def read(self):
            return self._d
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=60):
        calls["n"] += 1
        return FakeResp(data)

    docmod.urllib.request.urlopen = fake_urlopen
    p1 = docmod.fetch_document("http://x/c", str(cache))
    p2 = docmod.fetch_document("http://x/c", str(cache))
    assert p1 == p2
    assert calls["n"] == 1


if __name__ == "__main__":
    import tempfile

    class MP:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)

    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as d:
                args = []
                argn = fn.__code__.co_varnames[:fn.__code__.co_argcount]
                for a in argn:
                    if a == "tmp_path":
                        args.append(Path(d))
                    elif a == "monkeypatch":
                        args.append(MP())
                try:
                    fn(*args)
                    print(f"PASS {name}")
                except Exception as exc:
                    print(f"FAIL {name}: {exc}")
                    raise
    print("all tests passed")
