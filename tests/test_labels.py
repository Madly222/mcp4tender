from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import accounts, db
from engine.config_store import ConfigStore
from fastapi.testclient import TestClient
from web.server import create_app
from web.user import dictforms
from web.user.forms import HANDLED
from web.user.labels import LABELS, humanize, label_of
from web.user.settings_meta import section_of
def _fresh(tmp_path, name):
    p = str(tmp_path/name); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    accounts.create(conn, "rl", "password1", company="SC Rapid Link SRL", role="user")
    conn.commit(); return p, conn
def _login(p):
    c = TestClient(create_app(p), follow_redirects=False)
    assert c.post("/login", data={"login": "rl", "password": "password1"}).status_code == 303
    return c
def test_every_generated_key_has_a_real_name(tmp_path):
    """Nothing the user can see should fall back to the humanizer."""
    p, conn = _fresh(tmp_path,"lb.db")
    s = ConfigStore(conn); s.reload()
    handled = {k for v in HANDLED.values() for k in v} | set(dictforms.SPECS)
    missing = sorted(k for k in s.all()
                     if section_of(k) and k not in handled and k not in LABELS)
    assert missing == [], f"no human name for: {missing}"
    conn.close()
def test_labels_are_keyed_by_the_whole_key_not_the_stem():
    """max_output_tokens lives under four prefixes and means something different in each."""
    same_stem = [k for k in LABELS if k.endswith(".max_output_tokens")]
    assert len(same_stem) >= 3
    assert len({LABELS[k] for k in same_stem}) == len(same_stem), "each must read differently"
def test_labels_read_like_english():
    for key, text in LABELS.items():
        assert "_" not in text, f"{key} still has a machine name: {text}"
        assert text[:1] == text[:1].upper(), key
        assert text == text.strip() and len(text) > 3, key
def test_humanize_is_only_a_fallback():
    assert humanize("something.brand_new_key") == "Brand new key"
    assert humanize("x.ocr_prompt") == "OCR prompt"
    assert humanize("x.some_url") == "Some URL"
    assert label_of("results.archive_after_days") == "Move to the archive after"
def test_the_page_shows_names_not_variables(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"lb2.db"); conn.close()
    h = _login(p).get("/app/settings/lists").text
    assert "Move to the archive after" in h and "Drop undecided tenders from the inbox after" in h
    assert "<label>archive_after_days</label>" not in h
    assert "results.archive_after_days" in h, "the engine name stays available, just quietly"
def test_the_saved_banner_names_the_setting(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"lb3.db"); conn.close()
    h = _login(p).get("/app/settings/lists?saved=results.new_days").text
    assert "Drop undecided tenders from the inbox after — the engine picks it up" in h
def test_dict_form_subfields_are_named_too(tmp_path, monkeypatch):
    monkeypatch.delenv("TENDERENGINE_WEB_TOKEN", raising=False)
    p, conn = _fresh(tmp_path,"lb4.db"); conn.close()
    h = _login(p).get("/app/settings/sources").text
    assert "<label>Max records per run</label>" in h or "Max records per run" in h
    assert '<span class="chip plain mono">max_records_per_run</span>' not in h
