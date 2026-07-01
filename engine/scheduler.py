from __future__ import annotations

import datetime as dt
import json
import threading
import time


def job_key(job) -> str:
    return json.dumps(job, sort_keys=True, ensure_ascii=False)


def job_due(job, now: dt.datetime, last_fired: dict) -> dt.datetime | None:
    if not job.get("enabled", True):
        return None
    key = job_key(job)
    if "at" in job:
        current = now.strftime("%H:%M")
        if current in job["at"]:
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
        self.last_fired: dict = {}
        self._stop = threading.Event()

    def tick(self, now: dt.datetime | None = None) -> list:
        now = now or dt.datetime.now()
        jobs = self.store.get("schedule.jobs", [])
        fired = []
        for job in jobs:
            slot = job_due(job, now, self.last_fired)
            if slot is not None:
                self.last_fired[job_key(job)] = slot
                pipeline = job["pipeline"]
                self.logger(f"dispatch {pipeline}")
                try:
                    self.dispatch(pipeline, job)
                except Exception as exc:
                    self.logger(f"dispatch error {pipeline}: {exc}")
                fired.append(pipeline)
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
