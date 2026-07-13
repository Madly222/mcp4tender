from __future__ import annotations

import datetime as dt
import json
import threading

_DAYNAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

MAX_TIMES_PER_DAY = 24


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


def job_due(job, now, last_fired):
    if not job.get("enabled", True):
        return None
    days = _norm_days(job.get("days"))
    if days and now.weekday() not in days:
        return None
    key = job_key(job)
    times = job_times(job)
    if times:
        current = now.strftime("%H:%M")
        if current in times:
            slot = now.replace(second=0, microsecond=0)
            if last_fired.get(key) != slot:
                return slot
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

    def tick(self, now=None):
        now = now or now_in_tz(self.store)
        jobs = self.store.get("schedule.jobs", [])
        fired = []
        for job in jobs:
            slot = job_due(job, now, self.last_fired)
            if slot is not None:
                self.last_fired[job_key(job)] = slot
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
