#!/usr/bin/env python3
"""一键跑起来：探测所有 harness → 自动导入 → 发现项目 → 扫描 → 起服务 → 开浏览器。

不假设任何一家 harness 一定存在。workbuddy 只是其中之一，
Claude Code / Codex / Cursor / Trae … 走内置解析器，解析不了的由调用它的模型补。

    python run.py
"""

import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from worklog import api, db, harness, init_project, scan, sources  # noqa: E402

PORT = 8720
URL = f"http://127.0.0.1:{PORT}/"


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    home = Path.home()

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
    if not db.CONFIG_PATH.exists():
        res = init_project.write_config(home / ".workbuddy")
        print(f"  发现 {res.get('projects', 0)} 个项目")

    # 3. 统一扫描（workbuddy 有就一起算，没有也不影响）
    scan.scan()

    # 3.5 汇报「还差什么」——机械部分到此为止
    con = db.connect()
    pending = con.execute(
        "SELECT COUNT(DISTINCT session_id) FROM work_unit"
        " WHERE session_id NOT IN (SELECT session_id FROM session_split)"
    ).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM work_unit").fetchone()[0]
    con.close()

    threading.Timer(1.2, lambda: webbrowser.open(URL)).start()
    print(f"\n打开 {URL}   （Ctrl+C 停止）\n")
    print("—— 以下是机械扫描的结果，可读性还差得远 ——")
    print(f"  {total} 个工作单元，其中 {pending} 个会话还没切分（现在是一个会话算一条）")
    print("  要继续，你得自己做这几件事（脚本替不了）：")
    print("    1) python -m worklog.cli probe     看本机还有哪些 harness 没导进来")
    print("    2) 没覆盖的格式：读样本 → 现场写转换脚本 → ingest")
    print("    3) 切段：worklog_list_sessions → list_blocks → apply_split")
    print("    4) 归组：worklog_list_units → apply_groups")
    print("    5) 写详情：worklog_set_detail\n")
    api.serve("127.0.0.1", PORT)


if __name__ == "__main__":
    main()
