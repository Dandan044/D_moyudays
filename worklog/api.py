"""本地 HTTP 服务：标准库 http.server，只监听 127.0.0.1。"""

from __future__ import annotations

import datetime as dt
import json
import mimetypes
import pathlib
import sqlite3
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import db

WEB_DIR = db.ROOT / "web"
ALL_ID = "all"
MISC_ID = "misc"


def _scope(alias: str, project_id: str, harness: str | None = None) -> tuple[str, list]:
    """返回 (SQL 条件, 参数)。all = 除杂项外的所有项目；harness 为来源过滤。"""
    pcol = f"{alias}.project_id" if alias else "project_id"
    if project_id == ALL_ID:
        conds, args = [f"{pcol} != '{MISC_ID}'"], []
    else:
        conds, args = [f"{pcol} = ?"], [project_id]
    if harness:
        hcol = f"{alias}.harness" if alias else "harness"
        conds.append(f"{hcol} = ?")
        args.append(harness)
    return " AND ".join(conds), args
WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _default_range(days: int = 14) -> tuple[str, str]:
    end = dt.date.today()
    start = end - dt.timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _segs(active: list[str], dfrom: dt.date, dto: dt.date) -> list[list[str]]:
    """把活跃日合并成连续段，并按窗口裁剪。"""
    pts = sorted({x for x in active if dfrom.isoformat() <= x <= dto.isoformat()})
    if not pts:
        return []
    out = [[pts[0], pts[0]]]
    for p in pts[1:]:
        if (_d(p) - _d(out[-1][1])).days == 1:
            out[-1][1] = p
        else:
            out.append([p, p])
    return out


def fmt_h(v: float) -> str:
    h = int(v)
    m = int(round((v - h) * 60))
    if m == 60:
        h, m = h + 1, 0
    return f"{h:02d}:{m:02d}"


def _detail_json(row) -> dict | None:
    if "detail" not in row.keys() or not row["detail"]:
        return None
    try:
        data = json.loads(row["detail"])
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _unit_detail(con, uid: str, repo_path: str | None) -> dict:
    """把一个单元的变更摊成「目录 / 代表文件」，供卡片展示。"""
    arts = con.execute(
        "SELECT path, action, additions, deletions FROM artifact WHERE work_unit_id=?", (uid,)
    ).fetchall()
    base = (repo_path or "").replace("\\", "/").rstrip("/").lower()
    dirs: dict[str, dict] = {}
    files: dict[str, dict] = {}

    for a in arts:
        p = a["path"].replace("\\", "/")
        low = p.lower()
        rel = p[len(base) + 1 :] if base and low.startswith(base + "/") else p
        parts = [x for x in rel.split("/") if x]
        if not parts:
            continue
        name = parts[-1]
        top = parts[0] if len(parts) > 1 else "."
        d = dirs.setdefault(top, {"dir": top, "names": set(), "add": 0, "del": 0})
        d["names"].add(name)
        d["add"] += a["additions"] or 0
        d["del"] += a["deletions"] or 0
        parent = parts[-2] if len(parts) >= 2 else "."
        f = files.get(name)
        if not f:
            files[name] = {
                "name": name,
                "path": parent,
                "action": a["action"],
                "add": a["additions"] or 0,
                "del": a["deletions"] or 0,
            }
        else:
            f["add"] += a["additions"] or 0
            f["del"] += a["deletions"] or 0

    dir_list = [
        {"dir": d["dir"], "files": len(d["names"]), "add": d["add"], "del": d["del"]}
        for d in sorted(dirs.values(), key=lambda x: -(x["add"] + x["del"]))[:6]
    ]
    file_list = sorted(files.values(), key=lambda x: -(x["add"] + x["del"]))[:10]
    return {"dirs": dir_list, "files": file_list}


def build_payload(con: sqlite3.Connection, project_id: str, date_from: str, date_to: str, harness: str | None = None) -> dict:
    db.ensure_columns(con)
    dfrom, dto = _d(date_from), _d(date_to)
    if project_id == ALL_ID:
        proj = {"id": ALL_ID, "name": "全部项目", "color": "#D8D2BD", "kind": "all", "path": None}
    else:
        proj = con.execute("SELECT * FROM project WHERE id=?", (project_id,)).fetchone()
        if not proj:
            return {"error": f"未知项目 {project_id}"}

    days = []
    cur = dfrom
    while cur <= dto:
        days.append(
            {
                "date": cur.isoformat(),
                "md": f"{cur.month}/{cur.day}",
                "weekday": WEEKDAY_CN[cur.weekday()],
                "weekend": cur.weekday() >= 5,
                "is_monday": cur.weekday() == 0,
            }
        )
        cur += dt.timedelta(days=1)

    pmeta = {r["id"]: (r["name"], r["path"]) for r in con.execute("SELECT id, name, path FROM project")}
    pnames = {k: v[0] for k, v in pmeta.items()}
    scope_sql, scope_args = _scope("", project_id, harness)
    rows = con.execute(
        f"""SELECT * FROM work_unit
           WHERE {scope_sql} AND start_day<=? AND end_day>=?
           ORDER BY start_day ASC, end_day ASC""",
        (*scope_args, date_to, date_from),
    ).fetchall()

    units = []
    for r in rows:
        active = json.loads(r["active_days"] or "[]")
        segs = _segs(active, dfrom, dto)
        if not segs:
            continue
        det = _unit_detail(con, r["id"], pmeta.get(r["project_id"], (None, None))[1])
        units.append(
            {
                "id": r["id"],
                "title": r["title"],
                "kind": r["kind"],
                "start_day": r["start_day"],
                "end_day": r["end_day"],
                "active": active,
                "segs": segs,
                "span_days": r["span_days"],
                "max_streak": r["max_streak"],
                "file_count": r["file_count"],
                "additions": r["additions"],
                "deletions": r["deletions"],
                "design": r["file_count"] == 0,
                "masked": r["masked"],
                "group_id": r["group_id"] if "group_id" in r.keys() else None,
                "summary": r["summary"] if "summary" in r.keys() else None,
                "detail": _detail_json(r),
                "dirs": det["dirs"],
                "files": det["files"],
                "project": pnames.get(r["project_id"], r["project_id"]),
            }
        )

    day_counter: dict[str, int] = {}
    for u in units:
        for a in u["active"]:
            if date_from <= a <= date_to:
                day_counter[a] = day_counter.get(a, 0) + 1
    top_days = sorted(day_counter.items(), key=lambda kv: (-kv[1], kv[0]))[:2]

    # ---- 分组：相似工作单元合并，前端默认折叠 ----
    from . import group as group_mod

    group_mod.ensure_tables(con)
    gsql, gargs = _scope("w", project_id, harness)
    gids = {
        r["id"]: r["group_id"]
        for r in con.execute(
            f"SELECT w.id, m.group_id FROM work_unit w LEFT JOIN unit_group_map m ON m.unit_id=w.id"
            f" WHERE {gsql}",
            tuple(gargs),
        )
    }
    for u in units:
        u["group_id"] = gids.get(u["id"])
    # 组表没有 harness 列：按项目范围取，成员为空的分组后面会被跳过
    gsc_sql, gsc_args = _scope("", project_id)
    grows = con.execute(
        f"""SELECT * FROM work_group
           WHERE {gsc_sql} AND start_day<=? AND end_day>=? ORDER BY start_day ASC""",
        (*gsc_args, date_to, date_from),
    ).fetchall()
    groups = []
    for g in grows:
        members = sorted(
            [u for u in units if gids.get(u["id"]) == g["id"]], key=lambda u: u["start_day"]
        )
        if not members:
            continue
        kinds = json.loads(g["kinds"] or "{}")
        win_start = min(m["start_day"] for m in members)
        win_end = max(m["end_day"] for m in members)
        groups.append(
            {
                "id": g["id"],
                "title": g["title"],
                "kind": max(kinds.items(), key=lambda kv: kv[1])[0] if kinds else "code",
                "unit_count": len(members),
                "unit_count_total": g["unit_count"],
                "start_day": win_start,
                "end_day": win_end,
                "segs": _segs(json.loads(g["active_days"] or "[]"), dfrom, dto),
                "file_count": sum(m["file_count"] for m in members),
                "additions": sum(m["additions"] for m in members),
                "deletions": sum(m["deletions"] for m in members),
                "design": all(u["design"] for u in members),
                "project": pnames.get(g["project_id"], g["project_id"]),
                "units": members,
            }
        )

    # ---- 日历热力图：近 12 周每日变更条数 ----
    heatmap = []
    hstart = dto - dt.timedelta(days=dto.weekday() + 7 * 11)
    hmap = {
        r["day"]: r["c"]
        for r in con.execute(
            f"""SELECT a.day AS day, COUNT(*) AS c
               FROM artifact a JOIN work_unit w ON w.id = a.work_unit_id
               WHERE {gsql} AND a.day >= ? GROUP BY a.day""",
            (*gargs, hstart.isoformat()),
        )
    }
    cur = hstart
    while cur <= dto:
        heatmap.append({"date": cur.isoformat(), "n": hmap.get(cur.isoformat(), 0)})
        cur += dt.timedelta(days=1)

    # ---- 每日工作量 + 时段分布 + 成就 ----
    daily = {}
    hours = [0] * 24
    for r in con.execute(
        f"""SELECT a.day AS day, COUNT(*) AS n, MIN(a.ts) AS mn, MAX(a.ts) AS mx,
                   COUNT(DISTINCT w.project_id) AS np
            FROM artifact a JOIN work_unit w ON w.id = a.work_unit_id
            WHERE {gsql} AND a.day >= ? AND a.day <= ? GROUP BY a.day""",
        (*gargs, date_from, date_to),
    ):
        mn = dt.datetime.fromtimestamp(r["mn"] / 1000)
        mx = dt.datetime.fromtimestamp(r["mx"] / 1000)
        daily[r["day"]] = {
            "n": r["n"],
            "first": round(mn.hour + mn.minute / 60, 2),
            "last": round(mx.hour + mx.minute / 60, 2),
            "span": round((r["mx"] - r["mn"]) / 3_600_000, 2),
            "projects": r["np"],
        }
    for r in con.execute(
        f"""SELECT a.ts AS ts FROM artifact a JOIN work_unit w ON w.id = a.work_unit_id
            WHERE {gsql} AND a.day >= ? AND a.day <= ?""",
        (*gargs, date_from, date_to),
    ):
        hours[dt.datetime.fromtimestamp(r["ts"] / 1000).hour] += 1

    # 连续有记录的天数（窗口内）
    ordered = sorted(daily)
    run = 0
    for i, day in enumerate(ordered):
        run = run + 1 if i and (dt.date.fromisoformat(day) - dt.date.fromisoformat(ordered[i - 1])).days == 1 else 1
        daily[day]["streak"] = run

    achievements = {}
    for day, d in daily.items():
        badges = []
        if d["first"] < 8:
            badges.append(("sunrise", "🌅", "天没亮就开工", f"{fmt_h(d['first'])} 开始"))
        elif d["first"] < 10:
            badges.append(("early", "☀️", "早开工", f"{fmt_h(d['first'])} 就开始了"))
        if d["last"] >= 22:
            badges.append(("night", "🌙", "夜战", f"干到 {fmt_h(d['last'])}"))
        elif d["last"] >= 18.5:
            badges.append(("late", "🌇", "晚收工", f"干到 {fmt_h(d['last'])}"))
        if d["span"] >= 9:
            badges.append(("longhaul", "⏳", "超长待机", f"连续 {d['span']:.1f} 小时"))
        elif d["span"] >= 6:
            badges.append(("marathon", "🔥", "马拉松", f"连续 {d['span']:.1f} 小时"))
        if d["n"] >= 250:
            badges.append(("burst", "💯", "爆发日", f"当天 {d['n']} 处改动"))
        elif d["n"] >= 100:
            badges.append(("heavy", "🚀", "高产", f"当天 {d['n']} 处改动"))
        if dt.date.fromisoformat(day).weekday() >= 5 and d["n"] >= 10:
            badges.append(("weekend", "🎯", "周末战士", f"周末还改了 {d['n']} 处"))
        if d["projects"] >= 3:
            badges.append(("multi", "🎪", "多线并进", f"当天动了 {d['projects']} 个项目"))
        if d["streak"] >= 7:
            badges.append(("week7", "🏆", "连轴七天", f"连续第 {d['streak']} 天"))
        if badges:
            achievements[day] = [
                {"key": k, "icon": ic, "label": lb, "detail": dt_}
                for k, ic, lb, dt_ in badges
            ]

    today = dt.date.today()
    cur = dfrom
    while cur <= dto:
        ds = cur.isoformat()
        if cur.weekday() < 5 and ds not in daily and cur <= today and (today - cur).days <= 14:
            achievements.setdefault(ds, []).append(
                {"key": "idle", "icon": "🐟", "label": "摸鱼", "detail": "这天一行代码都没动"}
            )
        cur += dt.timedelta(days=1)

    # ---- 周 × 类型堆叠：近 8 周 ----
    wstart = dto - dt.timedelta(days=dto.weekday() + 7 * 7)
    buckets: dict[str, dict[str, int]] = {}
    for r in con.execute(
        f"SELECT kind, start_day FROM work_unit WHERE {scope_sql} AND start_day>=?",
        (*scope_args, wstart.isoformat()),
    ):
        if not r["start_day"]:
            continue
        ws = (_d(r["start_day"]) - dt.timedelta(days=_d(r["start_day"]).weekday())).isoformat()
        buckets.setdefault(ws, {})
        buckets[ws][r["kind"]] = buckets[ws].get(r["kind"], 0) + 1
    weekly = []
    cur = wstart
    while cur <= dto:
        weekly.append(
            {"week": cur.isoformat(), "md": f"{cur.month}/{cur.day}", "kinds": buckets.get(cur.isoformat(), {})}
        )
        cur += dt.timedelta(days=7)

    with_output = [u for u in units if not u["design"]]
    active_days = len(day_counter)
    summary = {
        "project": proj["name"],
        "from": date_from,
        "to": date_to,
        "unit_count": len(units),
        "output_count": len(with_output),
        "design_count": len(units) - len(with_output),
        "active_days": active_days,
        "total_days": len(days),
        "files": sum(u["file_count"] for u in units),
        "additions": sum(u["additions"] for u in units),
        "deletions": sum(u["deletions"] for u in units),
        "top_days": [{"date": d, "n": n} for d, n in top_days],
        "hours": round(sum(v["span"] for v in daily.values()), 1),
        "lines": sum(u["additions"] + u["deletions"] for u in units),
        "last_scan": (
            con.execute("SELECT value FROM meta WHERE key='last_scan_at'").fetchone() or [None]
        )[0],
    }
    kinds: dict[str, int] = {}
    for u in units:
        kinds[u["kind"]] = kinds.get(u["kind"], 0) + 1
    summary["kinds"] = kinds

    return {
        "project": {"id": proj["id"], "name": proj["name"], "color": proj["color"], "kind": proj["kind"]},
        "range": {"from": date_from, "to": date_to},
        "days": days,
        "units": units,
        "groups": groups,
        "heatmap": heatmap,
        "weekly": weekly,
        "daily": daily,
        "hours": hours,
        "achievements": achievements,
        "summary": summary,
    }


def list_harnesses(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT COALESCE(harness,'workbuddy') AS harness, COUNT(*) AS units"
        " FROM work_unit GROUP BY 1 ORDER BY units DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def list_projects(con: sqlite3.Connection, harness: str | None = None) -> list[dict]:
    """项目清单。给了 harness 就只列出来源下有数据的项目，避免选完空转。"""
    where = "WHERE p.id != ?"
    params: list = [MISC_ID]
    if harness:
        where += " AND w.harness = ?"
        params.append(harness)
    rows = con.execute(
        f"""SELECT p.id, p.name, p.color, COUNT(w.id) AS units
           FROM project p LEFT JOIN work_unit w ON w.project_id=p.id
           {where}
           GROUP BY p.id HAVING units > 0 ORDER BY units DESC""",
        params,
    ).fetchall()
    items = [dict(r) for r in rows]
    total = sum(x["units"] for x in items)
    return [{"id": ALL_ID, "name": "全部项目", "color": "#D8D2BD", "units": total}] + items


class Handler(BaseHTTPRequestHandler):
    server_version = "worklog/0.1"

    def log_message(self, fmt, *args):  # 静默
        return

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/projects":
            h = (qs.get("harness") or [None])[0] or None
            con = db.connect()
            try:
                return self._json({"projects": list_projects(con, h)})
            finally:
                con.close()

        if path == "/api/harnesses":
            con = db.connect()
            try:
                return self._json({"harnesses": list_harnesses(con)})
            finally:
                con.close()

        if path == "/api/project":
            project_id = (qs.get("project") or [ALL_ID])[0]
            harness = (qs.get("harness") or [None])[0] or None
            days = int((qs.get("days") or ["14"])[0])
            date_from = (qs.get("from") or [""])[0]
            date_to = (qs.get("to") or [""])[0]
            if not date_from or not date_to:
                date_from, date_to = _default_range(days)
            con = db.connect()
            try:
                return self._json(build_payload(con, project_id, date_from, date_to, harness))
            finally:
                con.close()

        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)


def serve(host: str = "127.0.0.1", port: int = 8720) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"worklog 已启动 → http://{host}:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
