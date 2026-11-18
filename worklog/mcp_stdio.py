"""MCP 服务（stdio / JSON-RPC 2.0）。零依赖，供任意 harness 调用。

分组不做规则判定：由 LLM 通过 list_units 拿到候选，自己判断相似性，
再用 apply_groups 写回。服务端只负责存取与聚合。
"""

from __future__ import annotations

import datetime as dt
import json
import sys

from . import api, db, group, review

PROTOCOL = "2024-11-05"
SERVER = {"name": "worklog", "version": "0.1.0"}

TOOLS = [
    {"name": "worklog_audit", "description": "检查所有项目的标题、主题归属与卡片详情，返回待处理 ID。",
     "inputSchema": {"type": "object", "properties": {}}},
    {
        "name": "worklog_list_units",
        "description": (
            "列出某项目的工作单元（一个会话 = 一个单元），含标题、时间、类型、文件数与 top_files，"
            "并标注已有 group_id。用于让 LLM 判断哪些单元属于同一件事。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "当前机器上的项目 ID"},
                "since": {"type": "string", "description": "只返回 end_day 不早于该日期的单元，YYYY-MM-DD"},
                "only_ungrouped": {"type": "boolean", "description": "只返回尚未分组的单元"},
            },
            "required": ["project"],
        },
    },
    {
        "name": "worklog_list_groups",
        "description": "列出现有分组及其成员 unit_ids，用于增量调整而不是每次重排。",
        "inputSchema": {
            "type": "object",
            "properties": {"project": {"type": "string"}},
            "required": ["project"],
        },
    },
    {
        "name": "worklog_apply_groups",
        "description": (
            "写回分组结果。每个 group 给 title 与 unit_ids；同一 unit 只能属于一个组，"
            "重复提交会覆盖其旧归属。未列出的单元保持未分组。返回落库统计。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "这一组在干什么，20 字内"},
                            "unit_ids": {"type": "array", "items": {"type": "string"}},
                            "note": {"type": "string", "description": "可选：为什么归为一组"},
                        },
                        "required": ["title", "unit_ids"],
                    },
                },
            },
            "required": ["project", "groups"],
        },
    },
    {
        "name": "worklog_clear_groups",
        "description": "清空某项目的分组（或指定 group_ids），回到未分组状态。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "group_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["project"],
        },
    },
    {
        "name": "worklog_summary",
        "description": "取一段时间内某项目的汇总数据（单位数、产出、类型分布、活跃日、分组情况），用于生成结论。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "days": {"type": "integer", "description": "回看天数，默认 14"},
            },
            "required": ["project"],
        },
    },
    {
        "name": "worklog_set_notes",
        "description": (
            "给工作单元写入摘要（1-2 句说明这件事做成了什么），显示在网页卡片上。"
            "传 unit_id 与 summary；一次可写多条。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "notes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "unit_id": {"type": "string"},
                            "summary": {"type": "string", "description": "20-80 字，说清做成了什么"},
                        },
                        "required": ["unit_id", "summary"],
                    },
                }
            },
            "required": ["notes"],
        },
    },
    {
        "name": "worklog_set_detail",
        "description": (
            "给工作单元写「总分」结构的详情，显示在网页卡片里。一次可写多条。\n\n"
            "写作对象是**几天后已经忘光细节的自己**，不是当时的同事。硬性要求：\n"
            "1) headline：这件事是干什么的 + 为什么做，60 字内，必须能脱离上下文读懂；\n"
            "2) sections 建议顺序：为什么做 / 做了什么 / 现在的状态 / 遗留（可选）；\n"
            "3) 「做了什么」用结果语言，不要罗列文件名；确需提内部代号（脚本名、页面名、模块名）时，"
            "当场用一句话解释它是干什么的，例如「make_labels.py —— 给词表每条打错误类型标签的脚本」；\n"
            "4) 不要写「优化代码」「处理问题」「继续开发」这类空话；没有素材支撑的动机不要编。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "unit_id": {"type": "string"},
                            "headline": {"type": "string", "description": "一句话结论，30-70 字"},
                            "title": {"type": "string", "description": "改写后的任务名称，写出对象和动作"},
                            "sections": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "items": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["title", "items"],
                                },
                            },
                        },
                        "required": ["unit_id", "headline", "sections"],
                    },
                }
            },
            "required": ["items"],
        },
    },
    {
        "name": "worklog_list_sessions",
        "description": (
            "列出需要切分任务的会话（一个会话可能横跨多天做多件事）。"
            "返回每个会话的标题、时间跨度、活动块数量与涉及文件，供判断要不要拆。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "since": {"type": "string", "description": "只看该日期之后有活动的会话"},
                "unsplit_only": {"type": "boolean", "description": "只返回尚未被 LLM 切分过的会话"},
                "min_blocks": {"type": "integer", "description": "只返回活动块数不少于该值的会话，默认 1"},
            },
            "required": ["project"],
        },
    },
    {
        "name": "worklog_list_blocks",
        "description": (
            "列出一个会话的所有活动块（30 分钟无动作即断开）。"
            "每块含 block_id、日期、文件、增删行；把块按任务归并后交给 worklog_apply_split。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    },
    {
        "name": "worklog_apply_split",
        "description": (
            "写回某个会话的任务切分：segments = [{title, block_ids}]。"
            "写入后自动重扫，该会话会按新的段生成工作单元；块没被任何段覆盖时归到最后一个段。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "这一段在做什么，20 字内"},
                            "block_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["title", "block_ids"],
                    },
                },
            },
            "required": ["session_id", "segments"],
        },
    },
    {
        "name": "worklog_scan",
        "description": "重新扫描 workbuddy 本地记录并重建派生层（幂等）。新增工作后调用一次。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, args: dict) -> dict:
    con = db.connect()
    try:
        if name == "worklog_audit":
            return review.audit(con)
        if name == "worklog_list_units":
            units = group.list_units(
                con,
                args["project"],
                since=args.get("since"),
                only_ungrouped=bool(args.get("only_ungrouped")),
            )
            return {"project": args["project"], "count": len(units), "units": units}

        if name == "worklog_list_groups":
            return {"project": args["project"], "groups": group.list_groups(con, args["project"])}

        if name == "worklog_apply_groups":
            with con:
                return group.apply_groups(con, args["project"], args.get("groups") or [])

        if name == "worklog_clear_groups":
            with con:
                n = group.clear(con, args["project"], args.get("group_ids"))
            return {"cleared_units": n}

        if name == "worklog_summary":
            date_from, date_to = api._default_range(int(args.get("days") or 14))
            payload = api.build_payload(con, args["project"], date_from, date_to)
            if "error" in payload:
                return payload
            groups = group.list_groups(con, args["project"])
            return {
                "summary": payload["summary"],
                "groups": [
                    {"title": g["title"], "unit_count": g["unit_count"], "start_day": g["start_day"]}
                    for g in groups
                ],
                "ungrouped_units": [
                    {"id": u["id"], "title": u["title"], "start_day": u["start_day"]}
                    for u in payload["units"]
                    if not u.get("group_id")
                ][:40],
            }

        if name == "worklog_set_detail":
            items = args.get("items") or []
            ok = 0
            with con:
                db.ensure_columns(con)
                for it in items:
                    row = con.execute("SELECT title, masked, detail FROM work_unit WHERE id=?", (it.get("unit_id"),)).fetchone()
                    if row is None:
                        raise ValueError(f"未知任务 {it.get('unit_id')}")
                    title = row["title"] if row["masked"] else it.get("title", row["title"])
                    if not review.task_title(title):
                        raise ValueError(f"{it['unit_id']} 需要可读的任务名称")
                    payload = {
                        "headline": it.get("headline") or "",
                        "sections": it.get("sections") or [],
                    }
                    issues = review.detail_issues(title, payload)
                    if issues:
                        raise ValueError(f"{it['unit_id']} " + "、".join(issues))
                    if it.get("title") or review.parse_detail(row["detail"]).get("title"):
                        payload["title"] = title
                    cur = con.execute(
                        "UPDATE work_unit SET title=?, detail=?, summary=? WHERE id=?",
                        (title, json.dumps(payload, ensure_ascii=False), payload["headline"], it["unit_id"]),
                    )
                    ok += cur.rowcount
            return {"updated": ok, "requested": len(items)}

        if name == "worklog_set_notes":
            notes = args.get("notes") or []
            ok = 0
            with con:
                db.ensure_columns(con)
                for n in notes:
                    cur = con.execute(
                        "UPDATE work_unit SET summary=? WHERE id=?", (n.get("summary"), n.get("unit_id"))
                    )
                    ok += cur.rowcount
            return {"updated": ok, "requested": len(notes)}

        if name == "worklog_list_sessions":
            project = args["project"]
            since = args.get("since")
            sql = (
                "SELECT w.session_id AS sid, MIN(w.title) AS title, MIN(w.start_day) AS start_day,"
                " MAX(w.end_day) AS end_day, COUNT(*) AS segs,"
                " (SELECT COUNT(*) FROM session_block b WHERE b.session_id = w.session_id) AS blocks"
                " FROM work_unit w WHERE w.project_id = ?"
            )
            params = [project]
            if since:
                sql += " AND w.end_day >= ?"
                params.append(since)
            sql += " GROUP BY w.session_id HAVING blocks >= ? ORDER BY end_day DESC"
            params.append(int(args.get("min_blocks") or 1))
            split_ids = {r[0] for r in con.execute("SELECT session_id FROM session_split")}
            out = []
            for r in con.execute(sql, params):
                if args.get("unsplit_only") and r["sid"] in split_ids:
                    continue
                out.append(dict(r))
            return {"project": project, "count": len(out), "sessions": out}

        if name == "worklog_list_blocks":
            sid = args["session_id"]
            row = con.execute(
                "SELECT DISTINCT session_id FROM work_unit WHERE session_id LIKE ? LIMIT 1", (f"{sid}%",)
            ).fetchone()
            sid = row["session_id"] if row else sid
            title = con.execute(
                "SELECT title FROM work_unit WHERE session_id=? ORDER BY start_day LIMIT 1", (sid,)
            ).fetchone()
            rows = [
                dict(r)
                for r in con.execute(
                    "SELECT block_id, day, start_ts, end_ts, files, additions, deletions"
                    " FROM session_block WHERE session_id=? ORDER BY start_ts",
                    (sid,),
                )
            ]
            for r in rows:
                r["block_id"] = r["block_id"].split(":")[-1]
                try:
                    r["files"] = json.loads(r["files"] or "[]")
                except (json.JSONDecodeError, TypeError):
                    r["files"] = []
                r.pop("start_ts", None)
                r.pop("end_ts", None)
            return {"session_id": sid, "title": title["title"] if title else None, "blocks": rows}

        if name == "worklog_apply_split":
            sid = args["session_id"]
            row = con.execute(
                "SELECT DISTINCT session_id FROM work_unit WHERE session_id LIKE ? LIMIT 1", (f"{sid}%",)
            ).fetchone()
            sid = row["session_id"] if row else sid
            segs = args.get("segments") or []
            payload = json.dumps({"segments": segs}, ensure_ascii=False)
            with con:
                con.execute(
                    "INSERT INTO session_split(session_id,payload,source,updated_at) VALUES(?,?,?,?)"
                    " ON CONFLICT(session_id) DO UPDATE SET payload=excluded.payload,"
                    " source=excluded.source, updated_at=excluded.updated_at",
                    (sid, payload, "llm", dt.datetime.now().isoformat(timespec="seconds")),
                )
            from . import scan as scan_mod

            stats = scan_mod.scan(verbose=False)
            units = [
                dict(r)
                for r in con.execute(
                    "SELECT id, title, start_day, end_day, file_count FROM work_unit WHERE session_id=? ORDER BY start_day",
                    (sid,),
                )
            ]
            return {"segments": len(segs), "units": units, "rescan": stats}

        if name == "worklog_scan":
            from . import scan as scan_mod

            return scan_mod.scan(verbose=False)

        raise KeyError(f"unknown tool {name}")
    finally:
        con.close()


_call = call_tool  # 兼容已有本机整理脚本


def _handle(req: dict) -> dict | None:
    method = req.get("method")
    rid = req.get("id")

    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER,
        }
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        params = req.get("params") or {}
        try:
            data = call_tool(params.get("name"), params.get("arguments") or {})
            return {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=1)}],
                "isError": False,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True,
            }
    return {"__error__": -32601, "message": f"Method not found: {method}"}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = _handle(req)
        if result is None:
            continue
        if "__error__" in result:
            resp = {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": result["__error__"], "message": result["message"]},
            }
        else:
            resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": result}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
