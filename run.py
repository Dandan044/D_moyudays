#!/usr/bin/env python3
"""一键跑起来：发现项目（首次）→ 扫描 → 起服务 → 开浏览器。

不需要任何第三方依赖，也不需要预先配置。
    python run.py
"""

import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from worklog import api, db, init_project, scan  # noqa: E402

PORT = 8720
URL = f"http://127.0.0.1:{PORT}/"


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    wb_home = Path.home() / ".workbuddy"
    if not (wb_home / "workbuddy.db").exists():
        print(f"找不到 workbuddy 数据目录：{wb_home}")
        print("如果你把它放在别处，先跑：python -m worklog.cli init --workbuddy <路径> --force")
        raise SystemExit(1)

    if not db.CONFIG_PATH.exists():
        print("首次运行，正在自动发现本机项目……")
        res = init_project.write_config(wb_home)
        print(f"  发现 {res.get('projects', 0)} 个项目")

    scan.scan()

    threading.Timer(1.2, lambda: webbrowser.open(URL)).start()
    print(f"\n打开 {URL}   （Ctrl+C 停止）\n")
    api.serve("127.0.0.1", PORT)


if __name__ == "__main__":
    main()
