# Life Copilot — 使用手册

> 版本：v4.3（2026-06-04）
> 运行环境：Claude Code (或任意代理 AI) + Obsidian + macOS
> 核心脚本：`scripts/copilot.py`
> RFC: [[life-copilot-v4.3-rfc]]

---

## 目录

1. [系统概览](#1-系统概览)
2. [目录结构](#2-目录结构)
3. [对话模式](#3-对话模式)
4. [Active Board 与 Seeds](#4-active-board-与-seeds)
5. [脚本命令全览](#5-脚本命令全览)
6. [记忆系统](#6-记忆系统)
7. [日程投影](#7-日程投影)
8. [Quant 任务产物协议](#8-quant-任务产物协议)
9. [写回守则](#9-写回守则)
10. [文件格式约定](#10-文件格式约定)
11. [日常维护](#11-日常维护)
12. [Negative Backlog](#12-negative-backlog)
13. [常见问题](#13-常见问题)
14. [GitHub 部署与隐私保护](#14-github-部署与隐私保护)

---

## 1. 系统概览

Life Copilot 是一个本地 AI 个人操作系统，运行在 Obsidian 工作目录上，通过 Claude Code 提供智能分析与写回能力。

**核心设计原则（v4.3）：**

- **直读源文件**：Claude Code 直接读取日记、记忆、路线图等原始文件，无需预生成上下文包
- **AI 对话可追溯**：Codex / Claudian 当日对话归档为独立 trace 文件，日记只保留 wikilink 索引
- **Append-only 数据**：洞察日志（insights.jsonl）、日程历史只增不改
- **上下文路由**：模式触发是软建议，不是硬门控；系统读 `life-board.md` + 记忆 + 当日日记来决定路由
- **本地优先**：所有数据在 iCloud 同步的 Obsidian 目录，无外部数据库依赖
- **Active Board 驱动**：`life-board.md` 是"Henry 在做什么"的 single source of truth，取代 roadmap 隐含假设
- **Schedule as Projection**：日程是对话投影，不是脚本生成的执行清单
- **Negative Backlog**：明确退役不再使用的规则，防止功能蔓延和僵尸规则

**v4.3 相比 v4.2 的主要变化：**

| 项目 | v4.2 | v4.3 |
|------|------|------|
| 路由 | 硬触发（`#quant`、`#YYYY-MM-DD`） | 上下文软路由（读 board + memory + diary） |
| 生活全景 | `quant/roadmap.md` 隐含为 life | `life-board.md` 显式为 single source of truth |
| 日程生成 | 需要已填写 Quant Feedback 才触发 | 对话投影，不依赖脚本门槛 |
| 项目入口 | XP task 创建 | Seeds → Active Board promotion |
| 模式 | Diary / Quant / Chat | Diary / Quant / Study / Chat |
| 路线图 / 状态 | 活跃使用 | 历史参考（roadmap 100% complete） |

---

## 2. 目录结构

```
Life/                                     ← Obsidian 工作目录根
├── AGENTS.md                             ← AI 行为规则（文件地图 + 模式路由 + 护栏 + v4.3 扩展）
├── CLAUDE.md                             ← 兼容入口，转发到 AGENTS.md
├── readme.md                             ← 本文件
├── life-board.md                         ← 🌟 Active Board（各 track 的 single source of truth）
├── life-copilot-v4.3-rfc.md              ← v4.3 RFC（设计决策与迁移说明）
├── .gitignore                            ← 🌟 隐私防洪堤（拦截日记、目标与配置不入库）
│
├── scripts/
│   └── copilot.py                        ← 核心脚本（只含写回 + quant 生命周期）
│
├── journal/                              ← 日记模块 (绝对私密区)
│   ├── YYYY/MM/YYYY-MM-DD.md            ← 每日日记
│   ├── ai-conversations/YYYY/MM/         ← Codex / Claudian 每日 trace 文件
│   ├── memory.md                         ← 长期热记忆（结构化分区，Claude 直读）
│   ├── memory-archive.md                 ← 🌟 记忆冷归档（过期假设自动沉淀至此）
│   └── insights.jsonl                    ← 洞察日志（append-only）
│
├── seeds/                                ← 🌟 候选项目孵化区（暂不可行但值得保留的想法）
│   ├── 00-index.md                       ← 种子索引 + 升级协议
│   └── *.md                              ← 各种子文件
│
├── quant/                                ← 职业/Quant 模块
│   ├── state.md                          ← 状态快照（历史参考，v4.3 后非默认路径）
│   ├── roadmap.md                        ← 路线图（历史参考，100% complete as of 2026-06-03）
│   ├── projects/                         ← Active builds / engineering projects
│   ├── career-moats/                     ← Internship pipeline / interview prep / career assets
│   ├── university/                       ← Academic obligations
│   ├── schedules/                        ← 日程归档（append-only）
│   │   └── YYYY/MM/sched-YYYY-MM-DD.md ← 每日日程文件
│   ├── arsenal/                          ← XP 任务产物
│   │   ├── xp-XX-mission-guide.md
│   │   ├── xp-XX-session-notes.md
│   │   └── xp-XX-summary.md
│   └── resumes/                          ← 简历文件
│
├── prompts/                              ← 模式行为规则（Obsidian 可见）
│   ├── diary-mode.md
│   ├── quant-mode.md
│   ├── chat-mode.md
│   └── study-mode.md
│
├── resources/                            ← 学习资料（PDF、课程等）
├── inbox/                                ← 零摩擦捕获缓冲区
├── templates/                            ← 日记模板
└── archives/                             ← 历史存档（论文、竞赛等）
```

命名规则：新建文件夹和普通文档统一使用 lowercase kebab-case；不再使用 `01-xxx` 这类排序前缀。例外是 `AGENTS.md`、`CLAUDE.md`，以及 `00-index.md` / `00-readme.md` 这类目录入口文件。

---

## 3. 对话模式

v4.3 的模式触发是**软建议**。进入任何模式前，先看：

1. `life-board.md` — 当前 active tracks 和 next artifacts
2. `journal/memory.md` — 热记忆与 Canonical
3. 当日日记（若存在）— 今天已经发生了什么

如果关键词和上下文冲突，按上下文路由。

---

### 3.1 Diary Mode（日记模式）

**触发方式：** 输入 `#YYYY-MM-DD`（例如 `#2026-03-30`）

**AI 执行流程：**

若目标日期日记存在，先归档当天 AI 对话：

```bash
python3 scripts/copilot.py writeback-ai-day --date 2026-03-30
```

这会把当天 Codex / Claudian 对话写入：
- `journal/ai-conversations/YYYY/MM/YYYY-MM-DD-codex-trace.md`
- `journal/ai-conversations/YYYY/MM/YYYY-MM-DD-claudian-trace.md`

日记的 `## 💬 From Kai` 只追加 `[[YYYY-MM-DD-codex-trace]]` / `[[YYYY-MM-DD-claudian-trace]]` 这样的 wikilink 索引。重复执行按 wikilink 去重。

如果只是想先看会写入什么，使用：

```bash
python3 scripts/copilot.py preview-ai-day --date 2026-03-30
```

Claude 直接读取：
1. `journal/YYYY/MM/YYYY-MM-DD.md` — 当日日记
2. `journal/memory.md` — 长期记忆（Active Hypotheses 区块优先）
3. 目标日期前后 2-3 天的日记 — 时间上下文
4. `## 💬 From Kai` — 当天 Telegram 原始对话流（若存在）和 AI trace wikilink 索引；若有 wikilink，需要跟读 trace 文件
5. 从当天内容抽出 `1-2` 条主线主题
6. `journal/insights.jsonl` — 历史索引层（找已有命名模式、refs、验证线索）
7. `journal/memory-archive.md` — 冷归档（找仍 relevant 的旧模式）
8. 按主线主题 Grep `journal/` — 原始样本日记（关键词、变体表达、相关意象）
9. 可选外部检索 — 仅用于实效性事实校验，不替代本地历史证据
10. 若命中文档中有 `[[...]]` wikilink，再额外读取一层
11. `prompts/diary-mode.md` — 模式行为规则

**Diary 输出要求（行为层）：**
- 每篇分析都默认做主题级历史检索，而不是只在想到时才查。
- 回答里要明确区分：这是旧模式复现、旧模式修正、旧假设验证，还是新模式出现。
- 结尾默认做一次简短 memory audit：`无需写入` / `值得记录为验证` / `值得记录为新模式`。
- `journal/insights.jsonl` 只作为检索索引层；面向用户仍优先引用 `[[YYYY-MM-DD]]`。
- 外部联网搜索只用于补充新闻、人物近况、产品/政策/赛事/旅行地点当前状态等实效性事实；使用时需标明来源和日期。

**写回日记（需要时）：**

```bash
# 先把 AI 分析写到临时文件（路径自定）
# 再执行写回（只写入 ## What Life Copilot Said）
python3 scripts/copilot.py writeback-journal \
  --date 2026-03-30 \
  --input-file <临时文件路径>
```

---

### 3.2 Quant Mode（量化模式）

**触发方式：** 输入 `#quant`，或消息明显围绕量化学习、XP 文件、量化项目、职业准备。

**Post-roadmap 规则：**

截至 [[2026-06-03]]，`quant/roadmap.md` 已完成。`sync-quant-state --date` 和 `update-schedule --date` 不再是默认 daily loop；它们仍保留原本的 Quant Feedback gate，用于 legacy Quant、未来新训练阶段或明确手动 override。

一般生活规划先读 `life-board.md`。不要因为消息里出现 `roadmap` 就自动运行 Quant scripts。

**需要 legacy/manual Quant 时：**

```bash
python3 scripts/copilot.py sync-quant-state \
  --date YYYY-MM-DD \
  --allow-missing-journal \
  --chat-note "manual override"

python3 scripts/copilot.py update-schedule --target-date YYYY-MM-DD
```

`update-schedule --date YYYY-MM-DD` 仍会检查当日日记里的 `## 📊 Legacy Quant Feedback`（或旧标题 `## 📊 Quant Protocol Feedback`）是否有真实填写内容；空模板不会触发 state 或 schedule 更新。

> **Template change (v4.3):** Default diary template no longer includes this section. To use legacy Quant scripts, paste the snippet from `templates/legacy-quant-feedback.md` into today's journal.

然后 Claude 直接读取：
- `prompts/quant-mode.md` — 模式行为规则
- `quant/state.md` — 历史状态参考
- `quant/roadmap.md` — 历史路线图参考
- 具体 XP 的 `quant/arsenal/` 文件（若讨论具体任务）

---

### 3.3 Study Mode（学习模式）

**触发方式：** 输入 `#study`，或对话围绕阅读、概念理解、代码练习，且不属于 Quant 专业化。

Claude 直接读取：
- `prompts/study-mode.md` — 模式行为规则
- `journal/memory.md` — 热记忆
- 相关学习笔记或资料目录

Study Mode 的重点是先复用已有资料，再决定是否新建笔记；避免把每个问题都升级成项目。

---

### 3.4 Chat Mode（通用对话模式）

**触发方式：** 不属于 Diary / Quant / Study 的普通对话，或用户只是分享想法、讨论方案、让 Copilot 做轻量任务。

Claude 直接读取：
- `prompts/chat-mode.md` — 模式行为规则
- `journal/memory.md` — 长期记忆
- 按需 Grep 搜索 `journal/` 目录获取历史证据
- 需要项目上下文时读取 `life-board.md`

---

## 4. Active Board 与 Seeds

### 4.1 Active Board

`life-board.md` 是 v4.3 的 active work single source of truth。它回答的是：Henry 现在到底在做什么。

每个 track 只保留四个字段：
- **Active question** — 当前要回答的问题
- **Next artifact** — 下一个具体产出物
- **Stop condition** — 什么时候算完成
- **Status** — `active` / `waiting` / `paused` / `done`

Board 在日记分析或 Henry 明确要求时更新，不由脚本自动更新。

### 4.2 Seeds

`seeds/00-index.md` 是候选项目孵化区的 source of truth。Seed 是“值得保留，但还不到 active project”的想法，不是 todo，不是 backlog。

Seed 升级为 active track 需要同时满足：
- 有 2-3 个 session 的真实执行窗口
- 有明确 next artifact
- 有 stop condition
- 不挤占更高优先级 active project

### 4.3 Inbox Flush

`inbox/` 是零摩擦捕获缓冲区。flush 时先读各目录的 `00-readme.md` / `readme.md` / `life-board.md` 判断归属：
- 明确属于某处：移到目标目录
- 有价值但暂不可行：移到 `seeds/`
- 2 分钟仍无法判断：询问；若仍不确定，低置信放入 `seeds/`
- 噪声或过期：删除，并记录到 `inbox/flush-log.md`

---

## 5. 脚本命令全览

所有命令格式：`python3 scripts/copilot.py <subcommand> [options]`

### Quant 状态管理

| 命令 | 用途 |
|------|------|
| `sync-quant-state --date YYYY-MM-DD [--allow-missing-journal] [--chat-note "..."]` | 从当日日记的**已填写** Legacy Quant Feedback 同步 state.md；若日记空白/缺失但你显式提供 `--chat-note`，可作为手动 override |
| `update-schedule --date YYYY-MM-DD` | 以该日期作为基准日，在当日日记存在**已填写** Legacy Quant Feedback 时生成 / 刷新次日日程并更新 roadmap 指针 |
| `update-schedule --target-date YYYY-MM-DD` | 手动 override：直接生成或指向指定日期的日程文件，不走日记反馈门槛 |
| `sync-roadmap-stats` | 重算 XP 完成率并更新 roadmap 头部 Total Readiness |

---

### Quant 任务产物

| 命令 | 用途 | 输出文件 |
|------|------|----------|
| `quant-mission --xp XP-XX [--date YYYY-MM-DD] [--force]` | 生成 XP 任务 Mission Guide 脚手架 | `quant/arsenal/xp-xx-mission-guide.md` |
| `quant-question-link --question "..." [--xp XP-XX] [--top 8] [--json]` | 检索现有 quant 文件中可复用的问题链接候选（只读，不写文件） | stdout |

`quant-question-link` 用于 Quant 学习中出现可复用问题时，先搜索 `quant/arsenal/` 和 `quant/roadmap.md` 已有文件，输出候选链接（`[[target#heading|question]]` 格式），帮助决定是直接链接、扩展已有文件还是新建笔记。默认输出人类可读 bullets，`--json` 输出结构化 JSON。

这是一个**只读的第一轮候选检索工具**，不是最终语义判断。返回候选后，代理应打开文件验证内容，并在候选不足时用 `rg` 换同义词/机制词继续搜索。它有意取代了旧的 embedding/index 方案，改用本地文件直读 + 模型引导搜索。

---

### 记忆写回

| 命令 | 用途 |
|------|------|
| 手动粘贴到 `## 💬 From Kai` | 保存当天 Telegram 上与 Kai 的原始对话流，不整理、不改写 |
| `preview-ai-day --date YYYY-MM-DD` | 预览当天 Codex / Claudian trace 文件与日记 wikilink，不写文件 |
| `writeback-ai-day --date YYYY-MM-DD` | 归档当天 Codex / Claudian trace，并把 wikilink 索引追加到日记 `## 💬 From Kai` |
| `writeback-journal --date YYYY-MM-DD --input-file <path>` | 把夜间 AI 分析写回日记的 `## What Life Copilot Said` |
| `writeback-thought --date YYYY-MM-DD --title "<标题>" --input-file <path>` | 把用户自己的日记正文补充写入 Thoughts & Reflections，并同步更新 Daily Log |
| `writeback-memory --date YYYY-MM-DD --kind "<类型>" --content "<内容>"` | 写入长期记忆 memory.md |
| `append-insight --date YYYY-MM-DD --kind "<类型>" --content "<内容>"` | 追加洞察到 `journal/insights.jsonl`（如需同时写入长期记忆，另运行 `writeback-memory`） |

> **Codex transcript 低级操作**：以下命令用于手动处理单个 Codex 线程或单日 transcript。日常日记分析优先使用 `writeback-ai-day --date YYYY-MM-DD`（自动归档全部 Codex + Claudian 对话），仅在需要精细控制时使用以下命令。

| 命令 | 用途 |
|------|------|
| `writeback-codex-thread --date YYYY-MM-DD [--thread-id ID \| --session-file PATH]` | 把单个 Codex 线程 transcript 写入日记 `## 💬 From Kai`（手动选择线程） |
| `writeback-codex-day --date YYYY-MM-DD` | 把当天所有 Codex 线程 transcript 合并写入日记 `## 💬 From Kai` |
| `export-codex-thread [--thread-id ID \| --session-file PATH] [--output-file PATH]` | 导出单个 Codex 线程 transcript 到独立 markdown 文件（不写日记） |
| `export-codex-day --date YYYY-MM-DD [--output-file PATH]` | 导出当天所有 Codex 线程 transcript 到独立 markdown 文件（不写日记） |

---

### 记忆维护

| 命令 | 用途 | 何时执行 |
|------|------|---------|
| `compact-memory` | 把 30 天以前的 Active Hypotheses 移入 Legacy Stream | 每月一次 |

---

## 6. 记忆系统

### 6.1 长期记忆结构（journal/memory.md）

文件分为四个区块：

| 区块 | 用途 | 更新频率 |
|------|------|----------|
| `Stable Profile` | 人格基线、偏好、语言模式 | 低频（月级） |
| `Active Hypotheses (Last 30 Days)` | 最近 30 天的高相关动态模式 | 每次有洞察时追加 |
| `Canonical Memories` | 多次验证后沉淀的高置信记忆 | 手动提升 |
| `journal/memory-archive.md` | 🌟 冷数据区（过期的假设和历史流均归档于此） | `compact-memory` 自动归档 |

新洞察用 `append-insight` 命令追加到 `journal/insights.jsonl`（append-only，结构化存储）。如需同时写入长期记忆的 Active Hypotheses 区块，另运行 `writeback-memory`。

两个命令职责分明：
- `append-insight` — 只写 `journal/insights.jsonl`
- `writeback-memory` — 只写 `journal/memory.md`

### 6.2 insights.jsonl 格式

每行一个 JSON 对象，第一行为 schema 定义：

```jsonl
{"_schema": "insight", "_version": "1.0", "_description": "Append-only log of cognitive insights."}
{"id": "insight_2026-03-28_118", "date": "2026-03-28", "type": "insight", "name": "Apple Watch 生物预警效力验证", "content": "...", "refs": ["2026-03-28"], "status": "active"}
```

字段说明：
- `type`：洞察类型（`insight` / `cognition` / `pattern` / `behavior` 等）
- `name`：英文名称（从内容中括号自动提取，如 `(Self-Duality Poem)`）
- `refs`：关联的日记日期（从 `[[YYYY-MM-DD]]` 自动提取）
- `status`：`active`（默认）/ `archived`

---

## 7. 日程投影

### 7.1 Legacy schedule files

```
quant/schedules/
  2026/
    03/
      sched-2026-03-30.md    ← 命名格式：sched-YYYY-MM-DD.md
    04/
      sched-2026-04-01.md
```

**命名前缀 `sched-` 的原因：** 避免与日记文件（`YYYY-MM-DD.md`）在 Obsidian 中产生 wikilink 命名冲突。

### 7.2 Legacy roadmap pointer

`quant/roadmap.md` 中的 Active Schedule 区块只存指针：

```markdown
## ⚡️ Active Schedule
*Current: [[sched-2026-03-30]]* → `quant/schedules/2026/03/sched-2026-03-30.md`

> 日程文件统一管理于 `quant/schedules/YYYY/MM/sched-YYYY-MM-DD.md`，此处只保留指针。
```

### 7.3 Conversational projection vs legacy generator

v4.3 的默认日程是 conversational projection：

1. 读 `life-board.md`
2. 看每个 active track 的 `Next artifact`
3. 结合当日状态，选出今天最重要的一件事
4. 用日记分析或对话给出轻量计划

这条默认路径不要求 Quant Feedback、XP targets 或脚本生成。

`update-schedule` 保留为 legacy/manual schedule generator。`update-schedule --date YYYY-MM-DD` 仍有两层规则：

1. 只有当 `YYYY-MM-DD` 对应日记中的 `## 📊 Legacy Quant Feedback`（或旧标题 `## 📊 Quant Protocol Feedback`）**有实际填写内容**时，命令才会生成 / 刷新次日日程。
2. 一旦门槛通过，目标 `sched-*.md` 文件在重复运行时会按最新状态**重新生成**，而不是“已存在就跳过”。

若你需要绕过日记反馈门槛，直接手动指定某一天的日程，使用：

```bash
python3 scripts/copilot.py update-schedule --target-date YYYY-MM-DD
```

---

## 8. Quant 任务产物协议

每个 XP 任务的完整生命周期：

### Step 1: 开工前 — 生成 Mission Guide

```bash
python3 scripts/copilot.py quant-mission --xp XP-64 --date 2026-03-30
```

AI 读取生成的 `xp-64-mission-guide.md`，填充 `<!-- AI_FILL: ... -->` 区块，生成教学文档。

Mission Guide 必须包含（`prompts/quant-mode.md` Learning Collaboration Protocol）：
- **Conceptual Why** — 这个知识点为什么重要，在 Quant 工作流中的位置
- **Core Formula** — 核心公式，附直觉解释（不允许裸公式）
- **Starter Scaffold** — 代码脚手架或推导骨架，含 `# TODO` 注释
- **Checkpoint Questions** — 关键节点的自检问题
- **Pitfall Alerts** — 这个 XP 特有的常见陷阱

大段代码或数学推导必须存为**独立副产品文件**（如 `xp-64-derivation-guide.md`），在 Mission Guide 中链接。

### Step 2: 执行中 — 追加笔记

手动编辑或新建 `quant/arsenal/xp-64-session-notes.md`，以 append-only 方式记录执行中的问题、决策、洞察等。

（`quant-note` 子命令已退役；脚本当前只保留 `quant-mission` 和 `quant-question-link`。）

### Step 3: 收工 — 生成 Summary

手动创建或编辑 `quant/arsenal/xp-64-summary.md`，总结该 XP 的学习成果与关键收获。

（`quant-summary` 子命令已退役；Summary 需要手动生成。）

### 产物文件位置

```
quant/arsenal/
  xp-64-mission-guide.md      ← 教学文档（含 AI 填充内容）
  xp-64-session-notes.md      ← 执行笔记（append-only）
  xp-64-summary.md            ← 完结总结（手动编写）
  xp-64-derivation-guide.md   ← 副产品（可选）
```

---

## 9. 写回守则

| 规则 | 说明 |
|------|------|
| 临时文件路径自定 | 写回前先把内容存为临时文件，路径可在工作区内任意选择 |
| 禁用 heredoc | 禁止 `--input-file - <<EOF ... EOF` 格式 |
| 日记边界 | 用户正文补充进 `Daily Log` / `Thoughts & Reflections`；Kai 原始对话手动粘贴到 `💬 From Kai`；Codex / Claudian 对话用 `writeback-ai-day` 写入 trace 并索引；夜间分析进 `What Life Copilot Said` |
| JSONL 只追加 | `insights.jsonl` 等 JSONL 文件只能 append，禁止行级编辑或删除 |
| 归档代替删除 | 需要"删除"一条 insight 时，将其 `status` 改为 `"archived"` |

---

## 10. 文件格式约定

| 格式 | 用途 | 特性 |
|------|------|------|
| **JSONL** | append-only 日志（insights.jsonl） | 每行自包含，流式友好，天然防覆写 |
| **Markdown** | 叙事内容（日记、记忆、指南） | Obsidian 兼容，可 diff，wikilink 支持 |

**JSONL schema 行约定：** 每个 JSONL 文件第一行为 schema 定义：
```json
{"_schema": "insight", "_version": "1.0", "_description": "..."}
```

---

## 11. 日常维护

### 每日

v4.3 的日常入口不是 Quant script loop，而是轻量检查：

1. 读 `life-board.md`，确认 active tracks 是否仍然准确。
2. 如果 `inbox/` 有新文件，按 `inbox/00-readme.md` flush。
3. 如果用户要日程，基于 board 做 conversational projection。
4. 只有明确进入 legacy/manual Quant 时，才使用 `sync-quant-state` 或 `update-schedule`。

如果使用 `sync-quant-state --date` / `update-schedule --date`，仍要检查当天日记里的 `## 📊 Legacy Quant Feedback`（或旧标题 `## 📊 Quant Protocol Feedback`）是否已填写。默认日记模板不再包含该 section——需要时先从 `templates/legacy-quant-feedback.md` 复制 snippet 到当天日记。空模板不会触发 state 或 schedule 更新。单独填写 `Request for Tomorrow` 不再构成有效反馈。

### 每月（手动）

```bash
# 压缩长期记忆：把 30 天前的 Active Hypotheses 从热内存剥离并存入 memory-archive.md 冷归档
python3 scripts/copilot.py compact-memory
```

---

## 12. Negative Backlog

以下项目已从 v4.3 默认流程退役，但保留在代码库中：

| 退役项 | 当前处理 |
|---|---|
| `sync-quant-state --date` 默认日常入口 | 保留脚本 gate，只在 legacy/manual Quant 时使用 |
| `update-schedule --date` 默认日常入口 | 保留为 legacy schedule generator；默认计划改为 conversational projection |
| FULL POWER 每日默认 | 改为 phase-aware planning |
| XP-only schedule projection | Active Board 支持多 track |
| 硬模式触发 | 改为上下文软路由 |
| `quant/roadmap.md` 作为生活全景 | 改由 `life-board.md` 承担 |

退役不是删除。如果 Henry 重新进入训练阶段或创建新 Quant roadmap，可以重新启用这些规则。

---

## 13. 常见问题

**Q: v4.3 为什么不默认运行 `sync-quant-state` / `update-schedule`？**
A: 因为 quant roadmap 已在 [[2026-06-03]] 完成。默认生活规划现在由 `life-board.md` 和 conversational projection 驱动；旧脚本保留给 legacy Quant、未来新训练阶段或明确手动 override。

**Q: 为什么 `update-schedule` 没有生成新日程？**
A: 如果你运行的是 legacy 命令 `update-schedule --date YYYY-MM-DD`，最常见原因是当日日记里根本没有 `## 📊 Legacy Quant Feedback` section（默认模板已不再包含它），或虽然有该 section 但下面仍是模板空位。只有**已填写**的反馈才会触发这条命令。需要时先从 `templates/legacy-quant-feedback.md` 复制 snippet 到当天日记。像 `___%`、`High/Low`、空的 `Roadblocks` / `Request for Tomorrow` 都不算有效内容。此外，单独填写 `Request for Tomorrow` 不再构成有效反馈——至少需要一个执行分数或能量字段。

**Q: 为什么我明明看到了 Quant Feedback section，还是没有更新 state / schedule？**
A: 因为”有 section”不等于”有反馈”。脚本现在看的是解析后的真实值，不是标题本身。只有至少一个执行字段（morning/afternoon/evening scores、roadblocks、energy）被实际填写，才会更新 `quant/state.md` 或次日日程。单独填写 `Request for Tomorrow` 不再构成有效反馈——它是生活计划 hint，不是 Quant 执行证据。

**Q: 我想不依赖当天日记，强制生成某一天的 schedule，怎么做？**
A: 使用：
```bash
python3 scripts/copilot.py update-schedule --target-date YYYY-MM-DD
```
这条命令会绕过基于日记的反馈门槛。

**Q: 我想在当天日记没有填 Quant Feedback 时，手动强制更新 quant-state，怎么做？**
A: 使用：
```bash
python3 scripts/copilot.py sync-quant-state \
  --date YYYY-MM-DD \
  --allow-missing-journal \
  --chat-note "manual override note"
```
`--chat-note` 是显式 manual override；没有它时，空白模板不会触发 state 更新。

**Q: v4.0 为什么不再有 prepare-* 命令？**
A: Claude Code 可以直接读文件，预生成 80KB 上下文包反而引入了大量噪声。现在直读 3-5 个源文件（~15-25KB），信噪比更高，速度更快。

**Q: Seed 为什么不直接放在 `life-board.md`？**
A: Board 应保持清爽，只显示 active tracks。Seed inventory 放在 `seeds/00-index.md`，避免 parked ideas 把当前工作面板挤满。

**Q: 为什么 Obsidian 里的 `[[2026-03-30]]` 指向日记而不是日程？**
A: 日程文件命名为 `sched-2026-03-30.md`，有 `sched-` 前缀，避免冲突。引用日程用 `[[sched-2026-03-30]]`。

**Q: 如何手动写入一条洞察？**
```bash
python3 scripts/copilot.py append-insight \
  --date 2026-03-30 \
  --kind insight \
  --content "你的洞察内容，支持 [[2026-03-30]] 这样的 wikilink 引用"
```

**Q: 如何查看某天的日程？**
直接打开 `quant/schedules/YYYY/MM/sched-YYYY-MM-DD.md`，或在 Obsidian 中搜索 `sched-`。

---

## 14. GitHub 部署与隐私保护

Life Copilot v4.3 支持**“开源系统引擎，私有核心数据”**的代码库部署架构。

根目录下的 `.gitignore` 拦截了以下敏感数据进入版本库：
- 日记区 (`journal/`)：含所有记忆池与每日复盘
- Quant 个人内容区 (`quant/` 下的各项目录、学习资料、简历和明确的目标大纲)
- 附件及缓冲区 (`resources/`, `inbox/`, `archives/`, `.obsidian/`)

提交前仍要运行 `git status --short`。`life-board.md`、`seeds/`、RFC 等 v4.3 新文件是否提交，取决于你想把它们视为系统文档还是私人工作面板。

---

*最后更新：[[2026-06-04]]*
