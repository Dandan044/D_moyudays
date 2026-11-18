"""整理验收。只检查能机械核实的缺口，主题和结论由整理者填写。"""

import json
import re

from . import db, group


_CONTEXT = re.compile(
    r"<(?:codex_internal_context|environment_context|system[-_]reminder|local-command|"
    r"command-name|user_instructions|permissions instructions)\b|"
    r"objective omitted|^\s*(?:你是|你将扮演|you are\s).{1,30}[，。,.:：]",
    re.I | re.S,
)


def readable(text):
    return isinstance(text, str) and bool(text.strip()) and not _CONTEXT.search(text)


def task_title(text):
    if not readable(text):
        return False
    placeholders = {"测试", "未命名", "未命名会话", "继续开发", "待核实任务", "未命名分组", "会话"}
    return text.strip() not in placeholders and not re.fullmatch(r"[\w.-]+(?: [\w.-]+)*\s+会话", text.strip(), re.ASCII)


def parse_detail(raw):
    try:
        value = json.loads(raw or "null")
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def display_detail(detail):
    """旧卡片可以部分填写，只展示其中可读的段落。"""
    headline = detail.get("headline")
    sections = detail.get("sections")
    clean = []
    for section in sections if isinstance(sections, list) else []:
        if not isinstance(section, dict) or not readable(section.get("title")):
            continue
        items = section.get("items")
        if isinstance(items, list):
            visible = [item for item in items if readable(item)]
            if visible:
                clean.append({"title": section["title"], "items": visible})
    if readable(headline) or clean:
        return {"headline": headline if readable(headline) else "", "sections": clean}
    return None


def detail_issues(title, detail):
    issues = []
    headline = detail.get("headline")
    if not readable(headline) or headline.strip("。 .") == title.strip("。 ."):
        issues.append("缺少独立概括")
    labels = set()
    facts = {title.strip("。 ."), str(headline).strip("。 .")}
    invalid = False
    sections = detail.get("sections")
    for section in sections if isinstance(sections, list) else []:
        if not isinstance(section, dict) or not readable(section.get("title")):
            invalid = True
            continue
        items = section.get("items")
        if not isinstance(items, list) or not items or not all(readable(x) for x in items):
            invalid = True
            continue
        statements = {x.strip("。 .") for x in items}
        if statements - facts:
            labels.add(section["title"].strip())
        facts.update(statements)
    if invalid or len(labels) < 2:
        issues.append("详情缺少具体经过或结果")
    return issues


def audit(con):
    db.ensure_columns(con)
    group.ensure_tables(con)
    pending = []
    total = 0
    for row in con.execute("""
        SELECT w.*, g.id AS topic, g.title AS topic_title FROM work_unit w
        LEFT JOIN unit_group_map m ON m.unit_id = w.id
        LEFT JOIN work_group g ON g.id = m.group_id AND g.project_id = w.project_id
        ORDER BY w.project_id, w.id
    """):
        total += 1
        title = row["title"]
        issues = detail_issues(title, parse_detail(row["detail"]))
        if not task_title(title):
            issues.append("需要根据原始记录命名")
        if not row["topic"] or not task_title(row["topic_title"]):
            issues.append("缺少本项目的内容分组")
        if issues:
            pending.append({"project": row["project_id"], "unit_id": row["id"], "issues": issues})
    return {"total": total, "complete": total - len(pending), "pending": pending}
