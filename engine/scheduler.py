from __future__ import annotations

import datetime as dt
import json
import threading

_DAYNAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

MAX_TIMES_PER_DAY = 24

# How late a missed time-slot may still fire. A tick that lands after the exact
# minute (loop blocked by a long job, a restart, clock drift) still runs the slot
# instead of silently dropping it — but a slot older than this is treated as stale
# and skipped, so a restart at 15:00 doesn't run the 09:00 batch.
DEFAULT_CATCHUP_MINUTES = 180


def job_key(job) -> str:
    return json.dumps(job, sort_keys=True, ensure_ascii=False)


def _norm_days(days):
    out = set()
    for d in days or []:
        if isinstance(d, bool):
            continue
        if isinstance(d, int):
            out.add(d % 7)
        else:
            k = str(d).strip().lower()[:3]
            if k in _DAYNAMES:
                out.add(_DAYNAMES[k])
    return out


def job_times(job):
    seen = []
    for t in job.get("at") or []:
        t = str(t)
        if t not in seen:
            seen.append(t)
    return sorted(seen)[:MAX_TIMES_PER_DAY]


def now_in_tz(store):
    tzname = (store.get("schedule.timezone", "") or "").strip()
    if tzname:
        try:
            from zoneinfo import ZoneInfo
            return dt.datetime.now(ZoneInfo(tzname))
        except Exception:
            pass
    return dt.datetime.now()


def slot_id(when):
    return when.strftime("%Y-%m-%d %H:%M")


def job_due(job, now, last_fired, catchup_minutes=DEFAULT_CATCHUP_MINUTES):
    if not job.get("enabled", True):
        return None
    days = _norm_days(job.get("days"))
    if days and now.weekday() not in days:
        return None
    key = job_key(job)
    times = job_times(job)
    if times:
        due = None
        for t in times:
            try:
                hh, mm = str(t).split(":")
                slot = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            except (ValueError, TypeError):
                continue
            if slot <= now and (due is None or slot > due):
                due = slot
        if due is None:
            return None
        if (now - due).total_seconds() > catchup_minutes * 60:
            return None
        if last_fired.get(key) != slot_id(due):
            return due
        return None
    if "every_minutes" in job:
        interval = int(job["every_minutes"]) * 60
        lf = last_fired.get(key)
        if lf is None or (now - lf).total_seconds() >= interval:
            return now
    return None


class Scheduler:
    def __init__(self, store, dispatch, logger=None):
        self.store = store
        self.dispatch = dispatch
        self.logger = logger or (lambda m: None)
        self.last_fired = {}
        self._stop = threading.Event()
        saved = self.store.get("schedule.last_fired", {}) or {}
        if isinstance(saved, dict):
            for k, v in saved.items():
                if isinstance(v, str):
                    self.last_fired[k] = v

    def _persist_fired(self):
        keep = {k: v for k, v in self.last_fired.items() if isinstance(v, str)}
        try:
            self.store.set("schedule.last_fired", keep, actor="scheduler",
                           note="slot fire tracking")
        except Exception as exc:
            self.logger(f"could not persist schedule state: {exc}")

    def tick(self, now=None):
        now = now or now_in_tz(self.store)
        jobs = self.store.get("schedule.jobs", [])
        try:
            grace = int(self.store.get("schedule.catchup_minutes", DEFAULT_CATCHUP_MINUTES)
                        or DEFAULT_CATCHUP_MINUTES)
        except (TypeError, ValueError):
            grace = DEFAULT_CATCHUP_MINUTES
        fired = []
        for job in jobs:
            slot = job_due(job, now, self.last_fired, grace)
            if slot is not None:
                key = job_key(job)
                if job_times(job):
                    self.last_fired[key] = slot_id(slot)
                    self._persist_fired()
                else:
                    self.last_fired[key] = slot
                label = job.get("pipeline") or job.get("kind") or "job"
                self.logger(f"dispatch {label}")
                try:
                    self.dispatch(job.get("pipeline"), job)
                except Exception as exc:
                    self.logger(f"dispatch error {label}: {exc}")
                fired.append(label)
        return fired

    def run_forever(self, interval: int = 30):
        self.logger("scheduler started")
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                self.logger(f"tick error: {exc}")
            self._stop.wait(interval)
        self.logger("scheduler stopped")

    def stop(self):
        self._stop.set()
