#!/usr/bin/env python3
"""一键跑起来：探测所有 harness → 自动导入 → 发现项目 → 扫描 → 起服务 → 开浏览器。

不假设任何一家 harness 一定存在。workbuddy 只是其中之一，
Claude Code / Codex / Cursor / Trae … 走内置解析器，解析不了的由调用它的模型补。

    python run.py
"""

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from worklog import api, db, harness, init_project, review, scan, sources  # noqa: E402
from worklog.delivery import first_delivery_questions

PORT = 8720
URL = f"http://127.0.0.1:{PORT}/"


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    home = Path.home()
    parser = argparse.ArgumentParser(description="导入本机工作记录并准备整理")
    parser.add_argument("--prepare-only", action="store_true", help="完成扫描后退出，供 agent 继续整理和导出")
    args = parser.parse_args()

    # 1. 先把能自动解析的 harness 全收进来（顺序无关，谁有数据算谁）
    print("扫描本机 harness……")
    payloads = sources.autoload(home)
    if payloads:
        for name, payload in payloads.items():
            res = harness.ingest(payload)
            if res.get("rejected"):
                print(f"  {name:<14} ✗ 解析质量不合格，已跳过")
                for prob in res.get("problems", []):
                    print(f"      · {prob}")
                print(f"      → 需要你读样本重写解析脚本，再 ingest（SKILL 第三步）")
            else:
                print(f"  {name:<14} {res['sessions']} 个会话 / {res['events']} 条事件")
    else:
        print("  没有发现可自动解析的 harness 记录")

    # 2. 项目发现（workbuddy 会话 + 外部导入的会话一起看）
    wb_home = db.load_config().get("workbuddy_home") if db.CONFIG_PATH.exists() else None
    res = init_project.write_config(Path(wb_home or home / ".workbuddy"), refresh=True)
    print(f"  已配置 {res['projects']} 个项目")

    # 3. 统一扫描（workbuddy 有就一起算，没有也不影响）
    scan.scan()

    # 3.5 汇报「还差什么」——机械部分到此为止
    con = db.connect()
    pending = con.execute(
        "SELECT COUNT(DISTINCT session_id) FROM work_unit"
        " WHERE session_id NOT IN (SELECT session_id FROM session_split)"
    ).fetchone()[0]
    coverage = review.audit(con)
    con.close()

    print(f"  标题、分组及详情检查通过 {coverage['complete']}/{coverage['total']} 个工作单元")
    print(f"  {pending} 个会话沿用整段，是否需要切分请依据内容判断")
    print("  python -m worklog.cli audit 可查看具体待整理项")
    if coverage["pending"] or not coverage["total"]:
        print("  继续整理：probe 检查来源 → 切分任务 → 归组 → 填写卡片详情。参见 SKILL.md。")
    if args.prepare_only:
        return

    threading.Timer(1.2, lambda: webbrowser.open(URL)).start()
    print(f"\n打开 {URL}   （Ctrl+C 停止）\n")

    def on_ready():
        ready_con = db.connect()
        try:
            for question in first_delivery_questions(ready_con, coverage):
                print(question)
        finally:
            ready_con.close()

    api.serve("127.0.0.1", PORT, on_ready=on_ready)


if __name__ == "__main__":
    main()
