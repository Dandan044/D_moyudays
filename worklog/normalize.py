"""项目归一与产出类型判定。"""

from __future__ import annotations

import pathlib
import ntpath
import os

CODE_EXT = {
    ".py", ".pyw", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue",
    ".gd", ".go", ".rs", ".java", ".kt", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".cs", ".rb", ".php", ".swift", ".scala", ".lua", ".sql", ".css", ".scss",
    ".html", ".htm", ".sh", ".zsh",
}
DATA_EXT = {".csv", ".tsv", ".xlsx", ".xls", ".parquet", ".db", ".sqlite", ".jsonl", ".ndjson"}
DOC_EXT = {".md", ".markdown", ".txt", ".rst", ".docx", ".doc", ".pdf", ".pptx", ".ppt", ".xmind"}
OPS_EXT = {".yml", ".yaml", ".bat", ".ps1", ".cmd", ".toml", ".ini", ".cfg", ".conf", ".env", ".dockerfile"}

DOC_HINTS = ("readme", "报告", "方案", "文档", "doc", "日报", "周报", "笔记", "说明")
OPS_HINTS = ("dockerfile", ".gitignore", "makefile", "requirements", "package.json", "pyproject")

# 类型优先级：ops > code > data > doc > design
PRIORITY = ["ops", "code", "data", "doc"]


def norm_path(p: str | None) -> str:
    if not p:
        return ""
    p = p.strip().strip('"').strip("'")
    windows_path = os.name == "nt" or bool(ntpath.splitdrive(p)[0])
    p = p.replace("/", "\\")
    while len(p) > 3 and p.endswith("\\"):
        p = p[:-1]
    return p.lower() if windows_path else p


class ProjectResolver:
    """按最长前缀把文件路径 / cwd 归到一个项目。"""

    def __init__(self, config: dict):
        self.projects = {p["id"]: p for p in config["projects"]}
        self.ordered = sorted(
            config["projects"], key=lambda p: len(norm_path(p["path"])), reverse=True
        )
        self.misc = config.get("misc_project", {"id": "misc", "name": "杂项", "color": "#888780"})
        self.work_roots = [norm_path(r) for r in config.get("work_roots", [])]
        self.noise_keywords = [k.lower() for k in config.get("noise_keywords", [])]

    def resolve(self, path: str | None) -> str | None:
        np = norm_path(path)
        if not np:
            return None
        for p in self.ordered:
            base = norm_path(p["path"])
            if np == base or np.startswith(base + "\\"):
                return p["id"]
        return None

    def under_work_root(self, path: str | None) -> bool:
        np = norm_path(path)
        return any(np == r or np.startswith(r + "\\") for r in self.work_roots)

    def primary(self, paths: list[str], cwd: str | None) -> str:
        """先按变更文件路径投票，再退回 cwd，最后 misc。"""
        votes: dict[str, int] = {}
        for p in paths:
            pid = self.resolve(p)
            if pid:
                votes[pid] = votes.get(pid, 0) + 1
        if votes:
            return max(votes.items(), key=lambda kv: kv[1])[0]
        return self.resolve(cwd) or self.misc["id"]

    def is_noise_title(self, title: str) -> bool:
        t = (title or "").lower()
        return any(k in t for k in self.noise_keywords)


def classify(paths: list[str]) -> str:
    """按文件构成判定产出类型；无文件 = design（只讨论）。"""
    if not paths:
        return "design"
    hits = set()
    for raw in paths:
        p = raw.lower().replace("/", "\\")
        name = p.rsplit("\\", 1)[-1]
        ext = pathlib.PurePosixPath(name).suffix
        if ext in OPS_EXT or any(h in name for h in OPS_HINTS):
            hits.add("ops")
        if ext in CODE_EXT:
            hits.add("code")
        if ext in DATA_EXT:
            hits.add("data")
        if ext in DOC_EXT or any(h in p for h in DOC_HINTS):
            hits.add("doc")
    for kind in PRIORITY:
        if kind in hits:
            return kind
    return "doc"


def mask_title(title: str, sensitive: bool) -> tuple[str, int]:
    if sensitive:
        return "内部项目", 1
    return title, 0


def active_days_from(days: list[str]) -> tuple[list[str], int]:
    """去重排序的活跃日，并算最长连续段。"""
    uniq = sorted(set(days))
    if not uniq:
        return [], 0
    import datetime as _dt

    parsed = [_dt.date.fromisoformat(d) for d in uniq]
    best = cur = 1
    for i in range(1, len(parsed)):
        if (parsed[i] - parsed[i - 1]).days == 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return uniq, best
