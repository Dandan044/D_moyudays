"""Exercise the documented agent workflow with a fresh checkout and synthetic logs."""

import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PortableWorkflowTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.repo = base / "工作记录 checkout"
        self.repo.mkdir()
        shutil.copy2(ROOT / "run.py", self.repo)
        for folder in ("worklog", "web"):
            shutil.copytree(ROOT / folder, self.repo / folder, ignore=shutil.ignore_patterns("__pycache__"))
        self.home = base / "test-home"
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home), PYTHONIOENCODING="utf-8")
        self.start = dt.datetime.combine(dt.date.today(), dt.time(8, 15))

    def command(self, *args, input_data=None, status=0):
        result = subprocess.run([sys.executable, "-X", "utf8", *args], cwd=self.repo, env=self.env,
                                input=json.dumps(input_data) if input_data is not None else None,
                                capture_output=True, encoding="utf-8", timeout=45)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return result.stdout

    def cli(self, *args, **kwargs):
        return self.command("-m", "worklog.cli", *args, **kwargs)

    def call(self, tool, params):
        return json.loads(self.cli("call", "worklog_" + tool, input_data=params))

    def snapshot(self):
        html = (self.repo / "data" / "工作记录.html").read_text(encoding="utf-8")
        embedded = re.search(r'<script type="application/json" id="worklog-snapshot">(.*?)</script>', html, re.S)
        self.assertIsNotNone(embedded)
        self.assertNotIn('src="/app.js"', html)
        self.assertNotIn('href="/app.css"', html)
        return json.loads(embedded[1])["sources"]

    def test_prepare_curate_export_and_repeat(self):
        self.command("run.py", "--prepare-only")
        self.assertEqual(json.loads(self.cli("audit", status=1))["total"], 0)
        destination = ("export", "--output", "data/工作记录.html")
        self.assertNotIn("是否创建", self.cli(*destination))
        self.assertEqual(self.snapshot()[""]["views"]["all"]["7"]["units"], [])

        project = self.home / "projects" / "atlas"
        (project / ".git").mkdir(parents=True)
        logs = self.home / ".claude" / "projects" / "atlas"
        logs.mkdir(parents=True)
        records = [{"type": "user", "timestamp": self.start.isoformat(), "cwd": str(project),
                    "message": {"content": "Add import checks and improve the help page"}}]
        for i, path in enumerate(("import.py", "help.md")):
            when = self.start + dt.timedelta(hours=i * 2)
            records.append({"type": "assistant", "timestamp": when.isoformat(), "cwd": str(project), "message": {
                "content": [{"type": "tool_use", "name": "Write", "input": {"file_path": str(project / path),
                                                                           "content": "sample\n"}}]}})
        (logs / "session-a.jsonl").write_text("\n".join(map(json.dumps, records)), encoding="utf-8")
        self.command("run.py", "--prepare-only")
        payload = {"source": "fixture-agent", "sessions": [{"session_id": "fixture:discussion", "cwd": str(project),
                   "title": "Discuss import formats", "events": [
                       {"ts": int(self.start.timestamp() * 1000), "action": "activity"}]}]}
        self.cli("ingest", input_data=payload)
        blocks = self.call("list_blocks", {"session_id": "session-a"})["blocks"]
        self.assertEqual(len(blocks), 2)
        split = self.call("apply_split", {"session_id": "session-a", "segments": [
            {"title": title, "block_ids": [block["block_id"]]}
            for title, block in zip(("Validate imports", "Explain the import command"), blocks)]})
        self.assertEqual(len(split["units"]), 2)
        units = self.call("list_units", {"project": "atlas"})["units"]
        self.assertEqual(len(units), 3)
        ids = [u["id"] for u in units]
        self.assertIn("fixture:discussion", ids)
        self.call("apply_groups", {"project": "atlas", "groups": [{"title": "Import workflow", "unit_ids": ids}]})
        self.call("set_detail", {"items": [{
            "unit_id": u["id"], "headline": "Reviewed the evidence for " + u["title"],
            "sections": [{"title": "Source", "items": ["Observed in local session " + u["id"]]},
                         {"title": "Scope", "items": ["Changed files recorded: " + str(u["files"])]}],
        } for u in units]})
        self.assertEqual(json.loads(self.cli("audit"))["complete"], 3)
        self.assertEqual(self.cli(*destination).count("是否创建"), 2)
        self.command("run.py", "--prepare-only")
        self.cli("ingest", input_data=payload)
        self.assertEqual(json.loads(self.cli("audit"))["complete"], 3)
        self.assertNotIn("是否创建", self.cli(*destination))
        sources = self.snapshot()
        self.assertEqual(set(sources), {"", "fixture-agent", "claude-code"})
        view = sources[""]["views"]["atlas"]["7"]
        self.assertEqual(len(view["days"]), 7)
        self.assertEqual(len(view["groups"]), 1)
        self.assertEqual(view["groups"][0]["unit_count"], 3)
        self.assertEqual(sum(u["file_count"] for u in view["units"]), 2)
        discussion = sources["fixture-agent"]["views"]["atlas"]["7"]
        self.assertEqual(discussion["units"][0]["kind"], "design")
        self.assertFalse(discussion["daily"])
        if browser := os.environ.get("WORKLOG_TEST_CHROME"):
            report = self.repo / "data" / "工作记录.html"
            rendered = subprocess.run([browser, "--headless=new", "--disable-background-networking",
                                       "--no-first-run", "--user-data-dir=" + str(self.home / "browser"),
                                       "--virtual-time-budget=3000", "--dump-dom", report.as_uri()],
                                      capture_output=True, encoding="utf-8", errors="replace", timeout=45)
            self.assertEqual(rendered.returncode, 0, rendered.stderr[-1000:])
            dom = rendered.stdout.split('<script type="application/json"')[0]
            self.assertRegex(dom, r'<button\b[^>]*data-days="7"[^>]*aria-pressed="true"')
            self.assertRegex(dom, r'<g\b[^>]*data-kind="group"')
            self.assertRegex(dom, r'<rect\b[^>]*class="bar-rect')
            self.assertIn("Import workflow", dom)
