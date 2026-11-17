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
            print(f"  {name:<14} {res['sessions']} 个会话 / {res['events']} 条事件")
    else:
        print("  没有发现可自动解析的 harness 记录")

    # 2. 项目发现（workbuddy 会话 + 外部导入的会话一起看）
    if not db.CONFIG_PATH.exists():
        res = init_project.write_config(home / ".workbuddy")
        print(f"  发现 {res.get('projects', 0)} 个项目")

    # 3. 统一扫描（workbuddy 有就一起算，没有也不影响）
    scan.scan()

    threading.Timer(1.2, lambda: webbrowser.open(URL)).start()
    print(f"\n打开 {URL}   （Ctrl+C 停止）")
    print("如果页面缺了你常用工具的数据，让它跑：python -m worklog.cli probe 再手工 ingest\n")
    api.serve("127.0.0.1", PORT)


if __name__ == "__main__":
    main()
