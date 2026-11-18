# worklog

把本机**各个 AI 编程 harness** 留下的工作痕迹整理成一张能看懂的工作记录：**哪天在哪个项目上做了什么事、连续几天、产出多少**。

**不预设你用哪家 harness。** workbuddy 与 Claude Code 是精确解析，Codex / Cursor / Trae / Continue 走通用 JSONL 启发式，格式未知的由执行它的模型现场识别。

> 如果你是通过某个 agent 打开这个项目的：**先去看你自己所在的那个 harness 目录**。
> 宿主是 Codex 就看 `~/.codex`，是 Claude Code 就看 `~/.claude`——那才是你最近真正干活的记录。
> `~/.workbuddy` 不存在不是错误，跳过即可。

纯本地、只读 workbuddy 数据、零第三方依赖（只用 Python 标准库）。

## 给 agent 的一句话

> 请获取 <https://github.com/Dandan044/D_moyudays>，按仓库根目录 SKILL.md 整理这台机器上的 AI 工作记录，验收后生成可离线打开的工作记录网页。

需要能读取本机日志、执行终端命令的 agent，以及 Python 3.10 或更高版本。已有仓库可以直接使用。Windows 上可用 `py -3`，macOS 或 Linux 上可用 `python3`。生成网页只用 Python 标准库和仓库自带的前端。

```bash
git clone https://github.com/Dandan044/D_moyudays.git
cd D_moyudays
python -X utf8 run.py --prepare-only
```

准备命令导入能识别的来源、发现项目、扫描并退出。agent 接着按 [SKILL.md](SKILL.md) 核对来源，从原会话提炼任务、主题和详情。普通终端即可通过 `python -X utf8 -m worklog.cli call --help` 使用与 MCP 相同的整理工具。

验收用 `python -X utf8 -m worklog.cli audit`，固定交付文件用 `python -X utf8 -m worklog.cli export --output "data/工作记录.html"`。双击即可离线打开。交互预览也可用 `python -m worklog.cli serve`。迁移时只需仓库文件，各台机器分别生成自己的配置、数据库和网页。运行 `python -X utf8 -m unittest discover -s tests -v` 可复验隔离样例。

迁移测试在独立的用户目录和仓库副本中生成样例，覆盖空库、两个来源、分组详情及重复更新。设置 `WORKLOG_TEST_CHROME` 为本机 Chrome 或 Chromium 的可执行文件路径，可连同离线网页的实际渲染一起验证。

## 它怎么工作

```
~/.workbuddy/changes-index/*.json    每次请求改了哪些文件、增删多少行
~/.workbuddy/workbuddy.db            会话标题、cwd、时间（只读打开）
~/.claude  ~/.codex  ~/.cursor …     其它 harness（probe 探测 → 模型归一 → ingest 导入）
              ↓  scan
         会话与活动块（供 agent 依据上下文判断任务边界）
              ↓  agent 整理（CLI 或 MCP）
         分组（哪些段其实是同一件事）
              ↓
         网页：甘特 + 卡片 + 成就 + 时段分布
```

**所有需要判断的环节都不在脚本里**：找哪个目录、怎么解析格式、一次会话该切成几段、哪些段是同一件事——
这些由执行它的模型现场决定，脚本只负责存和算。

## 页面上能看什么

- **两个筛选器**：来源（workbuddy / claude-code / … / 全部来源）× 项目（全部 / 单个），可任意组合
- **顶部统计**：累计在岗小时、累计改动行、工作单元数、活跃天数，最后更新时间
- **泳道甘特**按天从新到旧排列，条带两端对齐当天的实际时刻。向右滚动可查看更早的活动，左侧始终显示对应的项目和任务名。
- **类型 / 工作量**两种配色，默认用白、红、紫表示每小时变更文件数。色轴上的文件数按指数递增，让常见的小改动也有可辨的色差。纯白表示零产出，紫色对应当前视图中单个任务的小时峰值。
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

之后可以说：「把这个项目的会话重新切分并归组」「给最近的任务段补上详情」。

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

- **项目匹配**按最长路径前缀，嵌套子仓库优先归到对应的子项目。
- 按会话内容判断任务边界，同一天内的不同目标也可以切成多段
- **改动行数**含生成物（HTML 报告、数据集），会出现「+4 万行」，不代表手写量
- **纯讨论**进入工作单元、分组和详情卡片，文件产出计零。
- 各来源按本机实际保留的历史统计。缺少日志的日期无法还原文件变更。
- 临时目录中的任务可按实际归属指定项目；杂项也进入「全部项目」视图

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

## 任务整理验收

甘特图和卡片共用“项目 → 任务主题 → 工作单元”的层级。运行 `python -m worklog.cli audit` 可以查看全库尚缺标题、主题或详情的任务 ID。已有记录可通过 `worklog_set_detail` 同时更新标题、概括和具体经过，再用 `worklog_apply_groups` 写入主题。完整整理步骤见 [SKILL.md](SKILL.md)。

甘特图保留日刻度、日期间距和固定左栏。连续有文件产出的日期共用一根条带，起止时刻按本地时间定位到日列内。条内逐小时着色，白色表示该小时无文件产出，整天无产出时条带断开。悬停可看对应小时与变更文件数。同一任务一小时内反复改同一文件计一次，主题取可见成员的同小时平均值。仅知日期的记录以斜线标示。运行 `python -m worklog.cli export` 将当前版本生成到 `data/` 下的独立 HTML。

每次打开或刷新网页都显示近七天，可在顶栏切换时间范围。条带以各小时的实际工作量为颜色锚点，平滑过渡，悬停可查看该小时的读数。顶栏可在午夜蓝、墨松绿和暮光梅间切换，配色选择保存在当前浏览器中。首次完整生成后，工作流会分别询问定时更新频率和桌面快捷方式。定时更新优先使用宿主的调度功能。
