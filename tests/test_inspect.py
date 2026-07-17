from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as appmod
from engine import db
from engine.config_store import ConfigStore
OCID = "OCDS-B3WDP1-MD-1782799255436"
RAW = {"records": [{"compiledRelease": {
    "ocid": OCID.lower(), "date": "2026-06-01T10:00:00Z",
    "parties": [{"name": "PRIMARIA SATULUI USTIA", "roles": ["buyer"]}],
    "buyer": {"name": "PRIMARIA SATULUI USTIA"},
    "tender": {"title": "servicii internet", "status": "active",
               "statusDetails": "Calificarea ofertanților",
               "tenderPeriod": {"endDate": "2026-06-08T10:00:00Z"},
               "value": {"amount": 583.33, "currency": "MDL"}}}}]}
class _Args:
    def __init__(self, external_id, find=None):
        self.external_id = external_id
        self.find = find
def _fresh(tmp_path, stale=True):
    p = str(tmp_path/"i.db"); conn = db.connect(p); db.init_schema(conn)
    s = ConfigStore(conn); s.reload(); s.seed_defaults("config/defaults")
    nj = {"title": "servicii internet", "buyer": "PRIMARIA SATULUI USTIA", "status": "active",
          "value_amount": 583.33, "value_currency": "MDL", "cpv": [], "documents": []}
    if not stale:
        nj["status_details"] = "Calificarea ofertanților"
        nj["deadline"] = "2026-06-08T10:00:00Z"
    now = time.time()
    conn.execute("INSERT INTO tenders(source,external_id,content_hash,normalized_json,status,origin,created_at,updated_at) VALUES('mtender',?,'h',?,'analyzed','incremental',?,?)",
                 (OCID, json.dumps(nj), now, now))
    conn.execute("INSERT INTO raw_documents(source,external_id,content_hash,fetched_at,payload_json) VALUES('mtender',?,'h',?,?)",
                 (OCID, now, json.dumps(RAW)))
    conn.commit()
    return p, conn, s
def test_inspect_reports_a_missing_deadline_as_the_reason(tmp_path, capsys):
    p, conn, s = _fresh(tmp_path, stale=True)
    assert appmod.cmd_inspect(conn, s, _Args("1782799255436")) == 0
    out = capsys.readouterr().out
    assert "UNKNOWN" in out
    assert "NO submission deadline stored" in out
    assert "status_details       None" in out
def test_inspect_shows_what_the_source_really_sent(tmp_path, capsys):
    p, conn, s = _fresh(tmp_path, stale=True)
    appmod.cmd_inspect(conn, s, _Args(OCID))
    out = capsys.readouterr().out
    assert "tender.statusDetails" in out and "Calificarea ofertan" in out
    assert "tender.tenderPeriod.endDate" in out and "2026-06-08" in out
def test_inspect_says_renormalize_would_fix_it(tmp_path, capsys):
    p, conn, s = _fresh(tmp_path, stale=True)
    appmod.cmd_inspect(conn, s, _Args(OCID))
    out = capsys.readouterr().out
    assert "would `app.py renormalize mtender` change anything?" in out
    assert "status_details" in out.split("renormalize")[-1]
    assert "deadline" in out.split("renormalize")[-1]
def test_inspect_is_quiet_when_data_is_current(tmp_path, capsys):
    p, conn, s = _fresh(tmp_path, stale=False)
    appmod.cmd_inspect(conn, s, _Args(OCID))
    out = capsys.readouterr().out
    assert "CLOSED" in out, "a past submission deadline means we cannot bid"
def test_find_locates_a_word_from_the_portal(tmp_path, capsys):
    p, conn, s = _fresh(tmp_path, stale=True)
    appmod.cmd_inspect(conn, s, _Args(OCID, find="calificar"))
    out = capsys.readouterr().out
    assert "records[0].compiledRelease.tender.statusDetails" in out
def test_unknown_id_is_reported_not_crashed(tmp_path, capsys):
    p, conn, s = _fresh(tmp_path)
    assert appmod.cmd_inspect(conn, s, _Args("nope")) == 1
    assert "no tender matching" in capsys.readouterr().out
def test_renormalize_actually_closes_this_tender(tmp_path):
    from engine import renormalize_source
    from web.user import cards, lifecycle
    p, conn, s = _fresh(tmp_path, stale=True)
    rows = conn.execute("SELECT * FROM tenders").fetchall()
    nj = cards.nj_of(rows[0])
    closed = lifecycle.closed_statuses(s)
    assert lifecycle.state_of(nj, nj.get("deadline"), closed) == lifecycle.UNKNOWN
    renormalize_source("mtender", s, conn)
    rows = conn.execute("SELECT * FROM tenders").fetchall()
    nj = cards.nj_of(rows[0])
    assert nj["status_details"] == "Calificarea ofertanților"
    assert nj["deadline"] == "2026-06-08T10:00:00Z"
    assert lifecycle.state_of(nj, nj.get("deadline"), closed) == lifecycle.CLOSED
    conn.close()
