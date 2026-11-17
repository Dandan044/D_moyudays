---
name: worklog
description: 把本机 workbuddy 会话与文件变更记录整理成可视化工作记录（甘特图、卡片、成就、时段分布），纯本地运行，零第三方依赖。当用户说"整理我的工作记录""看看我最近做了什么""生成工作日报/周报视图"时使用。
---

# worklog

把 workbuddy 的历史记录（`~/.workbuddy` 下的 changes-index 与 sessions）整理成可看的工作记录网站。

## 一句话启动

```bash
git clone <repo> && cd D_moyudays && python run.py
```

`run.py` 会依次：自动发现本机项目 → 扫描记录 → 起本地服务（127.0.0.1:8720）→ 打开浏览器。

不需要 pip install，只用 Python 标准库（3.10+）。

## 首次运行会发生什么

1. **发现项目**：只读 `~/.workbuddy/workbuddy.db` 里的会话 cwd，向上找 `.git` 得到仓库根；
   没有 git 但反复出现的目录也纳入。结果写到 `config/projects.json`。
2. **扫描**：解析 `changes-index` 得到逐文件变更，按会话聚合成「工作单元」。
3. **起服务**：网页 + JSON API，仅监听 127.0.0.1。

`config/projects.json` 只在本机生成，不入库——每台机器的路径不同。

## 常见操作

| 想做什么 | 命令 |
|---|---|
| 重新发现项目（路径变了、新增仓库） | `python -m worklog.cli init --force` |
| 只重扫不启服务 | `python -m worklog.cli scan` |
| 终端看某项目一段时间 | `python -m worklog.cli report --project LLMbox --days 14` |
| 起服务不开浏览器 | `python -m worklog.cli serve` |
| 以 MCP 服务运行 | `python -m worklog.cli mcp` |

## 作为 MCP 接入 harness

写进 `~/.workbuddy/mcp.json`：

```json
"worklog": {
  "command": "<python 解释器绝对路径>",
  "args": ["-m", "worklog.cli", "mcp"],
  "cwd": "<本仓库绝对路径>"
}
```

工具清单：

- `worklog_list_sessions` / `worklog_list_blocks` / `worklog_apply_split`：把会话切成任务段
- `worklog_list_units` / `worklog_apply_groups`：把任务段聚成组
- `worklog_set_notes` / `worklog_set_detail`：写卡片摘要与「总分」详情
- `worklog_summary` / `worklog_scan`：取汇总、重扫

**分组与切分都不做规则判定**，由模型判断后写回，结果落库只算一次。

## 关键口径

- 一个会话里跨天且停顿 > 4 小时 → 切成另一段任务（未切分的会话用这条兜底）
- 一个任务段 = 一个工作单元，标题可以是模型起的那句话
- 项目按**最长路径前缀**匹配，嵌套子仓库优先于父仓库
- 变更行数含生成物，会出现「+4 万行」，不代表手写量

## 不要把 data/ 提交进仓库

`data/worklog.db` 是运行产物，含本机路径与项目名，已被 `.gitignore` 排除。
