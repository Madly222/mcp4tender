from __future__ import annotations

import datetime as dt
import re

from engine.collectors import (CollectContext, CollectedItem, CollectResult,
                               Collector, register_collector)
from engine.http import get_json
from engine.lifecycle import collect_ceiling, item_archive_reason

_OCID_BASE_RE = re.compile(r"^(ocds-[a-z0-9]+-[A-Z]{2}-\d+)")


def base_ocid(ocid):
    m = _OCID_BASE_RE.match(str(ocid or ""))
    return m.group(1) if m else str(ocid or "")


def _initial_cursor(backfill_days):
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=int(backfill_days))
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def _all_compiled(record_package):
    rp = record_package
    if isinstance(rp, dict) and "data" in rp and isinstance(rp["data"], dict):
        rp = rp["data"]
    records = rp.get("records") if isinstance(rp, dict) else None
    if not records:
        if isinstance(rp, dict) and "compiledRelease" in rp:
            return [rp["compiledRelease"]]
        return [rp] if isinstance(rp, dict) else []
    out = []
    for r in records:
        if isinstance(r, dict) and isinstance(r.get("compiledRelease"), dict):
            out.append(r["compiledRelease"])
    return out


def _first(crs, getter):
    for cr in crs:
        try:
            v = getter(cr)
        except (AttributeError, TypeError):
            v = None
        if v not in (None, "", [], {}):
            return v
    return None


def _buyer_name(crs):
    def from_cr(cr):
        buyer = cr.get("buyer") or {}
        if buyer.get("name"):
            return buyer["name"]
        for party in cr.get("parties") or []:
            roles = party.get("roles") or []
            if "buyer" in roles or "procuringEntity" in roles:
                return party.get("name")
        return ((cr.get("tender") or {}).get("procuringEntity") or {}).get("name")
    return _first(crs, from_cr)


def _cpv(crs):
    out = []
    seen = set()
    for cr in crs:
        tender = cr.get("tender") or {}
        classifications = [tender.get("classification") or {}]
        for item in tender.get("items") or []:
            classifications.append(item.get("classification") or {})
        for cl in classifications:
            cid = cl.get("id")
            if cid and cid not in seen:
                seen.add(cid)
                out.append({"id": cid, "scheme": cl.get("scheme"),
                            "description": cl.get("description")})
    return out


def _guess_format(title, explicit):
    if explicit:
        return explicit
    if not title:
        return None
    low = title.lower()
    for ext in (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".zip", ".rar",
                ".png", ".jpg", ".jpeg", ".odt"):
        if low.endswith(ext):
            return ext.lstrip(".")
    return None


_DOC_TS_RE = re.compile(r"-(\d{10,})(?:[/?#].*)?$")


def _doc_title_key(title, url):
    if title and str(title).strip():
        return str(title).strip().lower()
    if url:
        tail = str(url).rstrip("/").rsplit("/", 1)[-1]
        return _DOC_TS_RE.sub("", tail).strip().lower() or str(url).lower()
    return ""


def _doc_version(doc):
    url = doc.get("url") or ""
    m = _DOC_TS_RE.search(str(url))
    if m:
        return (1, int(m.group(1)))
    dp = doc.get("datePublished") or ""
    return (0, str(dp))


def dedupe_documents(docs):
    best = {}
    order = []
    for d in docs:
        key = _doc_title_key(d.get("title"), d.get("url"))
        if key not in best:
            best[key] = d
            order.append(key)
        else:
            if _doc_version(d) >= _doc_version(best[key]):
                best[key] = d
    return [best[k] for k in order]


def _documents(crs):
    docs = []
    seen = set()
    for cr in crs:
        tender = cr.get("tender") or {}
        groups = [tender.get("documents") or [], (cr.get("planning") or {}).get("documents") or []]
        for aw in cr.get("awards") or []:
            groups.append(aw.get("documents") or [])
        for ct in cr.get("contracts") or []:
            groups.append(ct.get("documents") or [])
        for group in groups:
            for d in group:
                key = d.get("url") or d.get("id")
                if key and key not in seen:
                    seen.add(key)
                    docs.append({"title": d.get("title"), "url": d.get("url"),
                                 "type": d.get("documentType"),
                                 "format": _guess_format(d.get("title"), d.get("format")),
                                 "datePublished": d.get("datePublished")})
    return dedupe_documents(docs)


def normalize_record(record_package, ocid):
    crs = _all_compiled(record_package)
    tg = lambda key: _first(crs, lambda cr: (cr.get("tender") or {}).get(key))
    value = _first(crs, lambda cr: (cr.get("tender") or {}).get("value")) or {}
    return {
        "ocid": ocid,
        "title": tg("title"),
        "description": tg("description"),
        "status": tg("status"),
        "status_details": tg("statusDetails"),
        "buyer": _buyer_name(crs),
        "value_amount": value.get("amount"),
        "value_currency": value.get("currency"),
        "procurement_method": tg("procurementMethod"),
        "main_category": tg("mainProcurementCategory"),
        "cpv": _cpv(crs),
        "deadline": _first(crs, lambda cr: ((cr.get("tender") or {}).get("tenderPeriod") or {}).get("endDate")),
        "enquiry_deadline": _first(crs, lambda cr: ((cr.get("tender") or {}).get("enquiryPeriod") or {}).get("endDate")),
        "publication_date": _first(crs, lambda cr: ((cr.get("tender") or {}).get("datePublished")) or cr.get("date")),
        "documents": _documents(crs),
        "date": _first(crs, lambda cr: cr.get("date")),
    }


@register_collector("mtender")
class MTenderCollector(Collector):
    def normalize(self, raw, external_id):
        return normalize_record(raw, external_id)

    def collect(self, ctx: CollectContext) -> CollectResult:
        sc = ctx.source_config
        list_url = sc.get("list_url", "https://public.mtender.gov.md/tenders")
        record_tpl = sc.get("record_url_template",
                            "https://public.mtender.gov.md/tenders/{ocid}")
        timeout = int(sc.get("timeout", 30))
        page_limit = int(sc.get("page_limit", 5))
        max_records = int(sc.get("max_records_per_run", 200))
        backfill_days = int(sc.get("backfill_days", 30))
        ceiling = collect_ceiling(ctx.config)

        cursor = ctx.cursor or _initial_cursor(backfill_days)
        items = []
        seen = set()
        pages = 0
        skipped_dead = 0

        while pages < page_limit and len(items) < max_records:
            pages += 1
            url = list_url + ("?offset=" + cursor if cursor else "")
            resp = get_json(url, timeout=timeout)
            data = resp.get("data") if isinstance(resp, dict) else None
            if not data:
                break
            next_cursor = resp.get("offset") if isinstance(resp, dict) else None

            for entry in data:
                ocid = entry.get("ocid")
                base = base_ocid(ocid)
                if not base or base in seen:
                    continue
                seen.add(base)
                try:
                    record = get_json(record_tpl.format(ocid=ocid), timeout=timeout)
                    normalized = normalize_record(record, base)
                    if ceiling and item_archive_reason(normalized, archive_days=ceiling):
                        skipped_dead += 1
                        continue
                    items.append(CollectedItem(external_id=base, raw=record,
                                              normalized=normalized))
                except Exception:
                    continue
                if len(items) >= max_records:
                    break

            if next_cursor and next_cursor != cursor:
                cursor = next_cursor
            else:
                last = data[-1].get("date")
                if not last or last == cursor:
                    break
                cursor = last

        return CollectResult(items=items, cursor=cursor, fetched=len(items),
                             too_old=skipped_dead)
