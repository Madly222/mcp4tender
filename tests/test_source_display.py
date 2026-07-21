from web.user import cards


def test_source_label_uses_portal_name_for_genericweb():
    row = {"source": "genericweb", "external_id": "x"}
    assert cards.source_label(row, {"source_site": "achizitii.md"}) == "achizitii.md"
    assert cards.source_label(row, {}) == "web"


def test_source_label_keeps_mtender():
    assert cards.source_label({"source": "mtender", "external_id": "ocds-x"}, {}) == "mtender"


def test_tender_link_scraped_uses_item_url():
    row = {"source": "genericweb", "external_id": "x"}
    link = "https://achizitii.md/ro/tender/123"
    assert cards.tender_link(row, {"url": link}) == link
    assert cards.tender_link(row, {"url": "not-a-url"}) is None
    assert cards.tender_link(row, {}) is None


def test_tender_link_mtender_uses_portal_template():
    row = {"source": "mtender", "external_id": "ocds-b3wdp1-MD-123"}
    assert cards.tender_link(row, {}) == "https://mtender.gov.md/tenders/ocds-b3wdp1-MD-123"
    assert cards.tender_link(row, {}, "https://p/{ocid}") == "https://p/ocds-b3wdp1-MD-123"
