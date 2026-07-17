from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import time
from web.user import lifecycle
from workflows.collectors.mtender import _awarded, _all_compiled, _latest, normalize_record
REAL = {"records": [
    {"compiledRelease": {"date": "2026-06-30T06:02:57Z", "tender": {
        "title": "servicii internet", "status": "active", "statusDetails": "negotiation",
        "contractPeriod": {"startDate": "2026-04-30T06:02:01Z"},
        "value": {"amount": 583.33, "currency": "MDL"}}}},
    {"compiledRelease": {"date": "2026-06-30T06:02:57Z", "tender": {
        "status": "complete", "statusDetails": "empty",
        "tenderPeriod": {"startDate": "2026-04-01T00:00:00Z"}}}},
    {"compiledRelease": {"date": "2026-06-30T06:02:59Z", "tender": {
        "status": "active", "statusDetails": "awarding",
        "awardPeriod": {"startDate": "2026-06-30T06:02:58Z"}},
        "awards": [{"status": "pending", "statusDetails": "active",
                    "date": "2026-06-30T06:02:59Z"}]}}]}
CLOSED = {"complete", "cancelled", "unsuccessful", "withdrawn"}
def test_stage_comes_from_the_freshest_release_not_the_first():
    """records[0] says negotiation, records[2] is 2 seconds newer and says awarding.
    _first() answered negotiation, which is how a tender past bidding looked alive."""
    nj = normalize_record(REAL, "ocds-b3wdp1-MD-1782799255436")
    assert nj["status_details"] == "awarding"
    assert nj["status"] == "active"
def test_awarded_is_detected_from_the_package_structure():
    assert _awarded(_all_compiled(REAL)) is True
def test_awarded_needs_a_real_award():
    assert _awarded([{"tender": {"status": "active"}}]) is False
    assert _awarded([{"awards": []}]) is False
    assert _awarded([{"awards": [{}]}]) is False
    assert _awarded([{"contracts": [{"id": "c1"}]}]) is True
def test_the_real_tender_is_closed():
    nj = normalize_record(REAL, "ocds-b3wdp1-MD-1782799255436")
    assert nj["deadline"] is None, "MTender never sent a submission deadline for this one"
    assert lifecycle.state_of(nj, nj.get("deadline"), CLOSED) == lifecycle.CLOSED
def test_awarded_beats_a_future_deadline_and_an_active_status():
    nj = {"status": "active", "status_details": "awarding", "awarded": True}
    future = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + 30*86400))
    assert lifecycle.state_of(nj, future, CLOSED) == lifecycle.CLOSED
def test_a_genuinely_open_tender_survives_all_of_this():
    pkg = {"records": [{"compiledRelease": {"date": "2026-07-01T10:00:00Z", "tender": {
        "title": "Echipament de retea", "status": "active", "statusDetails": "tendering",
        "tenderPeriod": {"endDate": "2026-12-01T16:00:00Z"}}}}]}
    nj = normalize_record(pkg, "ocds-x")
    assert nj["awarded"] is False and nj["status_details"] == "tendering"
    assert lifecycle.state_of(nj, nj["deadline"], CLOSED) == lifecycle.OPEN
def test_latest_ignores_releases_without_the_field():
    crs = [{"date": "2026-01-01", "tender": {"statusDetails": "tendering"}},
           {"date": "2026-06-01", "tender": {}}]
    assert _latest(crs, lambda cr: (cr.get("tender") or {}).get("statusDetails")) == "tendering"
def test_latest_survives_missing_dates():
    crs = [{"tender": {"statusDetails": "a"}}, {"tender": {"statusDetails": "b"}}]
    assert _latest(crs, lambda cr: (cr.get("tender") or {}).get("statusDetails")) in ("a", "b")
def test_title_still_comes_from_whichever_release_has_one():
    nj = normalize_record(REAL, "ocds-1")
    assert nj["title"] == "servicii internet", "_latest must not have broken _first fields"
    assert nj["value_amount"] == 583.33
