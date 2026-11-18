import datetime as dt
import json
import sqlite3
import unittest

from worklog import api, db, group, review
from worklog.delivery import first_delivery_questions


class WorklogReviewTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.addCleanup(self.con.close)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(db.SCHEMA)
        db.ensure_columns(self.con)
        group.ensure_tables(self.con)
        self.con.execute("INSERT INTO project(id,name) VALUES ('misc','杂项')")
        self.con.execute("""
            INSERT INTO work_unit(id,title,project_id,kind,start_day,end_day,active_days)
            VALUES ('u','<codex_internal_context source="user_goal">','misc','design',
                    '2020-01-01','2020-01-01','["2020-01-01"]')
        """)

    def payload(self):
        return api.build_payload(self.con, "all", *api.report_range(self.con, "all", None, 0))

    def test_delivery_asks_once_only_after_completion(self):
        self.assertFalse(first_delivery_questions(self.con, {"total": 0, "pending": []}))
        self.assertFalse(first_delivery_questions(self.con, {"total": 2, "pending": ["u"]}))
        ready = {"total": 2, "pending": []}
        self.assertEqual(len(first_delivery_questions(self.con, ready)), 2)
        self.assertFalse(first_delivery_questions(self.con, ready))

    def test_legacy_prompt_is_visible_as_pending_without_losing_the_unit(self):
        unit, = self.payload()["units"]
        self.assertEqual(unit["title"], "待核实任务")
        self.assertTrue(unit["review_issues"])
        self.assertEqual(review.audit(self.con)["pending"][0]["unit_id"], "u")
        self.assertFalse(review.task_title("你是助教，负责解释课程材料。"))
        self.assertTrue(review.task_title("恢复中断的研究会话"))

    def test_partial_detail_survives_but_repeated_or_invalid_sections_fail(self):
        fact = {"title": "做了什么", "items": ["暂停时停止统计帧时间。"]}
        detail = {"headline": "让暂停不影响平均帧时间。", "sections": [fact]}
        self.assertEqual(review.display_detail(detail)["sections"], [fact])
        detail["sections"].append(dict(fact, title="结果"))
        self.assertTrue(review.detail_issues("修正性能面板", detail))
        detail["sections"].extend([None, {"title": "遗留", "items": "损毁待测"}])
        self.assertEqual(len(review.display_detail(detail)["sections"]), 2)

    def test_singleton_topic_counts_and_filters_cover_all_history(self):
        detail = {"headline": "定位暂停时帧数仍然增长的原因。", "sections": [
            {"title": "改动", "items": ["暂停时跳过帧时间采样。"]},
            {"title": "验证", "items": ["重开后计数从零开始。"]},
        ]}
        self.con.execute("UPDATE work_unit SET title=?,detail=?,harness='codex'",
                         ("修正性能面板", json.dumps(detail)))
        group.apply_groups(self.con, "misc", [{"title": "性能诊断", "unit_ids": ["u"]}])
        self.assertEqual(review.audit(self.con)["complete"], 1)
        topic, = self.payload()["groups"]
        self.assertEqual([member["id"] for member in topic["units"]], ["u"])
        self.assertEqual(api.list_projects(self.con, "codex")[0]["units"], 1)
        self.con.execute("UPDATE work_group SET project_id='elsewhere'")
        self.assertIsNone(self.payload()["units"][0]["group_id"])
        self.assertEqual(review.audit(self.con)["complete"], 0)

    def test_topic_order_uses_last_activity_including_legacy_artifacts(self):
        self.con.execute("UPDATE work_unit SET updated_ms=1577865600000 WHERE id='u'")
        self.con.execute("""INSERT INTO work_unit(id,title,project_id,kind,start_day,end_day,active_days)
            VALUES ('v','核对帧时间','misc','code','2019-12-30','2020-01-01','["2020-01-01"]')""")
        self.con.execute("INSERT INTO artifact(work_unit_id,path,day,ts) VALUES ('v','frame.js','2020-01-01',1577869200000)")
        group.apply_groups(self.con, "misc", [{"title": "性能诊断", "unit_ids": ["u", "v"]}])
        topic, = self.payload()["groups"]
        self.assertEqual([u["id"] for u in topic["units"]], ["v", "u"])
        self.assertEqual(topic["updated_ms"], 1577869200000)

    def test_hourly_workload_uses_local_timestamps_and_filtered_members(self):
        def millis(time):
            return int(dt.datetime.fromisoformat(time).timestamp() * 1000)

        self.con.execute("""UPDATE work_unit SET end_day='2020-01-03', harness='codex',
            active_days='["2020-01-01","2020-01-02","2020-01-03"]', updated_ms=?""",
            (millis("2020-01-02T09:10"),))
        self.con.execute("""INSERT INTO work_unit(id,title,project_id,kind,start_day,end_day,active_days,harness)
            VALUES ('v','核对帧时间','misc','code','2020-01-01','2020-01-01','["2020-01-01"]','other')""")
        self.con.executemany("INSERT INTO artifact(work_unit_id,path,day,ts) VALUES (?,?,?,?)", [
            ('u', 'frame.js', '2020-01-01', millis('2020-01-01T23:01')),
            ('u', 'frame.js', '2020-01-01', millis('2020-01-01T23:52')),
            ('u', 'other/frame.js', '2020-01-01', millis('2020-01-01T23:59')),
            ('u', 'frame.js', '2020-01-02', millis('2020-01-02T00:00')),
            ('u', 'older.js', '2020-01-03', None),
        ])
        group.apply_groups(self.con, "misc", [{"title": "性能诊断", "unit_ids": ["u", "v"]}])
        topic, = self.payload()["groups"]
        unit = next(u for u in topic["units"] if u["id"] == "u")
        counts = {"2020-01-01T23": 2, "2020-01-02T00": 1, "2020-01-02T09": 0}
        self.assertEqual(unit["hour_files"], counts)
        self.assertEqual(unit["day_bounds"]["2020-01-01"], [23 + 1/60, 23 + 59/60])
        self.assertEqual(unit["day_bounds"]["2020-01-02"], [0, 9 + 10/60])
        self.assertNotIn("2020-01-03", unit["day_bounds"])
        self.assertEqual(unit["date_only"], ["2020-01-03"])
        self.assertEqual(topic["hour_files"], {h: n / 2 for h, n in counts.items()})
        self.assertEqual(topic["date_only"], ["2020-01-01", "2020-01-03"])
        filtered, = api.build_payload(self.con, "all", "2020-01-02", "2020-01-02", "codex")["groups"]
        self.assertEqual(filtered["hour_files"], {"2020-01-02T00": 1, "2020-01-02T09": 0})
        self.assertEqual(filtered["day_bounds"], {"2020-01-02": [0, 9 + 10/60]})
        self.assertEqual(filtered["date_only"], [])
