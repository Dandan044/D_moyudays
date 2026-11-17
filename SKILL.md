---
name: worklog
description: 把本机多个 AI 编程 harness（workbuddy、Claude Code、Codex、dsh 等）的会话与文件变更记录整理成可视化工作记录（甘特图、卡片、成就、时段分布），纯本地运行，零第三方依赖。当用户说"整理我的工作记录""看看我最近做了什么""这几个工具我都用过，合起来看看"时使用。
---

# worklog

把开发者在**各个 AI harness 里留下的工作痕迹**整理成一张工作记录网站。

内置 workbuddy 的解析，其它 harness 由你在执行时现场识别——见下面「多 harness」一节。

## 一句话启动

```bash
git clone <repo> && cd D_moyudays && python run.py
```

`run.py` 依次：自动发现本机项目 → 扫描 workbuddy 记录 → 起本地服务（127.0.0.1:8720）→ 打开浏览器。

不需要 pip install，只用 Python 标准库（3.10+）。

## 多 harness：不要只看 workbuddy

**这是本项目的核心设计：数据源不止一家。** 开发者往往同时装了好几个 harness，各自留了一份日志。只整理 workbuddy 会漏掉一半的工作量。

### 第一步：探测

```bash
python -m worklog.cli probe
```

输出 JSON，列出本机存在哪些 harness 目录、文件数、以及 JSONL 样本的字段轮廓。已知候选目录包括：

`~/.claude` · `~/.codex` · `~/.dsh` · `~/.cursor` · `~/.continue` · `~/.aider` · `~/.gemini` · `~/.cline` · `~/.trae` · `~/.codeium`

**别停在候选列表上。** 如果 `probe` 没命中，自己去家目录、`AppData/Roaming`、`AppData/Local` 里按名字找（claude / codex / cursor / trae / windsurf / cline / qwen / gemini / copilot / aider…），逐个 `ls` 看有没有 `*.jsonl`、`*.json`、`sessions/`、`chats/`、`history*` 这类东西。

### 第二步：读样本，自己判断格式

不要依赖字段名猜。直接读目标文件的前几行：

```bash
head -n 3 <某个会话.jsonl>
```

你要从中抽出三样东西：

| 需要什么 | 常见字段名 |
|---|---|
| 时间戳 | `timestamp` / `ts` / `time` / `created_at` / `createdAt` |
| 工作目录 | `cwd` / `projectPath` / `workspace` / `workspaceFolder` |
| 文件变更 | tool 调用的 `file_path` / `path`，或 `files` / `changes` 数组，或 diff 文本 |

有些 harness 只记录对话不记录文件改动（比如只存 message 的日志）。这种情况下**用会话的起止时间和 token 用量作为活动证据**，把 `file` 留空、`additions`/`deletions` 记 0——图上会显示成空心条，仍然能反映"那时候在干活"。

### 第三步：归一化后导入

把解析结果写成统一格式，交给 `ingest`：

```bash
python -m worklog.cli ingest --file /tmp/claude-code.json
```

格式：

```json
{
  "source": "claude-code",
  "sessions": [
    {
      "session_id": "<该 harness 的会话 id，没有就自己生成一个稳定 id>",
      "cwd": "D:/work/proj",
      "title": "用 Claude Code 重构 TTS 分段",
      "events": [
        {"ts": 1763350000000, "file": "D:/work/proj/tts_eval/segmenter.py",
         "action": "edit", "additions": 87, "deletions": 12}
      ]
    }
  ]
}
```

导入后会自动重扫。项目归属、切段、分组、成就、甘特图全部按和 workbuddy 一样的口径处理——不需要额外适配。

**幂等**：`(source, source_ref)` 去重，同一个会话重复导入不会产生重复数据，可以放心重跑。

### 第四步：告诉用户整合了什么

整理完要回报清楚：哪几个 harness、各导入了多少会话、时间范围。用户最想知道的是"我以前在 Cursor 里干的活也进来了吗"。

## 首次运行会发生什么

1. **发现项目**：只读 workbuddy 会话的 cwd，向上找 `.git` 得到仓库根；没有 git 但反复出现的目录也纳入。结果写到 `config/projects.json`。
2. **扫描**：解析 `changes-index` 得到逐文件变更，按会话聚合成「工作单元」。
3. **起服务**：网页 + JSON API，仅监听 127.0.0.1。

`config/projects.json` 只在本机生成，不入库——每台机器的路径不同。

## 常见操作

| 想做什么 | 命令 |
|---|---|
| 探测其它 harness 目录 | `python -m worklog.cli probe` |
| 导入外部 harness 记录 | `python -m worklog.cli ingest --file x.json` |
| 重新发现项目 | `python -m worklog.cli init --force` |
| 只重扫不启服务 | `python -m worklog.cli scan` |
| 终端看某项目一段时间 | `python -m worklog.cli report --project LLMbox --days 14` |
| 起服务不开浏览器 | `python -m worklog.cli serve` |
| 以 MCP 服务运行 | `python -m worklog.cli mcp` |

## 作为 MCP 接入 harness

写进 `~/.workbuddy/mcp.json`（或对应 harness 的 MCP 配置）：

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
外部 harness 导入的会话同样落在这个库里（`external_session` 表），也不会进仓库。
