"""工作单元分组：判定交给 LLM（通过 MCP 工具），本模块只负责存储与聚合。

设计约束：
- 不做任何基于规则的相似度合并，避免把 LLM 的判断替换成硬编码阈值。
- 分组结果存在 unit_group_map 里，独立于 work_unit，扫描重建不会丢。
- 未分组的工作单元保持 group_id 为空，前端按单条平铺（没有兜底合并）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json


def ensure_tables(con) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS work_group(
            id TEXT PRIMARY KEY, project_id TEXT, title TEXT,
            start_day TEXT, end_day TEXT, unit_count INTEGER,
            active_days TEXT, file_count INTEGER, additions INTEGER,
            deletions INTEGER, kinds TEXT, span_days INTEGER,
            note TEXT, created_at TEXT
        )"""
    )
    have = {r[1] for r in con.execute("PRAGMA table_info(work_group)")}
    for col, decl in (
        ("note", "TEXT"),
        ("created_at", "TEXT"),
        ("kinds", "TEXT"),
        ("span_days", "INTEGER"),
    ):
        if col not in have:
            con.execute(f"ALTER TABLE work_group ADD COLUMN {col} {decl}")
    con.execute(
        """CREATE TABLE IF NOT EXISTS unit_group_map(
            unit_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, assigned_at TEXT
        )"""
    )
    cols = [r[1] for r in con.execute("PRAGMA table_info(work_unit)")]
    if "group_id" not in cols:
        con.execute("ALTER TABLE work_unit ADD COLUMN group_id TEXT")


def _gid(project_id: str, unit_ids: list[str]) -> str:
    raw = project_id + "|" + ",".join(sorted(unit_ids))
    return "g-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def list_units(con, project_id: str, since: str | None = None, only_ungrouped: bool = False) -> list[dict]:
    """给 LLM 看的候选清单：只给判定所需的最小字段。"""
    sql = (
        "SELECT w.id, w.title, w.kind, w.start_day, w.end_day, w.span_days,"
        " w.active_day_count, w.file_count, w.additions, w.deletions, m.group_id"
        " FROM work_unit w LEFT JOIN unit_group_map m ON m.unit_id = w.id"
        " WHERE w.project_id = ?"
    )
    args: list = [project_id]
    if since:
        sql += " AND w.end_day >= ?"
        args.append(since)
    if only_ungrouped:
        sql += " AND m.group_id IS NULL"
    sql += " ORDER BY w.start_day ASC"
    out = []
    for r in con.execute(sql, args):
        out.append(
            {
                "id": r["id"],
                "title": r["title"],
                "kind": r["kind"],
                "start_day": r["start_day"],
                "end_day": r["end_day"],
                "span_days": r["span_days"],
                "active_days": r["active_day_count"],
                "files": r["file_count"],
                "additions": r["additions"],
                "deletions": r["deletions"],
                "group_id": r["group_id"],
                "top_files": [
                    x["path"].replace("\\", "/").split("/")[-1]
                    for x in con.execute(
                        "SELECT path FROM artifact WHERE work_unit_id=? ORDER BY additions DESC LIMIT 3",
                        (r["id"],),
                    )
                ],
            }
        )
    return out


def list_groups(con, project_id: str) -> list[dict]:
    out = []
    for g in con.execute(
        "SELECT * FROM work_group WHERE project_id=? ORDER BY start_day ASC", (project_id,)
    ):
        members = [
            r["unit_id"]
            for r in con.execute(
                "SELECT unit_id FROM unit_group_map WHERE group_id=? ORDER BY unit_id", (g["id"],)
            )
        ]
        out.append(
            {
                "id": g["id"],
                "title": g["title"],
                "note": g["note"],
                "unit_ids": members,
                "unit_count": g["unit_count"],
                "start_day": g["start_day"],
                "end_day": g["end_day"],
                "files": g["file_count"],
            }
        )
    return out


def _recompute(con, group_ids: set[str]) -> None:
    for gid in group_ids:
        rows = con.execute(
            "SELECT w.* FROM work_unit w JOIN unit_group_map m ON m.unit_id = w.id WHERE m.group_id=?",
            (gid,),
        ).fetchall()
        if not rows:
            con.execute("DELETE FROM work_group WHERE id=?", (gid,))
            continue
        days = sorted({d for r in rows for d in json.loads(r["active_days"] or "[]")})
        start_day = min((r["start_day"] for r in rows if r["start_day"]), default=None)
        end_day = max((r["end_day"] for r in rows if r["end_day"]), default=None)
        span = (
            (dt.date.fromisoformat(end_day) - dt.date.fromisoformat(start_day)).days + 1
            if start_day and end_day
            else 1
        )
        kinds: dict[str, int] = {}
        for r in rows:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        existing = con.execute("SELECT title, note, project_id FROM work_group WHERE id=?", (gid,)).fetchone()
        title = existing["title"] if existing and existing["title"] else rows[0]["title"]
        note = existing["note"] if existing else None
        project_id = existing["project_id"] if existing else rows[0]["project_id"]
        con.execute(
            """INSERT INTO work_group(id,project_id,title,start_day,end_day,unit_count,active_days,
               file_count,additions,deletions,kinds,span_days,note,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, start_day=excluded.start_day, end_day=excluded.end_day,
                 unit_count=excluded.unit_count, active_days=excluded.active_days,
                 file_count=excluded.file_count, additions=excluded.additions,
                 deletions=excluded.deletions, kinds=excluded.kinds, span_days=excluded.span_days,
                 note=excluded.note""",
            (
                gid, project_id, title, start_day, end_day, len(rows), json.dumps(days),
                sum(r["file_count"] for r in rows), sum(r["additions"] for r in rows),
                sum(r["deletions"] for r in rows), json.dumps(kinds, ensure_ascii=False),
                span, note, dt.datetime.now().isoformat(timespec="seconds"),
            ),
        )


def apply_groups(con, project_id: str, groups: list[dict]) -> dict:
    """LLM 返回的分组结果落库。groups: [{title, unit_ids[], note?}]"""
    ensure_tables(con)
    valid = {
        r["id"]
        for r in con.execute("SELECT id FROM work_unit WHERE project_id=?", (project_id,))
    }
    touched: set[str] = set()
    applied, skipped = [], []

    for g in groups or []:
        raw_ids = [str(u) for u in (g.get("unit_ids") or [])]
        ids = [u for u in raw_ids if u in valid]
        missing = [u for u in raw_ids if u not in valid]
        if not ids:
            skipped.append({"title": g.get("title"), "reason": "no valid unit_ids", "missing": missing[:5]})
            continue
        gid = g.get("id") or _gid(project_id, ids)
        owner = con.execute("SELECT project_id FROM work_group WHERE id=?", (gid,)).fetchone()
        if owner and owner["project_id"] != project_id:
            raise ValueError("主题属于另一项目")
        title = (g.get("title") or "").strip() or "未命名分组"
        # 同一批 unit 若已在别的组里，先摘出来
        qs = ",".join("?" * len(ids))
        old = [
            r["group_id"]
            for r in con.execute(f"SELECT DISTINCT group_id FROM unit_group_map WHERE unit_id IN ({qs})", ids)
        ]
        con.execute(f"DELETE FROM unit_group_map WHERE unit_id IN ({qs})", ids)
        con.execute(
            "INSERT INTO work_group(id,project_id,title,note,unit_count,active_days,kinds,created_at)"
            " VALUES(?,?,?,?,0,'[]','{}',?)"
            " ON CONFLICT(id) DO UPDATE SET title=excluded.title, note=excluded.note",
            (gid, project_id, title, g.get("note"), dt.datetime.now().isoformat(timespec="seconds")),
        )
        now = dt.datetime.now().isoformat(timespec="seconds")
        for uid in ids:
            con.execute(
                "INSERT INTO unit_group_map(unit_id,group_id,assigned_at) VALUES(?,?,?)"
                " ON CONFLICT(unit_id) DO UPDATE SET group_id=excluded.group_id, assigned_at=excluded.assigned_at",
                (uid, gid, now),
            )
        touched.add(gid)
        touched.update(old)
        applied.append({"id": gid, "title": title, "unit_count": len(ids), "skipped_ids": missing[:5]})

    _recompute(con, touched)
    _sync_group_col(con)
    return {
        "applied": applied,
        "skipped": skipped,
        "groups_total": con.execute(
            "SELECT COUNT(*) FROM work_group WHERE project_id=?", (project_id,)
        ).fetchone()[0],
        "ungrouped": con.execute(
            "SELECT COUNT(*) FROM work_unit w LEFT JOIN unit_group_map m ON m.unit_id=w.id"
            " WHERE w.project_id=? AND m.group_id IS NULL",
            (project_id,),
        ).fetchone()[0],
    }


def clear(con, project_id: str, group_ids: list[str] | None = None) -> int:
    ensure_tables(con)
    if group_ids:
        qs = ",".join("?" * len(group_ids))
        n = con.execute(
            f"SELECT COUNT(*) FROM unit_group_map WHERE group_id IN ({qs})", group_ids
        ).fetchone()[0]
        con.execute(f"DELETE FROM unit_group_map WHERE group_id IN ({qs})", group_ids)
        con.execute(f"DELETE FROM work_group WHERE id IN ({qs})", group_ids)
    else:
        n = con.execute(
            "SELECT COUNT(*) FROM unit_group_map m JOIN work_unit w ON w.id=m.unit_id WHERE w.project_id=?",
            (project_id,),
        ).fetchone()[0]
        con.execute(
            "DELETE FROM unit_group_map WHERE unit_id IN (SELECT id FROM work_unit WHERE project_id=?)",
            (project_id,),
        )
        con.execute("DELETE FROM work_group WHERE project_id=?", (project_id,))
    _sync_group_col(con)
    return n


def _sync_group_col(con) -> None:
    """把 map 里的归属回写到 work_unit.group_id，供查询侧直接用。"""
    con.execute(
        "UPDATE work_unit SET group_id = (SELECT group_id FROM unit_group_map WHERE unit_id = work_unit.id)"
    )


def reattach(con) -> int:
    """扫描重建 work_unit 之后把已有分组挂回去，并清掉空组。"""
    ensure_tables(con)
    con.execute("DELETE FROM unit_group_map WHERE unit_id NOT IN (SELECT id FROM work_unit)")
    con.execute("""DELETE FROM unit_group_map WHERE NOT EXISTS (
        SELECT 1 FROM work_unit w JOIN work_group g ON g.project_id = w.project_id
        WHERE w.id=unit_group_map.unit_id AND g.id=unit_group_map.group_id)""")
    _sync_group_col(con)
    stale = [
        r["id"]
        for r in con.execute(
            "SELECT g.id FROM work_group g LEFT JOIN unit_group_map m ON m.group_id=g.id"
            " GROUP BY g.id HAVING COUNT(m.unit_id)=0"
        )
    ]
    for gid in stale:
        con.execute("DELETE FROM work_group WHERE id=?", (gid,))
    ids = [r["id"] for r in con.execute("SELECT id FROM work_group")]
    _recompute(con, set(ids))
    return con.execute(
        "SELECT COUNT(*) FROM work_unit WHERE group_id IS NOT NULL"
    ).fetchone()[0]
