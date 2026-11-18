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
from .review import readable, task_title

def looks_like_path(p) -> bool:
    """判断一个值像不像文件路径。宁可错杀，也不要把结构体当文件名。"""
    if not isinstance(p, str):
        return False
    p = p.strip()
    if not p or p[0] in "{[<(":
        return False
    if p.startswith(("file:", "http://", "https://", "data:")):
        return False
    if len(p) > 260 or "\n" in p:
        return False
    return "/" in p or "\\" in p or "." in p.rsplit("/", 1)[-1]


def quality_report(payload: dict) -> dict:
    """给一次导入打分：看不出是不是真数据，就别假装成功。"""
    sessions = payload.get("sessions") or []
    events = [e for s in sessions for e in (s.get("events") or [])]
    n_s, n_e = len(sessions), len(events)
    if not n_s or not n_e:
        return {"ok": False, "reason": "没有可导入的会话或事件", "sessions": n_s, "events": n_e}

    default_titles = sum(1 for s in sessions if not task_title(s.get("title")))
    files = [e for e in events if not (e.get("action") == "activity" and not e.get("file"))]
    measured = [e for e in files if e.get("line_counts_known", True)]
    zero_lines = sum(1 for e in measured if not e.get("additions") and not e.get("deletions"))
    bad_paths = sum(1 for e in files if not looks_like_path(e.get("file")))
    no_cwd = sum(1 for s in sessions if not s.get("cwd"))

    r = {
        "sessions": n_s,
        "events": n_e,
        "default_title_ratio": round(default_titles / n_s, 2),
        "zero_lines_ratio": round(zero_lines / max(1, len(measured)), 2),
        "bad_path_ratio": round(bad_paths / max(1, len(files)), 2),
        "no_cwd_ratio": round(no_cwd / n_s, 2),
    }

    problems = []
    if any(not s.get("session_id") or not s.get("events") for s in sessions):
        problems.append("每个会话都需要稳定 ID 和至少一条活动记录")
    if any(not isinstance(e.get("ts"), int) or e["ts"] <= 0 for e in events):
        problems.append("每条事件都需要有效的毫秒时间戳")
    if any(s.get("title") and not readable(s["title"]) for s in sessions):
        problems.append("会话标题含宿主提示或角色设定，请回看用户请求和实际工作后命名")
    if r["default_title_ratio"] >= 0.8:
        problems.append(f"{int(r['default_title_ratio']*100)}% 的会话标题是默认值（说明没提取到真实标题）")
    if r["bad_path_ratio"] >= 0.3:
        problems.append(f"{int(r['bad_path_ratio']*100)}% 的 file 字段不是路径（抓错了层级）")
    if r["zero_lines_ratio"] >= 0.95:
        problems.append("几乎所有事件都没有增删行数（行数没解析出来）")

    r["ok"] = not problems
    r["problems"] = problems
    if problems:
        r["reason"] = (
            "解析质量不合格，已拒绝导入。" + "；".join(problems) +
            "。请读样本重新写解析脚本，不要用通用启发式硬猜。"
        )
    return r


def ingest(payload: dict, force: bool = False) -> dict:
    """把统一格式的会话事件写库，之后 scan 会像 workbuddy 会话一样聚合。"""
    from . import db

    source = payload.get("source") or "unknown"

    report = quality_report(payload)
    if not report["ok"] and not force:
        return {"source": source, "rejected": True, **report}

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
            owner = con.execute("SELECT source FROM external_session WHERE session_id=?", (sid,)).fetchone()
            if owner and owner["source"] != source:
                raise ValueError(f"会话 ID {sid!r} 已归属另一来源，请为新来源的 ID 加前缀后重试")
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
                fp = e.get("file")
                if fp is not None and not looks_like_path(fp):
                    fp = None
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
                                "file": fp,
                            },
                            ensure_ascii=False,
                        ),
                        None,
                    ),
                )
                n_events += cur.rowcount
    con.close()
    return {"source": source, "sessions": len(sessions) - n_skipped, "events": n_events, "skipped": n_skipped}
