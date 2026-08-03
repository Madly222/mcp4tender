from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workflows.collectors.mtender import normalize_record

AUCTION = {"records": [
    {"compiledRelease": {"date": "2026-06-20T00:00:00Z", "tender": {
        "title": "servicii", "status": "planning"}}},
    {"compiledRelease": {"date": "2026-06-25T00:00:00Z", "tender": {
        "status": "active", "tenderPeriod": {"startDate": "2026-07-01T00:00:00Z"}}}},
    {"compiledRelease": {"date": "2026-07-27T13:00:00Z", "tender": {
        "status": "active", "statusDetails": "tendering",
        "tenderPeriod": {"startDate": "2026-08-03T06:00:00Z",
                         "endDate": "2026-08-06T14:00:00Z"},
        "enquiryPeriod": {"startDate": "2026-07-27T12:54:56Z",
                          "endDate": "2026-08-03T06:00:00Z"},
        "auctionPeriod": {"startDate": "2026-08-07T10:00:00Z"}}}}]}


def test_auction_deadline_is_offer_submission_not_the_auction_end():
    nj = normalize_record(AUCTION, "ocds-b3wdp1-MD-1785155348345")
    assert nj["deadline"] == "2026-08-03T06:00:00Z"
    assert nj["deadline"] != "2026-08-06T14:00:00Z"


def test_planning_tenderperiod_startdate_never_becomes_the_deadline():
    nj = normalize_record(AUCTION, "ocds-x")
    assert nj["deadline"] != "2026-07-01T00:00:00Z"


NO_AUCTION = {"records": [
    {"compiledRelease": {"date": "2026-07-01T00:00:00Z", "tender": {
        "status": "active", "statusDetails": "tendering",
        "tenderPeriod": {"startDate": "2026-07-01T00:00:00Z",
                         "endDate": "2026-08-15T10:00:00Z"},
        "enquiryPeriod": {"endDate": "2026-08-10T10:00:00Z"}}}}]}


def test_plain_procedure_still_uses_tenderperiod_enddate():
    nj = normalize_record(NO_AUCTION, "ocds-y")
    assert nj["deadline"] == "2026-08-15T10:00:00Z"


def test_auction_without_enquiry_falls_back_to_tenderperiod_start():
    pkg = {"records": [{"compiledRelease": {"date": "2026-07-27T00:00:00Z", "tender": {
        "tenderPeriod": {"startDate": "2026-08-03T06:00:00Z",
                         "endDate": "2026-08-06T14:00:00Z"},
        "auctionPeriod": {"startDate": "2026-08-07T10:00:00Z"}}}}]}
    nj = normalize_record(pkg, "ocds-z")
    assert nj["deadline"] == "2026-08-03T06:00:00Z"
