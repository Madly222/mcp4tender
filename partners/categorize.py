from __future__ import annotations

import re

_WS = re.compile(r"\s+")

TYPE_RULES = (
    ("Thermal Paste", ("thermal paste", "thermal grease", "termopasta", "термопаста"), "both"),
    ("UPS", ("|ups|", "uninterruptible", "neintrerupt", "ибп"), "both"),
    ("Power Station", ("power station", "portable power", "ecoflow"), "desc"),
    ("Network Switch", ("switch",), "both"),
    ("Router", ("router",), "both"),
    ("Access Point", ("access point", "range extender", "powerline", "poe"), "both"),
    ("Mesh Wi-Fi", ("mesh wi-fi", "mesh wifi", "mesh system"), "both"),
    ("Wi-Fi Adapter", ("wi-fi adapter", "wireless adapter", "wifi adapter"), "desc"),
    ("Network Adapter", ("media converter", "network adapter", "|adapters|"), "both"),
    ("IP Camera / Surveillance",
     ("ip camera", "surveillance", "nvr", "dvr", "cctv", "camera video"), "both"),
    ("Monitor", ("monitor",), "path"),
    ("Projector", ("projector", "proiector"), "both"),
    ("Notebook / Laptop", ("notebook", "laptop"), "path"),
    ("Desktop PC", ("desktop pc", "|desktop"), "path"),
    ("Server", ("server",), "path"),
    ("MFD / MFP", ("mfd", "mfp", "multifunction", "multifunctional"), "both"),
    ("Copier", ("copier", "copiator"), "both"),
    ("Printer", ("printer", "imprimanta"), "both"),
    ("Scanner", ("scanner", "scaner"), "both"),
    ("Smartphone", ("smartphone", "|smartphones|"), "path"),
    ("Tablet", ("tablet",), "path"),
    ("SSD", ("ssd",), "both"),
    ("HDD", ("hdd", "hard drive", "hard disk"), "both"),
    ("RAM", ("|ram|", "ddr2", "ddr3", "ddr4", "ddr5", "dimm", "memory module",
             "memorie", "оперативная"), "both"),
    ("CPU", ("|cpu|", "processor"), "both"),
    ("Motherboard", ("motherboard", "mainboard", "|mainboards|", "placa de baza"), "both"),
    ("GPU / Video Card", ("video card", "graphics card", "|vga|", "gpu"), "both"),
    ("Case Fan", ("case fan", "fan control"), "both"),
    ("CPU Cooler", ("cpu cooler", "liquid cooling", "|coolers|", "radiator"), "both"),
    ("PC Case", ("|case|", "atx case", "pc case", "carcasa"), "both"),
    ("PSU", ("power supply", "|psu|"), "both"),
    ("Keyboard", ("keyboard", "tastatura"), "both"),
    ("Mouse", ("mouse",), "both"),
    ("Headset / Headphones",
     ("headset", "headphones", "casti", "earphone", "earbud"), "both"),
    ("Speakers", ("speaker", "boxe"), "both"),
    ("Webcam", ("webcam",), "both"),
    ("Cable / Patch Cord", ("patch cord", "cable", "cablu", "|cables"), "both"),
    ("External Storage",
     ("external hdd", "external ssd", "usb flash", "flash drive", "memory card",
      "sd card", "external storage"), "both"),
    ("Toner / Cartridge", ("toner", "cartridge", "cartus", "|consumables|"), "both"),
    ("Photo / Video", ("|photo", "camera photo", "dslr", "mirrorless", "action camera"), "both"),
    ("Accessory", ("|accessories|", "|accessory|", "docking", "usb hub"), "both"),
)

_ACRONYMS = {"UPS", "PSU", "SSD", "HDD", "RAM", "CPU", "GPU", "MFD", "MFP", "TV", "PC"}


def _norm_desc(value):
    return " " + _WS.sub(" ", str(value or "").lower()) + " "


def _norm_path(value):
    if not value:
        return "||"
    segs = [_WS.sub(" ", s.strip().lower()) for s in str(value).split(" / ")]
    return "|" + "|".join(segs) + "|"


def _top_segment(path):
    if not path:
        return None
    seg = str(path).split(" / ")[0].strip()
    if not seg:
        return None
    if seg.upper() in _ACRONYMS or (seg.isupper() and len(seg) <= 4):
        return seg.upper()
    return seg.title()


def classify(description, category_path):
    desc = _norm_desc(description)
    path = _norm_path(category_path)
    both = desc + " " + path
    for ptype, keywords, where in TYPE_RULES:
        hay = desc if where == "desc" else path if where == "path" else both
        for kw in keywords:
            if kw in hay:
                return ptype, "rule"
    top = _top_segment(category_path)
    if top:
        return top, "path"
    return None, None


def reclassify_all(conn):
    rows = conn.execute("SELECT id, description, category_path FROM partner_offers").fetchall()
    typed = 0
    by_rule = 0
    for r in rows:
        ptype, source = classify(r["description"], r["category_path"])
        conn.execute("UPDATE partner_offers SET product_type=?, type_source=? WHERE id=?",
                     (ptype, source, r["id"]))
        if ptype:
            typed += 1
        if source == "rule":
            by_rule += 1
    conn.commit()
    return {"total": len(rows), "typed": typed, "by_rule": by_rule}
