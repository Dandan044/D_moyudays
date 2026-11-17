"""worklog 命令行：scan / report / serve。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from . import api, db, scan as scan_mod

def _range(days: int, date_from: str | None, date_to: str | None) -> tuple[str, str]:
    if date_from and date_to:
        return date_from, date_to
    return api._default_range(days)


def cmd_init(args) -> None:
    from . import init_project

    wb = db.load_config().get("workbuddy_home") if db.CONFIG_PATH.exists() else None
    wb_home = args.workbuddy or wb or str(db.pathlib.Path.home() / ".workbuddy")
    res = init_project.write_config(db.pathlib.Path(wb_home), force=args.force)
    if res.get("skipped"):
        print(f"config 已存在（{res['projects']} 个项目），跳过。要重建加 --force")
    else:
        print(f"发现 {res['projects']} 个项目 → {res['path']}")
        print(f"  会话 {res['sessions']} 个 · git 仓库 {res['repos']} 个 · 普通目录 {res['loose']} 个")


def cmd_probe(args) -> None:
    from . import probe as probe_mod

    print(json.dumps(probe_mod.probe(args.path), ensure_ascii=False, indent=1))


def cmd_ingest(args) -> None:
    from . import harness

    if args.file:
        payload = json.loads(open(args.file, encoding="utf-8").read())
    else:
        payload = json.load(sys.stdin)
    res = harness.ingest(payload)
    print(f"导入 {res['source']}：{res['sessions']} 个会话 / {res['events']} 条事件")
    scan_mod.scan(verbose=True)


def cmd_scan(args) -> None:
    scan_mod.scan(verbose=True)


def cmd_report(args) -> None:
    con = db.connect()
    date_from, date_to = _range(args.days, args.from_, args.to)
    payload = api.build_payload(con, args.project, date_from, date_to)
    con.close()
    if "error" in payload:
        raise SystemExit(payload["error"])

    s = payload["summary"]
    kinds = " / ".join(f"{k} {v}" for k, v in sorted(s["kinds"].items()))
    print(f"\n{s['project']}  {s['from']} → {s['to']}")
    print(
        f"工作单元 {s['unit_count']}（有产出 {s['output_count']} / 纯讨论 {s['design_count']}）"
        f"· 活跃 {s['active_days']}/{s['total_days']} 天 · 文件 {s['files']} · +{s['additions']}/-{s['deletions']}"
    )
    print(f"类型分布: {kinds}")
    print("-" * 96)
    print(f"{'起止':<24}{'活跃':>4}{'连续':>4}{'文件':>5}{'类型':>8}  标题")
    for u in payload["units"]:
        span = f"{u['start_day'][5:]}~{u['end_day'][5:]}"
        print(
            f"{span:<24}{len(u['active']):>4}{u['max_streak']:>4}{u['file_count']:>5}"
            f"{u['kind']:>8}  {u['title'][:38]}"
        )
    print()


def cmd_serve(args) -> None:
    api.serve(args.host, args.port)


def cmd_mcp(args) -> None:
    from . import mcp_stdio

    mcp_stdio.main()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="worklog", description="本地工作记录可视化")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="自动发现本机项目，生成 config/projects.json")
    p_init.add_argument("--force", action="store_true", help="覆盖已有配置")
    p_init.add_argument("--workbuddy", default=None, help="workbuddy 数据目录，默认 ~/.workbuddy")
    p_init.set_defaults(func=cmd_init)

    p_probe = sub.add_parser("probe", help="探索目录里有什么（给模型判断用，不预设 harness 名单）")
    p_probe.add_argument("path", nargs="?", default=None, help="指定目录；省略则扫家目录与 AppData")
    p_probe.set_defaults(func=cmd_probe)

    p_ing = sub.add_parser("ingest", help="导入其它 harness 的会话事件（JSON）")
    p_ing.add_argument("--file", default=None, help="JSON 文件；省略则从 stdin 读")
    p_ing.set_defaults(func=cmd_ingest)

    p_scan = sub.add_parser("scan", help="扫描 workbuddy 本地记录并重建派生层")
    p_scan.set_defaults(func=cmd_scan)

    p_rep = sub.add_parser("report", help="终端输出某项目一段时间的工作记录")
    p_rep.add_argument("--project", default="LLMbox")
    p_rep.add_argument("--days", type=int, default=14)
    p_rep.add_argument("--from", dest="from_", default=None)
    p_rep.add_argument("--to", dest="to", default=None)
    p_rep.set_defaults(func=cmd_report)

    p_serve = sub.add_parser("serve", help="启动本地网页")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8720)
    p_serve.set_defaults(func=cmd_serve)

    p_mcp = sub.add_parser("mcp", help="以 stdio MCP 服务运行（供 harness 调用）")
    p_mcp.set_defaults(func=cmd_mcp)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
