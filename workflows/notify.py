from __future__ import annotations

import json
import mimetypes
import smtplib
import time
import uuid
from email.message import EmailMessage
from urllib import request as urlrequest

from engine.secrets import read_env

SMTP_PASSWORD_VAR = "TENDERENGINE_SMTP_PASSWORD"
TG_TOKEN_VAR = "TENDERENGINE_TG_TOKEN"


def smtp_password():
    import os
    return os.environ.get(SMTP_PASSWORD_VAR) or read_env().get(SMTP_PASSWORD_VAR) or ""


def tg_token():
    import os
    return os.environ.get(TG_TOKEN_VAR) or read_env().get(TG_TOKEN_VAR) or ""


def _load(conn, tender_id):
    row = conn.execute(
        "SELECT t.id, t.source, t.external_id, t.normalized_json, "
        "av.verdict av_verdict, av.score av_score, av.reason av_reason, "
        "e.fields_json ex_fields, s.items_json sp_items, s.total_cost, s.tender_value, "
        "s.currency sp_currency, s.margin "
        "FROM tenders t "
        "LEFT JOIN verdicts av ON av.tender_id=t.id AND av.stage_name='applicability' "
        "LEFT JOIN extractions e ON e.tender_id=t.id "
        "LEFT JOIN suppliers s ON s.tender_id=t.id "
        "WHERE t.id=?", (tender_id,)).fetchone()
    return row


def _nj(row):
    try:
        return json.loads(row["normalized_json"]) if row["normalized_json"] else {}
    except Exception:
        return {}


def _loose(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        out = json.loads(value)
        return out if isinstance(out, dict) else {"raw": out}
    except Exception:
        return {"raw": str(value)}


def _reason(row):
    r = _loose(row["av_reason"])
    return r if r else {}


def tender_link(store, row, nj):
    from web.render import source_url
    portal = (store.get("sources.mtender", {}) or {}).get("portal_url_template")
    return source_url(row["source"], row["external_id"], portal) or nj.get("url") or ""


def _fmt_value(nj):
    v = nj.get("value_amount")
    if not v:
        return ""
    return f"{v} {nj.get('value_currency') or ''}".strip()


def build_message(store, conn, tender_id):
    row = _load(conn, tender_id)
    if row is None:
        return None
    nj = _nj(row)
    title = nj.get("title") or "(untitled)"
    link = tender_link(store, row, nj)
    reason = _reason(row)
    ex = _loose(row["ex_fields"])

    lines = [f"TENDER: {title}"]
    if nj.get("buyer"):
        lines.append(f"Buyer: {nj['buyer']}")
    if _fmt_value(nj):
        lines.append(f"Value: {_fmt_value(nj)}")
    if nj.get("deadline"):
        lines.append(f"Deadline: {nj['deadline']}")
    if row["av_verdict"]:
        score = f" ({row['av_score']})" if row["av_score"] is not None else ""
        lines.append(f"Verdict: {row['av_verdict']}{score}")
    if link:
        lines.append(f"Link: {link}")
    text = "\n".join(lines)

    md = [f"# {title}", ""]
    facts = []
    for label, val in (("Buyer", nj.get("buyer")), ("Value", _fmt_value(nj)),
                       ("Published", nj.get("publication_date") or nj.get("date")),
                       ("Submission deadline", nj.get("deadline")),
                       ("Enquiry deadline", nj.get("enquiry_deadline")),
                       ("Source", link)):
        if val:
            facts.append(f"- **{label}:** {val}")
    md += facts + [""]
    cpv = nj.get("cpv") or []
    if cpv:
        md.append("## CPV")
        for c in cpv:
            if isinstance(c, dict):
                md.append(f"- {c.get('id') or ''} {c.get('description') or ''}".strip())
        md.append("")
    if row["av_verdict"]:
        md.append("## Can we execute it?")
        score = f" · readiness {row['av_score']}" if row["av_score"] is not None else ""
        md.append(f"**{row['av_verdict']}**{score}")
        if reason.get("reasoning"):
            md.append("")
            md.append(str(reason["reasoning"]))
        for label, key in (("What matches our profile", "matched"),
                           ("Gaps", "gaps"),
                           ("Required equipment", "required_equipment")):
            vals = reason.get(key) or []
            if vals:
                md.append("")
                md.append(f"### {label}")
                md += [f"- {v}" for v in vals]
        md.append("")
    if ex and set(ex) != {"raw"}:
        md.append("## What the tender requires (extracted)")
        for k, v in ex.items():
            if v in (None, "", [], {}):
                continue
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            md.append(f"- **{k}:** {v}")
        md.append("")
    if row["sp_items"]:
        md.append("## Costing against the catalog")
        total = row["total_cost"]
        cur = row["sp_currency"] or ""
        if total is not None:
            md.append(f"- **Our estimated cost:** {total:.2f} {cur}".rstrip())
        if row["tender_value"]:
            md.append(f"- **Tender value:** {row['tender_value']} {cur}".rstrip())
        if row["margin"] is not None:
            md.append(f"- **Margin:** {row['margin'] * 100:.1f}%")
        try:
            items = json.loads(row["sp_items"]) or []
        except Exception:
            items = []
        for it in items:
            if not isinstance(it, dict):
                continue
            req = it.get("requirement") or "?"
            if it.get("supplier"):
                md.append(f"- {req}: {it.get('model') or ''} from {it['supplier']} "
                          f"({it.get('unit_price')} {it.get('currency') or ''} × "
                          f"{it.get('quantity')})")
            else:
                md.append(f"- {req}: no catalog match")
        md.append("")
    docs = nj.get("documents") or []
    if docs:
        md.append("## Tender documents")
        for d in docs:
            if isinstance(d, dict) and d.get("url"):
                md.append(f"- [{d.get('title') or d['url']}]({d['url']})")
        md.append("")

    fname = f"tender-{row['id']}-analysis.md"
    return {"subject": f"Tender: {title}"[:180], "text": text,
            "filename": fname, "content": "\n".join(md).encode("utf-8")}


def email_config(store):
    return {"enabled": bool(store.get("notify.email.enabled", False)),
            "host": str(store.get("notify.email.host", "") or "").strip(),
            "port": int(store.get("notify.email.port", 587) or 587),
            "tls": bool(store.get("notify.email.tls", True)),
            "login": str(store.get("notify.email.login", "") or "").strip(),
            "sender": str(store.get("notify.email.from", "") or "").strip(),
            "to": [a.strip() for a in
                   str(store.get("notify.email.to", "") or "").split(",") if a.strip()]}


def telegram_config(store):
    return {"enabled": bool(store.get("notify.telegram.enabled", False)),
            "chat_id": str(store.get("notify.telegram.chat_id", "") or "").strip()}


def send_email(store, msg, password=None, smtp_cls=None):
    cfg = email_config(store)
    missing = [k for k in ("host", "sender") if not cfg[k]] + \
              ([] if cfg["to"] else ["to"])
    if missing:
        return f"skipped: fill in email {', '.join(missing)}"
    m = EmailMessage()
    m["Subject"] = msg["subject"]
    m["From"] = cfg["sender"]
    m["To"] = ", ".join(cfg["to"])
    m.set_content(msg["text"])
    ctype = mimetypes.guess_type(msg["filename"])[0] or "text/markdown"
    main, sub = ctype.split("/", 1)
    m.add_attachment(msg["content"], maintype=main, subtype=sub,
                     filename=msg["filename"])
    cls = smtp_cls or smtplib.SMTP
    password = password if password is not None else smtp_password()
    try:
        with cls(cfg["host"], cfg["port"], timeout=30) as s:
            if cfg["tls"]:
                s.starttls()
            if cfg["login"]:
                s.login(cfg["login"], password)
            s.send_message(m)
        return "sent"
    except Exception as exc:
        return f"error: {str(exc)[:200]}"


def _multipart(fields, filename, content):
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f'name="{name}"\r\n\r\n{value}\r\n').encode("utf-8")
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; "
             f'filename="{filename}"\r\nContent-Type: text/markdown\r\n\r\n'
             ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def _tg_post(url, data, content_type):
    req = urlrequest.Request(url, data=data,
                             headers={"Content-Type": content_type}, method="POST")
    with urlrequest.urlopen(req, timeout=30) as resp:
        return resp.read()


def send_telegram(store, msg, token=None, post=None):
    cfg = telegram_config(store)
    token = token if token is not None else tg_token()
    if not cfg["chat_id"] or not token:
        need = [n for n, v in (("chat id", cfg["chat_id"]), ("bot token", token)) if not v]
        return f"skipped: fill in telegram {', '.join(need)}"
    post = post or _tg_post
    base = f"https://api.telegram.org/bot{token}"
    try:
        payload = json.dumps({"chat_id": cfg["chat_id"], "text": msg["text"],
                              "disable_web_page_preview": True}).encode("utf-8")
        post(f"{base}/sendMessage", payload, "application/json")
        body, ctype = _multipart({"chat_id": cfg["chat_id"]},
                                 msg["filename"], msg["content"])
        post(f"{base}/sendDocument", body, ctype)
        return "sent"
    except Exception as exc:
        return f"error: {str(exc)[:200]}"


def channels_on(store):
    return {"email": email_config(store)["enabled"],
            "telegram": telegram_config(store)["enabled"]}


def notify_tender(store, conn, tender_id, emailer=None, telegrammer=None):
    on = channels_on(store)
    if not on["email"] and not on["telegram"]:
        return {"status": "off",
                "detail": "sending is turned off — enable email or Telegram in "
                          "Company settings → Sending results"}
    msg = build_message(store, conn, tender_id)
    if msg is None:
        return {"status": "error", "detail": "no such tender"}
    out = {"status": "ok", "detail": ""}
    parts = []
    if on["email"]:
        res = (emailer or send_email)(store, msg)
        parts.append(f"email {res}")
        if not res.startswith("sent"):
            out["status"] = "partial"
    if on["telegram"]:
        res = (telegrammer or send_telegram)(store, msg)
        parts.append(f"telegram {res}")
        if not res.startswith("sent"):
            out["status"] = "partial"
    if not any(p.endswith("sent") or " sent" in p for p in parts):
        out["status"] = "failed"
    out["detail"] = "; ".join(parts)
    return out
