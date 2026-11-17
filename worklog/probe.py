"""探索本机目录，把证据摆出来，不做判断。

这个模块**故意不内置 harness 名单**：新 harness 层出不穷，写死清单必然过时。
它只负责回答「这个目录里有什么」——文件数、有没有 jsonl、样本长什么样、
最近什么时候动过。判断「这是不是 harness、能不能解析」交给调用它的模型。

用法：
    probe()                    扫家目录与 AppData，列出全部候选目录（不做筛选）
    probe("~/.codex")          只看指定目录，输出更详细的采样
"""

from __future__ import annotations

import json
import pathlib

SKIP_NAMES = {"node_modules", "site-packages", "__pycache__", ".git", "Cache", "CachedData"}


def _stats(d: pathlib.Path, limit: int = 800) -> dict:
    files = []
    try:
        for p in d.rglob("*"):
            if len(files) >= limit:
                break
            if p.is_file() and not any(s in p.parts for s in SKIP_NAMES):
                files.append(p)
    except (OSError, PermissionError):
        pass
    if not files:
        return {"files": 0, "jsonl": 0, "mb": 0.0, "latest": None}
    total = 0
    latest = 0.0
    for f in files:
        try:
            st = f.stat()
            total += st.st_size
            latest = max(latest, st.st_mtime)
        except OSError:
            continue
    import datetime as dt

    return {
        "files": len(files),
        "jsonl": sum(1 for f in files if f.suffix == ".jsonl"),
        "mb": round(total / 1_048_576, 1),
        "latest": dt.date.fromtimestamp(latest).isoformat() if latest else None,
    }


def _sample(path: pathlib.Path, limit: int = 2) -> list[dict]:
    """采样 JSONL 的字段轮廓——只给形状，不给结论。"""
    out = []
    files = sorted(path.rglob("*.jsonl"))[:2] if path.is_dir() else [path]
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
                                "keys": list(obj.keys())[:16],
                                "sample": {k: str(v)[:50] for k, v in list(obj.items())[:6]},
                            }
                        )
        except OSError:
            continue
    return out


def inspect(target: str) -> dict:
    """看一个目录（或文件）里到底有什么。"""
    p = pathlib.Path(target).expanduser()
    if not p.exists():
        return {"path": str(p), "exists": False}
    if p.is_file():
        return {
            "path": str(p),
            "exists": True,
            "is_file": True,
            "mb": round(p.stat().st_size / 1_048_576, 2),
            "sample": _sample(p, limit=3),
        }
    top = sorted(
        (x.name + ("/" if x.is_dir() else "") for x in p.iterdir() if not x.name.startswith("$"))
    )[:20]
    return {"path": str(p), "exists": True, "children": top, **_stats(p), "sample": _sample(p)}


def probe(target: str | None = None) -> dict:
    """不带 target 时，把家目录与 AppData 下的目录全列出来——包括点开头的隐藏目录。"""
    if target:
        return {"mode": "single", "target": inspect(target)}

    home = pathlib.Path.home()
    roots = [home, home / "AppData" / "Roaming", home / "AppData" / "Local"]
    candidates = []
    seen = set()

    for root in roots:
        if not root.is_dir():
            continue
        try:
            entries = sorted(root.iterdir())
        except (OSError, PermissionError):
            continue
        for d in entries:
            if not d.is_dir():
                continue
            low = d.name.lower()
            if low in SKIP_NAMES or low.startswith("microsoft") or low.startswith("temp"):
                continue
            st = _stats(d, limit=300)
            # 没有任何文件、或者太像普通软件目录的，也留着但不采样
            item = {"path": str(d), "name": d.name, **st}
            if st["jsonl"] and str(d) not in seen:
                item["sample"] = _sample(d)
                seen.add(str(d))
            if st["files"]:
                candidates.append(item)

    with_jsonl = sorted([c for c in candidates if c["jsonl"]], key=lambda x: (-x["jsonl"], -x["files"]))
    others = sorted([c for c in candidates if not c["jsonl"]], key=lambda x: -x["files"])[:25]

    return {
        "mode": "scan",
        "scanned": [str(r) for r in roots if r.is_dir()],
        "with_jsonl": with_jsonl,
        "others_sample": others,
        "others_total": len([c for c in candidates if not c["jsonl"]]),
        "hint": (
            "with_jsonl 是按会话日志数量排的，harness 几乎一定在这一组里；"
            "others_sample 只是文件多的目录，通常不是。"
            "判断某个目录是什么，靠读 sample 里的 keys，不要靠目录名——"
            "新 harness 的名字你大概率没见过。看到可疑目录就 probe <path> 深入看。"
        ),
    }
