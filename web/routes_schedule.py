from __future__ import annotations

import re

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from web import settings_ops
from web.render import _e, _layout

router = APIRouter()

_DAYS = settings_ops.DAYS
_KNOWN_SOURCES = settings_ops.KNOWN_SOURCES
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _collect_job(store):
    for j in store.get("schedule.jobs", []) or []:
        if isinstance(j, dict) and j.get("kind") == "collect":
            return j
    return {"kind": "collect", "sources": ["mtender", "genericweb"], "days": [],
            "at": ["06:00", "18:00"], "analyze": True, "enabled": False}


def _other_jobs(store):
    return [j for j in (store.get("schedule.jobs", []) or [])
            if not (isinstance(j, dict) and j.get("kind") == "collect")]


def _norm_day(d):
    names = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    if isinstance(d, bool):
        return None
    if isinstance(d, int):
        return d % 7
    return names.get(str(d).strip().lower()[:3])


def _parse_times(raw):
    out = []
    for part in re.split(r"[,\s]+", raw or ""):
        part = part.strip()
        if part and _TIME_RE.match(part):
            hh, mm = part.split(":")
            norm = "%02d:%s" % (int(hh), mm)
            if norm not in out:
                out.append(norm)
    return sorted(out)[:24]


@router.get("/schedule")
def schedule(request: Request, msg: str = "", err: str = ""):
    store = request.state.store
    ro = request.state.readonly
    job = _collect_job(store)
    tz = store.get("schedule.timezone", "") or ""
    days = {_norm_day(d) for d in (job.get("days") or [])}
    times = ", ".join(job.get("at") or [])
    srcs = set(job.get("sources") or [])
    analyze = bool(job.get("analyze", True))
    enabled = bool(job.get("enabled", False))

    banner = ""
    if msg:
        banner += f'<div class="ok">{_e(msg)}</div>'
    if err:
        banner += f'<div class="err">{_e(err)}</div>'

    if ro:
        day_txt = "every day" if not days else ", ".join(n for i, n in _DAYS if i in days)
        en_txt = "yes" if enabled else "no"
        tz_txt = _e(tz or "server local")
        times_txt = _e(times or "-")
        src_txt = _e(", ".join(sorted(srcs)) or "-")
        an_txt = "yes" if analyze else "no"
        summary = (
            '<div class="card"><table>'
            f'<tr><td>Enabled</td><td><b>{en_txt}</b></td></tr>'
            f'<tr><td>Timezone</td><td>{tz_txt}</td></tr>'
            f'<tr><td>Days</td><td>{_e(day_txt)}</td></tr>'
            f'<tr><td>Times</td><td>{times_txt}</td></tr>'
            f'<tr><td>Sources</td><td>{src_txt}</td></tr>'
            f'<tr><td>Analyze after collect</td><td>{an_txt}</td></tr>'
            '</table></div>')
        return _layout(request, "Schedule", banner + '<p class="mut">Read-only mode.</p>' + summary)

    day_parts = []
    for i, n in _DAYS:
        chk = "checked" if i in days else ""
        day_parts.append(f'<label class="pillbox"><input type=checkbox name="day_{i}" {chk}>{n}</label>')
    day_boxes = "".join(day_parts)

    src_parts = []
    for k, lbl in _KNOWN_SOURCES:
        chk = "checked" if k in srcs else ""
        src_parts.append(f'<label class="pillbox"><input type=checkbox name="src_{k}" {chk}>'
                         f'{_e(lbl)}</label>')
    src_boxes = "".join(src_parts)

    en_chk = "checked" if enabled else ""
    an_chk = "checked" if analyze else ""
    tz_val = _e(tz)
    times_val = _e(times)

    body = f"""
{banner}
<style>
.pillbox{{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;margin:0 8px 8px 0;
  border-radius:999px;background:var(--chip);box-shadow:inset 0 0 0 1px var(--line);font-size:13px}}
.fld{{margin:0 0 16px}}
.fld label.h{{display:block;font-weight:600;margin-bottom:6px}}
.hint{{color:var(--mut);font-size:12px;margin:4px 0 0}}
</style>
<p class="res-intro" style="color:var(--mut);max-width:80ch">Daily automatic collection. Each run
fetches only new tenders from the selected sources and (optionally) analyses them right away.
Historical back-fills are done manually from the Sites page; this schedule only adds fresh finds
to <b>New</b>.</p>
<form method=post action="/schedule">
  <div class="card">
    <div class="fld">
      <label class="h">Enable scheduled collection</label>
      <label class="pillbox"><input type=checkbox name="enabled" {en_chk}> on</label>
    </div>
    <div class="fld">
      <label class="h" for="timezone">Timezone (IANA)</label>
      <input type=text id=timezone name="timezone" value="{tz_val}" placeholder="Europe/Chisinau"
             style="max-width:280px">
      <p class="hint">Empty = server local time. Days and times below use this zone.</p>
    </div>
    <div class="fld">
      <label class="h">Days of week</label>
      {day_boxes}
      <p class="hint">None selected = every day.</p>
    </div>
    <div class="fld">
      <label class="h" for="times">Run times</label>
      <input type=text id=times name="times" value="{times_val}"
             placeholder="06:00, 14:00, 20:00" style="max-width:420px">
      <p class="hint">Comma-separated HH:MM. Up to 24 per day; extra times are dropped.</p>
    </div>
    <div class="fld">
      <label class="h">Sources</label>
      {src_boxes}
      <p class="hint">Generic-web collection uses LLM tokens; MTender does not.</p>
    </div>
    <div class="fld">
      <label class="pillbox"><input type=checkbox name="analyze" {an_chk}>
        Analyse new tenders right after collecting</label>
    </div>
    <button>Save schedule</button>
  </div>
</form>
"""
    return _layout(request, "Schedule", body)


@router.post("/schedule")
async def schedule_save(request: Request):
    if request.state.readonly:
        return RedirectResponse("/schedule", status_code=303)
    form = await request.form()
    msg = settings_ops.save_schedule(form, request.state.store)
    from urllib.parse import urlencode
    return RedirectResponse("/schedule?" + urlencode({"msg": msg}), status_code=303)
