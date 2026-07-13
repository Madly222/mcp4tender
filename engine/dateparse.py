from __future__ import annotations

import datetime as dt
import re

DEFAULT_TZ = "Europe/Chisinau"

_MONTHS = {}


def _add_months(names, num):
    for n in names:
        _MONTHS[n] = num


_add_months(["ianuarie", "ian", "januarie"], 1)
_add_months(["februarie", "feb", "fevruarie"], 2)
_add_months(["martie", "mar"], 3)
_add_months(["aprilie", "apr"], 4)
_add_months(["mai"], 5)
_add_months(["iunie", "iun"], 6)
_add_months(["iulie", "iul"], 7)
_add_months(["august", "aug"], 8)
_add_months(["septembrie", "sept", "sep"], 9)
_add_months(["octombrie", "oct"], 10)
_add_months(["noiembrie", "noi", "nov"], 11)
_add_months(["decembrie", "dec"], 12)

_add_months(["january", "jan"], 1)
_add_months(["february"], 2)
_add_months(["march"], 3)
_add_months(["april"], 4)
_add_months(["june", "jun"], 6)
_add_months(["july", "jul"], 7)
_add_months(["october"], 10)
_add_months(["november"], 11)
_add_months(["december"], 12)
_add_months(["may"], 5)

_add_months(["\u044f\u043d\u0432\u0430\u0440\u044f", "\u044f\u043d\u0432\u0430\u0440\u044c", "\u044f\u043d\u0432"], 1)
_add_months(["\u0444\u0435\u0432\u0440\u0430\u043b\u044f", "\u0444\u0435\u0432\u0440\u0430\u043b\u044c", "\u0444\u0435\u0432"], 2)
_add_months(["\u043c\u0430\u0440\u0442\u0430", "\u043c\u0430\u0440\u0442"], 3)
_add_months(["\u0430\u043f\u0440\u0435\u043b\u044f", "\u0430\u043f\u0440\u0435\u043b\u044c", "\u0430\u043f\u0440"], 4)
_add_months(["\u043c\u0430\u044f", "\u043c\u0430\u0439"], 5)
_add_months(["\u0438\u044e\u043d\u044f", "\u0438\u044e\u043d\u044c", "\u0438\u044e\u043d"], 6)
_add_months(["\u0438\u044e\u043b\u044f", "\u0438\u044e\u043b\u044c", "\u0438\u044e\u043b"], 7)
_add_months(["\u0430\u0432\u0433\u0443\u0441\u0442\u0430", "\u0430\u0432\u0433\u0443\u0441\u0442", "\u0430\u0432\u0433"], 8)
_add_months(["\u0441\u0435\u043d\u0442\u044f\u0431\u0440\u044f", "\u0441\u0435\u043d\u0442\u044f\u0431\u0440\u044c", "\u0441\u0435\u043d"], 9)
_add_months(["\u043e\u043a\u0442\u044f\u0431\u0440\u044f", "\u043e\u043a\u0442\u044f\u0431\u0440\u044c", "\u043e\u043a\u0442"], 10)
_add_months(["\u043d\u043e\u044f\u0431\u0440\u044f", "\u043d\u043e\u044f\u0431\u0440\u044c", "\u043d\u043e\u044f"], 11)
_add_months(["\u0434\u0435\u043a\u0430\u0431\u0440\u044f", "\u0434\u0435\u043a\u0430\u0431\u0440\u044c", "\u0434\u0435\u043a"], 12)

_DIACRITICS = str.maketrans({
    "\u0103": "a", "\u00e2": "a", "\u00ee": "i", "\u0219": "s", "\u021b": "t",
    "\u015f": "s", "\u0163": "t", "\u00e4": "a", "\u00e9": "e", "\u00e8": "e",
})

_ISO_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}))?\s*(Z|[+-]\d{2}:?\d{2})?)?")

_NUM_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_YMD_RE = re.compile(r"\b(\d{4})[./](\d{1,2})[./](\d{1,2})\b")

_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_TXT_DMY_RE = re.compile(r"\b(\d{1,2})\s+(?:de\s+)?(" + _MONTH_ALT + r")\.?\s+(?:de\s+)?(\d{4})",
                         re.I)
_TXT_MDY_RE = re.compile(r"\b(" + _MONTH_ALT + r")\.?\s+(\d{1,2})\s*,?\s+(\d{4})", re.I)

_TIME_RE = re.compile(r"(?:\bora\s*|,\s*|\s)(\d{1,2})[:.](\d{2})(?!\d)")


class DateInfo:
    def __init__(self, date=None, time=None, kind=None):
        self.date = date
        self.time = time
        self.kind = kind

    def __bool__(self):
        return self.date is not None

    def __repr__(self):
        return "DateInfo(%r, %r, %r)" % (self.date, self.time, self.kind)

    def iso(self):
        return self.date.isoformat() if self.date else None


def _tz(name=DEFAULT_TZ):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


def _safe_date(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def _fmt_time(h, mi):
    return "%02d:%02d" % (int(h), int(mi))


def _find_time(text):
    m = _TIME_RE.search(text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return _fmt_time(h, mi)
    return None


def _parse_iso(s, tzname):
    m = _ISO_RE.search(s)
    if not m:
        return None
    date = _safe_date(m.group(1), m.group(2), m.group(3))
    if date is None:
        return None
    if not m.group(4):
        return DateInfo(date, None, "iso-date")
    hh, mi = int(m.group(4)), int(m.group(5))
    ss = int(m.group(6) or 0)
    offs = m.group(7)
    naive = dt.datetime(date.year, date.month, date.day, hh, mi, min(ss, 59))
    if not offs:
        return DateInfo(naive.date(), _fmt_time(naive.hour, naive.minute), "iso-naive")
    if offs == "Z":
        tzinfo = dt.timezone.utc
    else:
        sign = 1 if offs[0] == "+" else -1
        body = offs[1:].replace(":", "")
        tzinfo = dt.timezone(sign * dt.timedelta(hours=int(body[:2]), minutes=int(body[2:4])))
    aware = naive.replace(tzinfo=tzinfo)
    target = _tz(tzname)
    local = aware.astimezone(target) if target else aware
    return DateInfo(local.date(), _fmt_time(local.hour, local.minute), "iso-tz")


def _parse_numeric(s, dayfirst):
    m = _YMD_RE.search(s)
    if m:
        date = _safe_date(m.group(1), m.group(2), m.group(3))
        if date:
            return DateInfo(date, _find_time(s[m.end():]), "ymd")
    m = _NUM_RE.search(s)
    if not m:
        return None
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if a > 12 and b <= 12:
        d, mo = a, b
    elif b > 12 and a <= 12:
        d, mo = b, a
    else:
        d, mo = (a, b) if dayfirst else (b, a)
    date = _safe_date(y, mo, d)
    if date is None:
        return None
    return DateInfo(date, _find_time(s[m.end():]), "numeric")


def _parse_textual(s):
    m = _TXT_DMY_RE.search(s)
    if m:
        mo = _MONTHS.get(m.group(2).lower())
        date = _safe_date(m.group(3), mo, m.group(1)) if mo else None
        if date:
            return DateInfo(date, _find_time(s[m.end():]), "text-dmy")
    m = _TXT_MDY_RE.search(s)
    if m:
        mo = _MONTHS.get(m.group(1).lower())
        date = _safe_date(m.group(3), mo, m.group(2)) if mo else None
        if date:
            return DateInfo(date, _find_time(s[m.end():]), "text-mdy")
    return None


def parse(value, tzname=DEFAULT_TZ, dayfirst=True):
    if value is None:
        return DateInfo()
    if isinstance(value, dt.datetime):
        return DateInfo(value.date(), _fmt_time(value.hour, value.minute), "datetime")
    if isinstance(value, dt.date):
        return DateInfo(value, None, "date")
    s = str(value).strip()
    if not s:
        return DateInfo()
    low = s.lower().translate(_DIACRITICS)
    for fn in (lambda: _parse_iso(s, tzname),
               lambda: _parse_textual(low),
               lambda: _parse_numeric(low, dayfirst)):
        got = fn()
        if got:
            return got
    return DateInfo()


def parse_date(value, tzname=DEFAULT_TZ, dayfirst=True):
    return parse(value, tzname, dayfirst).date


def to_iso(value, tzname=DEFAULT_TZ, dayfirst=True):
    return parse(value, tzname, dayfirst).iso()


def to_iso_dt(value, tzname=DEFAULT_TZ, dayfirst=True):
    info = parse(value, tzname, dayfirst)
    if not info:
        return None
    if info.time:
        return info.date.isoformat() + "T" + info.time + ":00"
    return info.date.isoformat()


def normalize_field(value, tzname=DEFAULT_TZ, dayfirst=True):
    iso = to_iso_dt(value, tzname, dayfirst)
    if iso:
        return iso
    s = str(value).strip() if value else ""
    return s or None


def humanize(value, tzname=DEFAULT_TZ, dayfirst=True, with_time=True):
    info = parse(value, tzname, dayfirst)
    if not info:
        return None
    out = info.date.strftime("%d.%m.%Y")
    if with_time and info.time:
        out += ", " + info.time
    return out
