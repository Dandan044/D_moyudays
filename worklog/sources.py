"""各 harness 的内置解析器。

原则：能确定解析的才内置（claude-code 已验证），格式不确定的用启发式兜底，
解析不出来的交给调用它的模型现场处理——probe 会标出来。

统一产出 ingest 需要的格式：
    {"source": ..., "sessions": [{"session_id", "cwd", "title", "events": [...]}]}
"""

from __future__ import annotations

import collections
import datetime as dt
import json
import pathlib

TIME_KEYS = ("timestamp", "ts", "time", "created_at", "createdAt", "date")
FILE_KEYS = ("file_path", "filePath", "path", "filename", "target_file")
CWD_KEYS = ("cwd", "projectPath", "workspace", "workspaceFolder", "project", "project_path")


def _to_ms(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v if v > 1e11 else v * 1000)
    s = str(v).strip()
    if s.isdigit():
        n = int(s)
        return n if n > 1e11 else n * 1000
    try:
        return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _first(d: dict, keys) -> object:
    for k in keys:
        if d.get(k):
            return d[k]
    return None


def _deep(d, keys, depth: int = 3):
    """在嵌套结构里找第一个命中的键。"""
    if depth < 0 or not isinstance(d, dict):
        return None
    v = _first(d, keys)
    if v:
        return v
    for val in d.values():
        if isinstance(val, dict):
            got = _deep(val, keys, depth - 1)
            if got:
                return got
        elif isinstance(val, list):
            for item in val[:4]:
                got = _deep(item, keys, depth - 1)
                if got:
                    return got
    return None


def _lines(v) -> int:
    return len(str(v).splitlines()) if v else 0


# ---------------- Claude Code ----------------
def claude_code(home: pathlib.Path) -> dict | None:
    root = home / ".claude" / "projects"
    if not root.is_dir():
        return None

    sessions: dict[str, dict] = {}
    for f in root.rglob("*.jsonl"):
        sid = f.stem
        rec = sessions.setdefault(sid, {"session_id": sid, "cwd": None, "title": None, "events": []})
        votes: collections.Counter = collections.Counter()

        for line in _iter_jsonl(f):
            cwd = _first(line, CWD_KEYS)
            if cwd:
                votes[str(cwd)] += 1
            ms = _to_ms(_first(line, TIME_KEYS))
            if not ms:
                continue

            if line.get("type") == "user" and not rec["title"]:
                c = (line.get("message") or {}).get("content")
                if isinstance(c, str):
                    rec["title"] = c[:60]
                elif isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and b.get("type") == "text":
                            rec["title"] = str(b.get("text", ""))[:60]
                            break

            if line.get("type") != "assistant":
                continue
            for b in ((line.get("message") or {}).get("content") or []):
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                name = b.get("name")
                inp = b.get("input") or {}
                fp = inp.get("file_path") or inp.get("path")
                if not fp or name not in ("Edit", "Write", "NotebookEdit"):
                    continue
                if name == "Write":
                    adds, dels = _lines(inp.get("content")), 0
                else:
                    old, new = _lines(inp.get("old_string")), _lines(inp.get("new_string"))
                    adds, dels = (new - old, 0) if new >= old else (0, old - new)
                rec["events"].append(
                    {"ts": ms, "file": fp, "action": str(name).lower(), "additions": adds, "deletions": dels}
                )

        if votes:
            rec["cwd"] = votes.most_common(1)[0][0]
        if not rec["title"]:
            rec["title"] = "Claude Code 会话"

    keep = [s for s in sessions.values() if s["events"]]
    return {"source": "claude-code", "sessions": keep} if keep else None


# ---------------- Codex / 通用 JSONL ----------------
def generic_jsonl(home: pathlib.Path, source: str, rel: str) -> dict | None:
    """格式未知时的启发式：找时间戳 + 文件路径，按文件分组成会话。"""
    root = home / rel.lstrip("~/")
    if not root.exists():
        return None

    sessions: dict[str, dict] = {}
    for f in sorted(root.rglob("*.jsonl"))[:400]:
        sid = f.stem
        rec = sessions.setdefault(sid, {"session_id": sid, "cwd": None, "title": None, "events": []})
        for line in _iter_jsonl(f):
            ms = _to_ms(_deep(line, TIME_KEYS))
            if not ms:
                continue
            if not rec["cwd"]:
                cwd = _deep(line, CWD_KEYS)
                if cwd:
                    rec["cwd"] = str(cwd)
            fp = _deep(line, FILE_KEYS)
            if not fp:
                continue
            fp = str(fp)
            if len(fp) < 4 or fp.startswith(("http://", "https://")):
                continue
            sig = _deep(line, ("additions", "added", "lines_added")) or 0
            dei = _deep(line, ("deletions", "removed", "lines_removed")) or 0
            rec["events"].append(
                {"ts": ms, "file": fp, "action": "edit", "additions": int(sig), "deletions": int(dei)}
            )
        if not rec["title"]:
            rec["title"] = f"{source} 会话"

    keep = [s for s in sessions.values() if s["events"]]
    return {"source": source, "sessions": keep} if keep else None


def _iter_jsonl(path: pathlib.Path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


AUTO_SOURCES = [
    ("claude-code", lambda h: claude_code(h)),
    ("codex", lambda h: generic_jsonl(h, "codex", "~/.codex")),
    ("cursor", lambda h: generic_jsonl(h, "cursor", "~/.cursor")),
    ("trae", lambda h: generic_jsonl(h, "trae", "~/.trae")),
    ("continue", lambda h: generic_jsonl(h, "continue", "~/.continue")),
]


def autoload(home: pathlib.Path) -> dict[str, dict]:
    """把所有能自动解析的 harness 跑一遍。解析失败的静默跳过，由 agent 兜底。"""
    out: dict[str, dict] = {}
    for name, fn in AUTO_SOURCES:
        try:
            payload = fn(home)
        except Exception:  # noqa: BLE001 —— 单个源坏掉不能拖垮整体
            continue
        if payload and payload.get("sessions"):
            out[name] = payload
    return out
