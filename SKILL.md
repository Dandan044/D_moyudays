---
name: worklog
description: 把本机各个 AI 编程 harness（Codex、Claude Code、Cursor、Trae、workbuddy、dsh…）的会话与文件变更记录整理成可视化工作记录（甘特图、卡片、成就、时段分布），纯本地运行，零第三方依赖。当用户说"整理我的工作记录""看看我最近做了什么""这几个工具我都用过，合起来看看"时使用。
---

# worklog

把开发者在**各个 AI harness 里留下的工作痕迹**整理成一张工作记录网站。

> **这个工具不预设你用的是哪家 harness。** workbuddy 只是内置解析的其中一家，
> 任何有本地日志的 harness 都能接进来——包括你此刻运行所在的那一个。

## 第一步：先看你自己

你（执行这段的 agent）正跑在某个 harness 里：Codex、Claude Code、Cursor、Trae、workbuddy……

**你自己的记录就在你自己的目录里，那是优先级最高的数据源。** 不要因为「README 里第一个提到 workbuddy」就默认去找 workbuddy——如果你的宿主是 Codex，`~/.codex` 下才是你这几天真正干的事；宿主是 Claude Code，就去看 `~/.claude/projects`。

先回答自己两个问题：

1. 我这个 harness 把会话存在哪？（`~/.codex` / `~/.claude` / `~/.cursor` / AppData… ）
2. 它记录文件改动吗？记录在哪个字段（tool 调用的 `file_path`、diff、还是只有对话）？

确认了再往下走。**如果 `~/.workbuddy` 根本不存在，那不是错误，跳过 workbuddy 那一路就行。**

## 第二步：让工具把证据摆出来

```bash
python -m worklog.cli probe
```

**这个命令不认 harness 名字。** 它扫家目录、`AppData/Roaming`、`AppData/Local`，把每个目录的文件数、
jsonl 数量、大小、最近修改时间、以及 jsonl 样本的字段轮廓列出来，分成两组：

- `with_jsonl`：有会话日志的目录，按日志数量排序——**harness 几乎一定在这里**
- `others_sample`：只是文件多的目录，通常不是，忽略即可

想知道某个目录到底是什么，直接深入：

```bash
python -m worklog.cli probe ~/.qoder-cli
```

### 判断靠证据，不靠名字

不要因为「没见过这个名字」就跳过。真实情况是：除了 claude/cursor/codex，还有
`.qoder-cli`、`.gientech-agent`、`.qoderworkcn` 这类你大概率没听过的——它们照样是 harness，
照样有完整的会话记录。**看 jsonl 数量、看 sample 里的 keys**，那才是判断依据。

一个目录像 harness 的信号：

- 有 `*.jsonl`，每行是一个带 `timestamp` 的对象
- 有 `sessions/`、`projects/`、`chats/`、`tasks/` 这类子目录
- 子目录名是 UUID 或 workspace 路径的变形

## 第三步：跑起来

```bash
python run.py
```

它会自动处理**内置能识别的** harness（workbuddy 原生、claude-code 精确解析、其余通用 JSONL 启发式），
写入本地库 → 发现项目 → 扫描 → 起服务（127.0.0.1:8720）→ 开浏览器。

**内置解析只是加速器，不是覆盖率保证。** 你刚在 `probe` 里看到的那些目录，
如果 `run.py` 没导入，就由你手工接手——见下一步。

## 第四步：手工接管（自动解析没覆盖到的）

```bash
python -m worklog.cli probe
```

输出每个目录的文件数、JSONL 字段轮廓。然后：

```bash
head -n 3 <某个会话.jsonl>     # 直接读，别猜字段名
```

从样本里认出三样东西：

| 需要什么 | 常见字段 |
|---|---|
| 时间戳 | `timestamp` / `ts` / `time` / `created_at` / `createdAt` |
| 工作目录 | `cwd` / `projectPath` / `workspace` / `workspaceFolder` |
| 文件变更 | tool 调用里的 `file_path` / `path`，或 `files` / `changes` 数组 |

归一成统一格式后导入：

```bash
python -m worklog.cli ingest --file /tmp/xxx.json
```

```json
{
  "source": "codex",
  "sessions": [
    {
      "session_id": "<会话 id，没有就自己生成稳定的>",
      "cwd": "D:/work/proj",
      "title": "重构登录流程",
      "events": [
        {"ts": 1763350000000, "file": "D:/work/proj/src/login.ts",
         "action": "edit", "additions": 87, "deletions": 12}
      ]
    }
  ]
}
```

只记录对话、不记录文件改动的 harness，用**会话起止时间当活动证据**：`file` 留空、行数记 0，图上会显示成空心条，仍然能反映"那时候在干活"。

`(source, source_ref)` 幂等，重复导入无副作用。

## 第五步：回报

告诉用户：**哪几个 harness、各多少会话、时间范围**。用户最关心的是"我以前在 X 里干的活也进来了吗"。

导入的数据会出现在顶栏的「来源」筛选器里，可与「项目」任意组合，选「全部来源」就是总览。

## 其它命令

| 想做什么 | 命令 |
|---|---|
| 探测 harness 目录 | `python -m worklog.cli probe` |
| 导入外部记录 | `python -m worklog.cli ingest --file x.json` |
| 重新发现项目 | `python -m worklog.cli init --force` |
| 只重扫 | `python -m worklog.cli scan` |
| 终端看报告 | `python -m worklog.cli report --project X --days 14` |
| 起服务 | `python -m worklog.cli serve` |
| MCP 服务 | `python -m worklog.cli mcp` |

## 作为 MCP 接入

```json
"worklog": {
  "command": "<python 绝对路径>",
  "args": ["-m", "worklog.cli", "mcp"],
  "cwd": "<本仓库绝对路径>"
}
```

工具：`list_sessions` / `list_blocks` / `apply_split`（切段）、`list_units` / `apply_groups`（归组）、`set_notes` / `set_detail`（写卡片）、`summary` / `scan`。

切段与归组**不做规则判定**，由模型判断后写回，结果落库只算一次。

## 关键口径

- 一个会话里跨天且停顿 > 4 小时 → 切成另一段任务（未切分的用这条兜底）
- 一个任务段 = 一个工作单元，标题可以是模型起的那句话
- 项目按**最长路径前缀**匹配，嵌套子仓库优先于父仓库
- 变更行数含生成物，会出现「+4 万行」，不代表手写量

## 不要把 data/ 提交进仓库

`data/worklog.db` 是运行产物，含本机路径与项目名，已被 `.gitignore` 排除。
外部 harness 导入的会话存在 `external_session` 表，同样不会进仓库。
