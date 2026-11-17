"""把任意 harness 的记录写进库。

这里只有 ingest——没有目录名单，也没有格式判断。
「去哪找、怎么解析」由调用它的模型决定（配套工具是 worklog.probe）。

统一输入格式（模型负责从各家日志里抽成这个形状）：
    {"source": "claude-code",
     "sessions": [{"session_id": "...", "cwd": "D:/work/proj", "title": "...",
                   "events": [{"ts": 1760000000000, "file": "src/a.ts",
                               "action": "edit", "additions": 12, "deletions": 3}]}]}
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

def ingest(payload: dict) -> dict:
    """把统一格式的会话事件写库，之后 scan 会像 workbuddy 会话一样聚合。"""
    from . import db

    source = payload.get("source") or "unknown"
    sessions = payload.get("sessions") or []
    con = db.connect()
    db.ensure_columns(con)

    n_events = 0
    n_skipped = 0
    with con:
        for s in sessions:
            sid = str(s.get("session_id") or "").strip()
            events = s.get("events") or []
            if not sid or not events:
                n_skipped += 1
                continue
            stamps = [int(e["ts"]) for e in events if e.get("ts")]
            con.execute(
                "INSERT INTO external_session(session_id,source,cwd,title,start_ts,end_ts,imported_at)"
                " VALUES(?,?,?,?,?,?,?)"
                " ON CONFLICT(session_id) DO UPDATE SET source=excluded.source, cwd=excluded.cwd,"
                " title=excluded.title, start_ts=excluded.start_ts, end_ts=excluded.end_ts",
                (
                    sid,
                    source,
                    s.get("cwd"),
                    s.get("title") or f"{source} 会话",
                    min(stamps) if stamps else None,
                    max(stamps) if stamps else None,
                    dt.datetime.now().isoformat(timespec="seconds"),
                ),
            )
            for i, e in enumerate(events):
                ts = int(e.get("ts") or 0)
                if not ts:
                    continue
                day = dt.datetime.fromtimestamp(ts / 1000).date().isoformat()
                cur = con.execute(
                    "INSERT OR IGNORE INTO event(source, source_ref, ts, day, session_id,"
                    " project_id, kind, signal, raw_ref) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        source,
                        f"{sid}:{i}",
                        ts,
                        day,
                        sid,
                        None,
                        "file_change",
                        json.dumps(
                            {
                                "additions": int(e.get("additions") or 0),
                                "deletions": int(e.get("deletions") or 0),
                                "action": e.get("action"),
                                "file": e.get("file"),
                            },
                            ensure_ascii=False,
                        ),
                        None,
                    ),
                )
                n_events += cur.rowcount
    con.close()
    return {"source": source, "sessions": len(sessions) - n_skipped, "events": n_events, "skipped": n_skipped}
