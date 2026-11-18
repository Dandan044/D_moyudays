"""用网页本身的模板和数据接口生成独立 HTML。"""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from . import api, db, review


def write_snapshot(path: Path):
    con = db.connect()
    try:
        con.execute("BEGIN")
        coverage = review.audit(con)
        harnesses = api.list_harnesses(con)
        sources = {}
        for harness in [None] + [item["harness"] for item in harnesses]:
            projects = api.list_projects(con, harness)
            views = {}
            for project in projects:
                pid = project["id"]
                views[pid] = {}
                for days in (7, 14, 28, 0):
                    start, end = api.report_range(con, pid, harness, days)
                    views[pid][days] = api.build_payload(con, pid, start, end, harness)
            sources[harness or ""] = {"projects": projects, "views": views}
    finally:
        con.close()
    data = json.dumps({"harnesses": harnesses, "sources": sources}, ensure_ascii=False,
                      separators=(",", ":")).replace("<", "\\u003c")
    template = (api.WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (api.WEB_DIR / "app.css").read_text(encoding="utf-8")
    js = (api.WEB_DIR / "app.js").read_text(encoding="utf-8")
    html = template.replace('<link rel="stylesheet" href="/app.css">', f"<style>{css}</style>")
    html = html.replace('<script src="/app.js"></script>',
                        f'<script type="application/json" id="worklog-snapshot">{data}</script>\n<script>{js}</script>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        tmp_path.write_text(html, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return coverage
