from __future__ import annotations

import time


def log_steps(conn, tender_id, stage, steps):
    if tender_id is None:
        return
    try:
        conn.execute("DELETE FROM stage_events WHERE tender_id=? AND stage=?",
                     (tender_id, stage))
        for i, s in enumerate(steps or []):
            if isinstance(s, dict):
                label, detail = s.get("label"), s.get("detail")
            else:
                label = s[0]
                detail = s[1] if len(s) > 1 else ""
            conn.execute(
                "INSERT INTO stage_events(tender_id,stage,seq,label,detail,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (tender_id, stage, i, str(label or ""), str(detail or ""), time.time()))
        conn.commit()
    except Exception:
        pass
