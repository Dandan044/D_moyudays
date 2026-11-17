"""扫描 workbuddy 本地记录，归一成 event / work_unit / artifact。

只读外部数据：changes-index/*.json 与 workbuddy.db(只读连接)。
同一份输入幂等：event 靠 UNIQUE(source, source_ref) 去重，派生表每次整表重建。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import sqlite3
import tempfile

from . import db, group, normalize

# 活动块粒度：30 分钟没动作就算断开（只是给 LLM 看的候选，不是最终任务边界）
BLOCK_GAP_MS = 30 * 60 * 1000
# 尚未经 LLM 切分的会话，用这个规则兜底
GAP_MS = 4 * 3600 * 1000


def _make_blocks(items: list[dict]) -> list[dict]:
    """把文件级变更聚成「请求批次」再聚成「活动块」。"""
    batches: dict[str, dict] = {}
    for it in items:
        bid = it.get("req") or "norq"
        b = batches.setdefault(
            bid, {"batch_id": bid, "ts": it["ts"], "day": it["day"], "files": [], "add": 0, "del": 0}
        )
        b["files"].append(it["file"])
        b["add"] += it["add"]
        b["del"] += it["del"]
    ordered = sorted(batches.values(), key=lambda b: b["ts"])
    raw: list[list[dict]] = []
    for b in ordered:
        if raw and (b["ts"] - raw[-1][-1]["ts"]) <= BLOCK_GAP_MS:
            raw[-1].append(b)
        else:
            raw.append([b])

    out = []
    for i, group in enumerate(raw, 1):
        files: list[str] = []
        for b in group:
            files.extend(b["files"])
        out.append(
            {
                "block_id": f"b{i}",
                "start_ts": group[0]["ts"],
                "end_ts": group[-1]["ts"],
                "day": group[0]["day"],
                "batch_ids": [b["batch_id"] for b in group],
                "files": list(dict.fromkeys(files)),
                "add": sum(b["add"] for b in group),
                "del": sum(b["del"] for b in group),
            }
        )
    return out


def _day(ms: int | None) -> str | None:
    if not ms:
        return None
    return dt.datetime.fromtimestamp(ms / 1000).date().isoformat()


def _open_source(path: pathlib.Path) -> sqlite3.Connection:
    """只读打开 workbuddy.db；失败则复制快照再读，绝不写入原库。"""
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
        con.execute("SELECT count(*) FROM sessions").fetchone()
        return con
    except sqlite3.Error:
        pass
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="worklog-snap-"))
    dst = tmpdir / "workbuddy.db"
    shutil.copy2(path, dst)
    for suffix in ("-wal", "-shm"):
        side = pathlib.Path(str(path) + suffix)
        if side.exists():
            shutil.copy2(side, tmpdir / (dst.name + suffix))
    con = sqlite3.connect(dst)
    con.row_factory = sqlite3.Row
    return con


def read_sessions(wb_home: pathlib.Path) -> dict[str, dict]:
    src = wb_home / "workbuddy.db"
    if not src.exists():
        # 这台机器可能根本没装 workbuddy：不是错误，只是这个源为空
        return {}
    con = _open_source(src)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT id, cwd, title, custom_title, created_at, updated_at,
               last_activity_at, model, status, is_playground
        FROM sessions
        WHERE deleted_at IS NULL
        """
    ).fetchall()
    con.close()
    out = {}
    for r in rows:
        title = (r["title"] or r["custom_title"] or "").strip()
        if not title:
            title = pathlib.PureWindowsPath(r["cwd"] or "").name or "未命名会话"
        out[r["id"]] = {
            "id": r["id"],
            "cwd": r["cwd"],
            "title": title,
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "last_activity_at": r["last_activity_at"],
            "model": r["model"],
            "is_playground": r["is_playground"],
        }
    return out


def read_changes(wb_home: pathlib.Path) -> list[dict]:
    """展开 changes-index，得到逐文件的变更记录。"""
    out = []
    if not (wb_home / "changes-index").is_dir():
        return out
    for path in sorted((wb_home / "changes-index").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for ch in payload.get("changes", []):
            conv = ch.get("conversationId")
            if not conv:
                continue
            ts = ch.get("createdAt") or 0
            day = _day(ts)
            detail = ch.get("detailRef")
            for f in ch.get("files", []):
                fp = f.get("filePath")
                if not fp:
                    continue
                out.append(
                    {
                        "conv": conv,
                        "req": ch.get("requestId") or "",
                        "ts": ts,
                        "day": day,
                        "file": fp,
                        "action": f.get("action"),
                        "add": int(f.get("additions") or 0),
                        "del": int(f.get("deletions") or 0),
                        "detail": detail,
                    }
                )
    return out


def scan(verbose: bool = True) -> dict:
    config = db.load_config()
    wb_home = pathlib.Path(config.get("workbuddy_home") or (pathlib.Path.home() / ".workbuddy"))
    resolver = normalize.ProjectResolver(config)

    sessions = read_sessions(wb_home)
    changes = read_changes(wb_home)

    con = db.connect()
    db.ensure_columns(con)
    with con:
        con.execute("DELETE FROM project")
        for p in config["projects"]:
            con.execute(
                "INSERT INTO project(id,name,path,color,kind,sensitive) VALUES(?,?,?,?,?,?)",
                (p["id"], p["name"], p.get("path"), p.get("color"), p.get("kind"), int(p.get("sensitive") or 0)),
            )
        misc = config.get("misc_project", {})
        con.execute(
            "INSERT INTO project(id,name,path,color,kind,sensitive) VALUES(?,?,?,?,?,0)",
            (misc.get("id", "misc"), misc.get("name", "杂项"), None, misc.get("color", "#888780"), "misc"),
        )

        new_events = 0
        for c in changes:
            cur = con.execute(
                "INSERT OR IGNORE INTO event(source, source_ref, ts, day, session_id, project_id, kind, signal, raw_ref)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    "changes",
                    f"{c['conv']}:{c['req']}:{c['file']}",
                    c["ts"],
                    c["day"],
                    c["conv"],
                    None,
                    "file_change",
                    json.dumps({"additions": c["add"], "deletions": c["del"], "action": c["action"]}, ensure_ascii=False),
                    c["detail"],
                ),
            )
            new_events += cur.rowcount

        # ---- 派生层：每次整表重建（先保住人工/LLM 写的摘要）----
        prev_notes = {
            r["id"]: (r["summary"], r["detail"])
            for r in con.execute("SELECT id, summary, detail FROM work_unit")
            if r["summary"] or r["detail"]
        }
        # ---- 其它 harness 导入的会话（Claude Code / Codex / dsh …）----
        for r in con.execute("SELECT * FROM external_session"):
            sessions.setdefault(
                r["session_id"],
                {
                    "id": r["session_id"],
                    "cwd": r["cwd"],
                    "title": r["title"] or f"{r['source']} 会话",
                    "created_at": r["start_ts"] or 0,
                    "updated_at": r["end_ts"] or 0,
                    "last_activity_at": r["end_ts"],
                    "model": r["source"],
                    "is_playground": 0,
                    "external": True,
                },
            )
        for r in con.execute("SELECT * FROM event WHERE source != 'changes'"):
            if not r["session_id"]:
                continue
            sig = json.loads(r["signal"] or "{}")
            changes.append(
                {
                    "conv": r["session_id"],
                    "req": r["source_ref"] or "",
                    "ts": r["ts"],
                    "day": r["day"],
                    "file": sig.get("file") or "",
                    "action": sig.get("action") or "edit",
                    "add": int(sig.get("additions") or 0),
                    "del": int(sig.get("deletions") or 0),
                    "detail": None,
                }
            )

        con.execute("DELETE FROM artifact")
        con.execute("DELETE FROM work_unit")
        con.execute("DELETE FROM session_block")
        splits = {
            r["session_id"]: json.loads(r["payload"])
            for r in con.execute("SELECT session_id, payload FROM session_split")
        }

        by_conv: dict[str, list[dict]] = {}
        for c in changes:
            by_conv.setdefault(c["conv"], []).append(c)

        units = []
        for sid, s in sessions.items():
            raw_items = sorted(by_conv.get(sid, []), key=lambda x: x["ts"])
            blocks = _make_blocks(raw_items)
            for b in blocks:
                con.execute(
                    "INSERT INTO session_block(block_id, session_id, day, start_ts, end_ts,"
                    " files, additions, deletions, batch_ids) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        f"{sid}:{b['block_id']}", sid, b["day"], b["start_ts"], b["end_ts"],
                        json.dumps([f.split("\\")[-1] for f in b["files"]][:8], ensure_ascii=False),
                        b["add"], b["del"], json.dumps(b["batch_ids"]),
                    ),
                )

            split = splits.get(sid)
            segments: list[tuple[str, list[dict]]] = []
            if split and blocks:
                by_batch = {bid: b["block_id"] for b in blocks for bid in b["batch_ids"]}
                claimed: set[str] = set()
                for seg in split.get("segments", []):
                    ids = {bid for bid in by_batch if by_batch[bid] in set(seg.get("block_ids") or [])}
                    claimed |= ids
                    picked = [it for it in raw_items if (it.get("req") or "norq") in ids]
                    segments.append(((seg.get("title") or "").strip(), picked))
                rest = [it for it in raw_items if (it.get("req") or "norq") not in claimed]
                if rest:
                    if segments:
                        segments[-1] = (segments[-1][0], segments[-1][1] + rest)
                    else:
                        segments.append(("", rest))
            elif raw_items:
                groups: list[list[dict]] = []
                for it in raw_items:
                    same_day = bool(groups) and it["day"] == groups[-1][-1]["day"]
                    gap_ok = bool(groups) and (it["ts"] - groups[-1][-1]["ts"]) <= GAP_MS
                    if groups and (same_day or gap_ok):
                        groups[-1].append(it)
                    else:
                        groups.append([it])
                segments = [("", g) for g in groups]
            else:
                segments = [("", [])]

            multi = len(segments) > 1
            for idx, (seg_title, items) in enumerate(segments, 1):
                uid = sid if not multi else f"{sid}#{idx}"
                for it in items:
                    it["uid"] = uid
                paths = [i["file"] for i in items]
                project_id = resolver.primary(paths, s["cwd"])
                kind = normalize.classify(paths)
                days = [i["day"] for i in items if i["day"]]
                if days:
                    start_day, end_day = min(days), max(days)
                else:
                    start_day = end_day = _day(s["created_at"])
                    if start_day:
                        days = [start_day]
                active, streak = normalize.active_days_from(days)
                if start_day and end_day:
                    span = (dt.date.fromisoformat(end_day) - dt.date.fromisoformat(start_day)).days + 1
                else:
                    span = 1
                proj = con.execute("SELECT sensitive FROM project WHERE id=?", (project_id,)).fetchone()
                base_title = seg_title or s["title"]
                if multi and not seg_title:
                    # 同一会话被切成多段时，用「会话名 + 该段首日」区分，等 LLM 再改名
                    md = f"{int(start_day[5:7])}/{int(start_day[8:10])}" if start_day else ""
                    base_title = f"{md} {s['title']}"
                title, masked = normalize.mask_title(base_title, bool(proj and proj["sensitive"]))
                no_artifacts = not items
                is_noise = int(
                    project_id == resolver.misc["id"] and (no_artifacts or resolver.is_noise_title(s["title"]))
                )
                units.append(
                    {
                        "id": uid,
                        "session_id": sid,
                        "title": title,
                        "raw_title": s["title"],
                        "project_id": project_id,
                        "kind": kind,
                        "start_day": start_day,
                        "end_day": end_day,
                        "span_days": span,
                        "active_days": active,
                        "max_streak": streak,
                        "file_count": len(set(paths)),
                        "additions": sum(i["add"] for i in items),
                        "deletions": sum(i["del"] for i in items),
                        "is_noise": is_noise,
                        "masked": masked,
                        "cwd": s["cwd"],
                        "harness": s.get("model") if s.get("external") else "workbuddy",
                    }
                )

        for u in units:
            con.execute(
                """INSERT INTO work_unit(id,session_id,title,project_id,kind,start_day,end_day,span_days,
                    active_day_count,max_streak,active_days,file_count,additions,deletions,
                    is_noise,masked,raw_title,harness) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    u["id"], u["session_id"], u["title"], u["project_id"], u["kind"], u["start_day"],
                    u["end_day"], u["span_days"], len(u["active_days"]), u["max_streak"],
                    json.dumps(u["active_days"]), u["file_count"], u["additions"], u["deletions"],
                    u["is_noise"], u["masked"], u["raw_title"], u["harness"],
                ),
            )

        for c in changes:
            con.execute(
                "INSERT INTO artifact(work_unit_id,path,action,additions,deletions,ts,day)"
                " VALUES(?,?,?,?,?,?,?)",
                (c.get("uid") or c["conv"], c["file"], c["action"], c["add"], c["del"], c["ts"], c["day"]),
            )

        # 摘要/详情按仍然存在的单元回填（拆段后 id 变了的由 LLM 重新生成）
        for uid, (summary, detail) in prev_notes.items():
            con.execute(
                "UPDATE work_unit SET summary=?, detail=? WHERE id=? AND summary IS NULL",
                (summary, detail, uid),
            )

        group.reattach(con)

        db.set_meta(con, "last_scan_at", dt.datetime.now().isoformat(timespec="seconds"))
        db.set_meta(con, "source_changes", str(len(changes)))
        db.set_meta(con, "source_sessions", str(len(sessions)))

    stats = {
        "sessions": len(sessions),
        "change_rows": len(changes),
        "new_events": new_events,
        "work_units": len(units),
        "projects_hit": len({u["project_id"] for u in units}),
        "noise": sum(u["is_noise"] for u in units),
        "design": sum(1 for u in units if u["kind"] == "design"),
    }
    if verbose:
        print(
            f"扫描完成: 会话 {stats['sessions']} / 变更行 {stats['change_rows']} / "
            f"新增事件 {stats['new_events']} / 工作单元 {stats['work_units']} / "
            f"涉及项目 {stats['projects_hit']} / 杂项 {stats['noise']} / 纯讨论 {stats['design']}"
        )
    con.close()
    return stats
