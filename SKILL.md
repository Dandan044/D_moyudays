---
name: worklog
description: 把本机各个 AI 编程 harness（Codex、Claude Code、Cursor、Trae、workbuddy、qoder…）的会话与文件变更整理成可视化工作记录。工具只提供数据模型、网页和读写接口，所有需要判断的环节——找目录、解析格式、切分任务、归组、写摘要——都由你在执行时现场完成。
---

# worklog

把开发者在各个 AI harness 里留下的工作痕迹，整理成一张能看懂的工作记录网站。

## 先明确一件事

**这个项目不替你做判断。** 它提供的是：

- 一套数据模型（event → 工作单元 → 分组）
- 一个网页（甘特 / 卡片 / 成就 / 时段分布）
- 几个读写接口（`probe` 探索、`ingest` 导入、MCP 的切段/归组/写摘要）

**它不提供**「解析各 harness 的脚本」「切分任务的规则」「判断哪些是同一件事的逻辑」——这些恰恰是脚本做不好、只有你能做好的部分。

所以 `python run.py` 跑完只是"有了一个空架子 + 起了服务"，**真正的整理工作在你手上**。不要看到页面有东西就以为完事了，那只是机械扫描的结果。

## 第一步：跑起来（机械部分）

```bash
python run.py
```

它会：建库 → 扫描 workbuddy（如果这台机器有）→ 发现项目 → 起服务（127.0.0.1:8720）→ 开浏览器。

跑完你会看到一个只有「会话」没有「任务段」的页面——因为切分还没发生。这正是下一步要做的。

## 第二步：找出这台机器上有什么

```bash
python -m worklog.cli probe
```

它扫家目录、`AppData/Roaming`、`AppData/Local`，把每个目录的文件数、jsonl 数量、大小、最近修改时间、
**以及 jsonl 样本的字段名**列出来，分成两组：

- `with_jsonl`：有会话日志的目录，按日志数排序——**harness 几乎一定在这里**
- `others_sample`：只是文件多的目录，通常忽略

想看某个目录内部：`python -m worklog.cli probe ~/.codex`

**判断靠证据不靠名字。** 除了 claude/cursor/codex，还可能存在 `.qoder-cli`、`.gientech-agent` 这类你
没听过的——它们照样是 harness，照样有完整记录。看 jsonl 数量、看 sample 里的 keys。

## 第三步：自己写解析脚本

**不要指望内置解析器覆盖你的宿主。** 仓库里 `sources.py` 只放了两三个已验证格式当参考，
它不知道 Codex 的字段怎么排，也不认识你公司内部工具的结构。

正确做法是：读样本 → 现场写一小段转换代码 → 输出统一格式 → 导入。

```bash
head -n 5 <某个会话.jsonl>       # 先看真实结构，别猜
```

然后写个临时脚本（Python 即可），把该 harness 的记录转成：

```python
{
  "source": "codex",                    # 这个 harness 的名字，进「来源」筛选器
  "sessions": [
    {
      "session_id": "<稳定 id>",
      "cwd": "D:/work/proj",            # 没有就留空，项目归属会退回按文件路径判断
      "title": "重构登录流程",           # 一句话概括这次会话在干嘛
      "events": [
        {"ts": 1763350000000, "file": "D:/work/proj/src/login.ts",
         "action": "edit", "additions": 87, "deletions": 12}
      ]
    }
  ]
}
```

```bash
python -m worklog.cli ingest --file /tmp/codex.json      # 幂等，可反复跑
```

**导入会做质量检查，不合格直接拒绝**，返回类似：

```
解析质量不合格，已拒绝导入。
100% 的会话标题是默认值（说明没提取到真实标题）；
41% 的 file 字段不是路径（抓错了层级）；
几乎所有事件都没有增删行数
```

看到这个不是让你加 `--force` 硬塞，而是**回去重写解析**。三个指标的含义：

| 指标 | 超标说明 |
|---|---|
| 默认标题占比 | 没找到真正的标题字段，标题全成了「xxx 会话」 |
| file 不是路径 | 递归找 `path` 时抓到了结构体（如 `{'type':'special'}`）或 `file://` URL |
| 零行数占比 | 没找到增删行数字段，或者只抓到了消息没抓到工具调用 |

几个实战经验：

- **时间戳位置千奇百怪**：有的在 `timestamp` 字段，有的埋在消息正文的 `<timestamp>` 标签里（Cursor 就是这样），有的只有会话级 mtime
- **行数常常没有**：`Write` 看 `contents` 行数、`StrReplace` 看 old/new 差值；都没有就记 0，图上会显示成短的条，仍然能反映"那时候在干活"
- **cwd 不一定有**：没有就留空，项目归属会退回用 `file` 的绝对路径投票
- **只记录对话的工具**：用会话首末时间当活动证据，`file` 留空、行数 0
- **patch 型日志**：有的 harness（Codex 之类）不存结构化文件字段，而是把 patch 文本塞在工具入参里。
  这时要从文本标记里提路径：`*** Update File: xxx`、`*** Add File: xxx`、`--- a/xxx`、`+++ b/xxx`。
  行数就数 patch 里 `+` 开头 / `-` 开头的行
- **别用递归找 `path` 键**：嵌套结构里到处都有 `path`，容易抓到 `{'type':'special'}` 这类结构体。
  只认顶层字段，或者严格校验「像不像路径」

脚本放哪都行（`/tmp` 下就够），**不要提交进仓库**——它只对这台机器、这个版本有效。

## 第四步：切分任务段（这一步最影响观感）

机械扫描出来的「一个会话」往往横跨多天干了好几件事。**用时间间隔去猜切点是不准的**，
必须由你读内容判断。

```bash
# 1. 看哪些会话值得切
worklog_list_sessions(unsplit_only=true)

# 2. 拉某个会话的活动块
worklog_list_blocks(session_id="...")

# 3. 判断切几段、每段叫什么，写回
worklog_apply_split(session_id="...", segments=[
  {"title": "搭评测流水线骨架", "block_ids": ["b1","b2"]},
  {"title": "扩样本重跑并修错行", "block_ids": ["b3","b4","b5"]},
])
```

判断依据：

- 相邻块改同一批文件 / 同一模块、日期连续 → 同一段
- 文件集明显换到别的目录或模块 → 新段
- 隔几天回来继续改同一批文件 → 同一任务的不同阶段，块少就合并
- 标题要具体（「接 SynthAudioPanel 与路由」），不要「继续开发」

**不做这一步，页面就是一小时一条的碎块，没有可读性。** 这是脚本永远替代不了的部分。

## 第五步：归组（把同一件事的多次会话聚起来）

```bash
worklog_list_units(project="...")     # 拉任务单元
worklog_apply_groups(project="...", groups=[
  {"title": "TTS 读音与专有名词优化", "unit_ids": ["...", "..."]},
])
```

判断依据：不同会话在改同一批文件、围绕同一个目标 → 同一组。
跨 harness 也能归到一组（workbuddy 和 cursor 都在改同一个项目的那部分工作）。

## 第六步：写卡片详情

```bash
worklog_set_detail(items=[{
  "unit_id": "...",
  "headline": "补齐词条的错误类型标签，重建审阅页并冒烟，让后续能按类型分工修",
  "sections": [
    {"title": "为什么做", "items": ["上一轮打标还有词条没标上，标签不全没法按类型统计"]},
    {"title": "做了什么", "items": ["补齐打标脚本（make_labels.py —— 按问题给每条词条打类型标签）"]},
  ],
}])
```

写给小几天后忘光细节的自己：**先说为什么做，再说做成什么**。提到内部代号要当场解释它是干什么的。
禁止「优化代码」「处理问题」这类空话。

## 第七步：回报

告诉用户：哪几个 harness、各多少会话、切出多少个任务段、归了多少组。

---

## 哪些事脚本做了、哪些没做

| 环节 | 谁做 | 说明 |
|---|---|---|
| 建库、起服务、读 workbuddy | 脚本 | 机械活，不需要判断 |
| 找 harness 目录 | 脚本给证据，**你判断** | probe 只列事实，不说"这是 harness" |
| 解析各家格式 | **你**（现场写脚本） | 格式千差万别，内置解析器只是参考 |
| 切分任务段 | **你** | 时间间隔猜不出"换了一件事" |
| 归组 | **你** | 需要理解语义 |
| 写摘要与详情 | **你** | 需要理解上下文 |
| 项目归属、类型判定 | 脚本 | 按路径前缀和扩展名，规则明确且可预期 |

## 常用命令

| 命令 | 用途 |
|---|---|
| `python run.py` | 起服务（只做机械部分） |
| `python -m worklog.cli probe [path]` | 看目录里有什么 |
| `python -m worklog.cli ingest --file x.json` | 导入解析结果 |
| `python -m worklog.cli scan` | 重扫 workbuddy |
| `python -m worklog.cli init --force` | 重新发现项目 |
| `python -m worklog.cli serve` | 只起服务 |
| `python -m worklog.cli mcp` | MCP 服务（stdio） |

## 不要把 data/ 提交进仓库

`data/worklog.db` 含本机路径与项目名，已被 `.gitignore` 排除。解析脚本也别提交——它只对一台机器有效。
