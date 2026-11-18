"""自动发现本机项目，生成 config/projects.json。

原则：不猜、不乱填。只看 workbuddy 会话真实用过的工作目录，
向上找 git 仓库根；没有 git 又反复出现的目录才单独收进来。
"""

from __future__ import annotations

import collections
import json
import os
import pathlib

from . import db

SKIP_PARTS = {
    "node_modules", ".venv", "venv", "site-packages", "dist", "build",
    "__pycache__", ".git", "AppData", "Windows", "Program Files",
}


def _skip(path: pathlib.Path, repo: bool = False) -> bool:
    parts = {p.lower() for p in path.parts}
    ignored = SKIP_PARTS - {"AppData"} if repo else SKIP_PARTS
    if any(s.lower() in parts for s in ignored):
        return True
    low = str(path).lower()
    if "\\workbuddy\\" in low or "/workbuddy/" in low:
        return True
    if len(path.parts) <= (1 if repo else 2):
        return True
    return False


def find_repo_root(start: str | None) -> pathlib.Path | None:
    if not start:
        return None
    try:
        cur = pathlib.Path(start).resolve()
    except OSError:
        return None
    for _ in range(10):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _uniq_id(base: str, used: set[str]) -> str:
    cand = base
    i = 2
    while cand.lower() in used:
        cand = f"{base}-{i}"
        i += 1
    used.add(cand.lower())
    return cand


def discover(wb_home: pathlib.Path) -> tuple[list[dict], dict]:
    from . import scan as scan_mod

    sessions = scan_mod.read_sessions(wb_home)

    repo_hits: collections.Counter = collections.Counter()
    loose_hits: collections.Counter = collections.Counter()

    cwds = [s.get("cwd") for s in sessions.values() if s.get("cwd")]
    try:
        con = db.connect()
        cwds += [
            r["cwd"]
            for r in con.execute("SELECT cwd FROM external_session WHERE cwd IS NOT NULL")
        ]
        con.close()
    except Exception:  # noqa: BLE001
        pass

    for cwd in cwds:
        if not cwd:
            continue
        path = pathlib.Path(cwd)
        root = find_repo_root(cwd)
        if root and not _skip(root, repo=True):
            repo_hits[str(root)] += 1
        elif not _skip(path):
            loose_hits[str(path)] += 1

    entries = []
    used = {"misc", "all"}
    for root, n in repo_hits.most_common():
        p = pathlib.Path(root)
        entries.append({"path": str(p), "name": p.name, "sessions": n, "kind": "repo"})
    for cwd, n in loose_hits.most_common():
        if n < 2:
            continue
        p = pathlib.Path(cwd)
        entries.append({"path": str(p), "name": p.name, "sessions": n, "kind": "dir"})

    # 父子路径都保留：运行时按最长前缀匹配，子仓库自然优先，父仓库接住其余文件
    seen: set[str] = set()
    uniq = []
    for e in entries:
        key = os.path.normcase(os.path.normpath(e["path"]))
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    entries = uniq

    palette = ["#5DCAA5", "#AFA9EC", "#EF9F27", "#85B7EB", "#F0997B", "#ED93B1", "#97C459", "#B4B2A9"]
    projects = []
    for i, e in enumerate(entries):
        proj_id = _uniq_id(e["name"] or f"proj{i+1}", used)
        projects.append(
            {
                "id": proj_id,
                "name": e["name"] or proj_id,
                "path": e["path"],
                "color": palette[i % len(palette)],
                "kind": "auto",
                "sensitive": 0,
            }
        )

    stats = {
        "sessions": len(sessions),
        "repos": len(repo_hits),
        "loose": len([e for e in entries if e["kind"] == "dir"]),
    }
    return projects, stats


def write_config(wb_home: pathlib.Path, force: bool = False, refresh: bool = False) -> dict:
    cfg_path = db.CONFIG_PATH
    cur = db.load_config() if cfg_path.exists() and not force else None
    if cur is not None and not refresh:
        return {"skipped": True, "projects": len(cur["projects"]), "path": str(cfg_path)}

    projects, stats = discover(wb_home)
    if cur is not None:
        existing = cur["projects"]
        paths = {os.path.normcase(os.path.normpath(p["path"])) for p in existing}
        additions = [p for p in projects if os.path.normcase(os.path.normpath(p["path"])) not in paths]
        if not additions:
            return {"skipped": True, "projects": len(existing), "path": str(cfg_path)}
        used = {p["id"].lower() for p in existing} | {"all", "misc"}
        for p in additions:
            p["id"] = _uniq_id(p["name"], used)
        existing.extend(additions)
        cfg_path.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"skipped": False, "projects": len(existing), "path": str(cfg_path), **stats}
    cfg = {
        "workbuddy_home": str(wb_home),
        "work_roots": sorted({str(pathlib.Path(p["path"]).parent) for p in projects})[:6],
        "misc_project": {"id": "misc", "name": "杂项", "color": "#888780", "kind": "misc"},
        "noise_keywords": ["卸载", "安装", "下载地址", "密码", "教程", "怎么", "wifi", "驱动", "快捷键", "壁纸"],
        "projects": projects,
    }
    db.DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"skipped": False, "projects": len(projects), "path": str(cfg_path), **stats}
