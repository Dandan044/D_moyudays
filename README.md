# worklog

把本机**各个 AI 编程 harness** 留下的工作痕迹整理成一张能看懂的工作记录：**哪天在哪个项目上做了什么事、连续几天、产出多少**。

**不预设你用哪家 harness。** workbuddy 与 Claude Code 是精确解析，Codex / Cursor / Trae / Continue 走通用 JSONL 启发式，格式未知的由执行它的模型现场识别。

> 如果你是通过某个 agent 打开这个项目的：**先去看你自己所在的那个 harness 目录**。
> 宿主是 Codex 就看 `~/.codex`，是 Claude Code 就看 `~/.claude`——那才是你最近真正干活的记录。
> `~/.workbuddy` 不存在不是错误，跳过即可。

纯本地、只读 workbuddy 数据、零第三方依赖（只用 Python 标准库）。

## 一句话跑起来

```bash
git clone https://github.com/Dandan044/D_moyudays.git && cd D_moyudays && python run.py
```

`run.py` 只做机械部分：建库 → 扫描 workbuddy → 发现项目 → 起服务 → 开浏览器（`127.0.0.1:8720`）。

**它不替你切分任务、不替你归组**——跑完你看到的还是"一个会话一条"，可读性很差。
真正的整理要看 [SKILL.md](SKILL.md) 的七步工作流：找 harness → 现场写脚本解析 → 切段 → 归组 → 写详情。

不需要 `pip install`，不需要预先填任何路径。要求 Python 3.10+。

清空重来：删掉 `data/` 和 `config/projects.json` 再跑一次。

## 它怎么工作

```
~/.workbuddy/changes-index/*.json    每次请求改了哪些文件、增删多少行
~/.workbuddy/workbuddy.db            会话标题、cwd、时间（只读打开）
~/.claude  ~/.codex  ~/.cursor …     其它 harness（probe 探测 → 模型归一 → ingest 导入）
              ↓  scan
         工作段（session 内按停顿切分，跨天且 >4h 才切）
              ↓  模型判断（可选，通过 MCP）
         分组（哪些段其实是同一件事）
              ↓
         网页：甘特 + 卡片 + 成就 + 时段分布
```

**所有需要判断的环节都不在脚本里**：找哪个目录、怎么解析格式、一次会话该切成几段、哪些段是同一件事——
这些由执行它的模型现场决定，脚本只负责存和算。

## 页面上能看什么

- **两个筛选器**：来源（workbuddy / claude-code / … / 全部来源）× 项目（全部 / 单个），可任意组合
- **顶部统计**：累计在岗小时、累计改动行、工作单元数、活跃天数，最后更新时间
- **泳道甘特**：左新右旧，横条是任务段的实际跨度；没记录的周末折叠成窄条，跨周末的条会连起来
- **条带 / 热力**两种形态：条带按产出类型上色，热力按改动文件数从白到紫
- **成就行**：按日标注 🌅早开工 🌇晚收工 🔥马拉松 ⏳超长待机 💯爆发日 🎪多线并进 🐟摸鱼 等，悬停整列看当天全部成就
- **每日柱状图**：与日期列对齐，柱高 = 当日改动数
- **工作时段分布**：24 小时柱状，看一天里集中在几点
- **密度日历**：近 12 周每天的热度
- **卡片**：每个任务段一张，点开是「为什么做 / 做了什么 / 现在的状态」

## 接其它 harness

```bash
python -m worklog.cli probe                  # 探测本机有哪些 harness 目录
python -m worklog.cli ingest --file x.json   # 把解析结果导入（自动重扫）
```

`probe` 只负责"告诉他有什么"，格式判断交给执行它的模型：读样本、认字段、归一成统一事件。
详细流程写在 [SKILL.md](SKILL.md) 的「多 harness」一节——**那里是给人/AI 看的操作手册，不是装饰**。

导入的会话存在 `external_session` 表，参与后续所有聚合（项目归属、切段、分组、成就），
和 workbuddy 记录没有区别。工作单元会带上 `harness` 字段，顶栏的「来源」筛选器据此分类，选「全部来源」即总览。`(source, source_ref)` 幂等，重复导入无副作用。

## 接入 harness（MCP）

写进 `~/.workbuddy/mcp.json`：

```json
"worklog": {
  "command": "<python 绝对路径>",
  "args": ["-m", "worklog.cli", "mcp"],
  "cwd": "<本仓库绝对路径>"
}
```

之后可以说：「把 LLMbox 的会话重新切分并归组」「给最近的任务段补上详情」。

工具：`worklog_list_sessions` / `list_blocks` / `apply_split`（切段）、`list_units` / `apply_groups`（归组）、`set_notes` / `set_detail`（写卡片）、`summary` / `scan`。

细节见 [SKILL.md](SKILL.md)。

## 命令行

```bash
python -m worklog.cli init --force        # 重新发现项目（换了机器/新增仓库）
python -m worklog.cli scan                # 只重扫
python -m worklog.cli serve               # 只起服务
python -m worklog.cli report --project X --days 14   # 终端看报告
```

## 口径与限制

- **项目匹配**按最长路径前缀，嵌套子仓库优先——所以 `LLMbox/BERT_.../ernie_xxx` 会独立成项目，不被父仓库吞并
- **切段**只在跨天且停顿 >4h 时才切；同一天内做三件事不会被拆开（交给归组时区分）
- **改动行数**含生成物（HTML 报告、数据集），会出现「+4 万行」，不代表手写量
- **纯讨论**（没有文件变更）在图上是一条空心虚线，算「有工作但无产出」
- `changes-index` 只覆盖 **2026-09-04 之后**，更早的日期只有会话、没有文件级记录
- cwd 在临时目录的会话归「杂项」，默认不进「全部项目」视图

## 目录结构

```
run.py                     一键启动
SKILL.md                   给 harness 的操作手册
worklog/                   后端（标准库）
  db.py                    schema
  scan.py                  扫描 + 切段
  init_project.py          自动发现项目
  normalize.py             项目归一 / 类型判定
  group.py                 分组存储
  api.py                   HTTP 服务 + JSON 接口
  cli.py                   命令行
  mcp_stdio.py             MCP 服务（stdio）
web/                       前端（无构建、无框架）
config/projects.json       本机项目映射（不入库，首次运行自动生成）
data/worklog.db            运行产物（不入库）
```

## 数据不出本机

服务只监听 `127.0.0.1`，`workbuddy.db` 以只读方式打开，`changes-index` 只读不写。
`data/` 与 `config/projects.json` 都在 `.gitignore` 里——仓库里只有代码，没有任何个人记录。
