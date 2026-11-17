"""接入 workbuddy 之外的 harness（Claude Code / Codex / dsh / 任何有此能力的东西）。

两个能力：
- probe：扫常见 harness 目录，报告发现了什么、长得像什么格式，把判断权交给调用它的模型
- ingest：把模型解析出来的统一事件写进库

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

CANDIDATES = [
    ("claude-code", "~/.claude", ["projects", "history.jsonl"]),
    ("codex", "~/.codex", ["sessions", "history.jsonl", "log"]),
    ("dsh", "~/.dsh", ["sessions", "logs", "history"]),
    ("cursor", "~/.cursor", ["chats", "workspaceStorage"]),
    ("continue", "~/.continue", ["sessions", "index"]),
    ("aider", "~/.aider", ["analytics", "history"]),
    ("gemini", "~/.gemini", ["tmp", "history"]),
    ("cline", "~/.cline", ["tasks"]),
    ("trae", "~/.trae", ["logs", "workspaceStorage"]),
    ("windsurf", "~/.codeium", ["windsurf", "chats"]),
]


def _sample(path: pathlib.Path, limit: int = 2) -> list[dict]:
    """采样 JSONL，给出字段轮廓，供模型判断。"""
    out = []
    files = sorted(path.rglob("*.jsonl"))[:3] if path.is_dir() else [path]
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for i, line in enumerate(fh):
                    if i >= limit:
                        break
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        out.append({"file": f.name, "parse": "invalid-json"})
                        continue
                    if isinstance(obj, dict):
                        out.append(
                            {
                                "file": f.name,
                                "keys": list(obj.keys())[:14],
                                "sample": {k: str(v)[:60] for k, v in list(obj.items())[:6]},
                            }
                        )
        except OSError:
            continue
    return out


def probe() -> dict:
    home = pathlib.Path.home()
    found = []
    for name, rel, hints in CANDIDATES:
        root = home / rel.lstrip("~/")
        if not root.exists():
            continue
        files = [p for p in root.rglob("*") if p.is_file()][:400]
        jsonl = [p for p in files if p.suffix == ".jsonl"]
        total = sum(p.stat().st_size for p in files if p.exists())
        found.append(
            {
                "harness": name,
                "path": str(root),
                "files": len(files),
                "jsonl": len(jsonl),
                "mb": round(total / 1_048_576, 1),
                "hints_present": [h for h in hints if (root / h).exists()],
                "sample": _sample(root) if jsonl else [],
            }
        )
    return {
        "home": str(home),
        "found": found,
        "note": "字段轮廓只是提示；实际字段含义请直接读样本前几行再判断",
    }


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
