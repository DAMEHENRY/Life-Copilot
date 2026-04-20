# Life Copilot — 使用手册

> 版本：v4.1（2026-03-30）
> 运行环境：Claude Code (或任意代理 AI) + Obsidian + macOS
> 核心脚本：`scripts/copilot.py`

---

## 目录

1. [系统概览](#1-系统概览)
2. [目录结构](#2-目录结构)
3. [三种对话模式](#3-三种对话模式)
4. [脚本命令全览](#4-脚本命令全览)
5. [记忆系统](#5-记忆系统)
6. [日程管理系统](#6-日程管理系统)
7. [Quant 任务产物协议](#7-quant-任务产物协议)
8. [写回守则](#8-写回守则)
9. [文件格式约定](#9-文件格式约定)
10. [日常维护](#10-日常维护)
11. [常见问题](#11-常见问题)
12. [GitHub 部署与隐私保护](#12-github-部署与隐私保护)

---

## 1. 系统概览

Life Copilot 是一个本地 AI 个人操作系统，运行在 Obsidian 工作目录上，通过 Claude Code 提供智能分析与写回能力。

**核心设计原则（v4.0）：**

- **直读源文件**：Claude Code 直接读取日记、记忆、路线图等原始文件，无需预生成上下文包
- **Append-only 数据**：洞察日志（insights.jsonl）、日程历史只增不改
- **两层路由**：CLAUDE.md（路由 + 文件地图）→ mode prompt（完整行为规则）
- **本地优先**：所有数据在 iCloud 同步的 Obsidian 目录，无外部数据库依赖

**v4.0 相比 v3.0 的主要变化：**

| 项目 | v3.0 | v4.0 |
|------|------|------|
| 脚本行数 | 2,376 行 | 884 行 |
| CLAUDE.md 行数 | 228 行 | ~80 行 |
| 每次交互上下文 | ~80KB（预生成上下文包） | ~15-25KB（直读源文件） |
| 索引系统 | 词法 + 语义双索引（10.8MB） | 无（Grep 替代） |
| 子命令数 | 16 | 11 |
| 间接层数 | 4 层 | 1 层 |

---

## 2. 目录结构

```
Life/                                     ← Obsidian 工作目录根
├── CLAUDE.md                             ← AI 行为规则（文件地图 + 模式路由 + 护栏）
├── README.md                             ← 本文件
├── .gitignore                            ← 🌟 隐私防洪堤（拦截日记、目标与配置不入库）
│
├── scripts/
│   └── copilot.py                        ← 核心脚本（只含写回 + quant 生命周期）
│
├── journal/                              ← 日记模块 (绝对私密区)
│   ├── YYYY/MM/YYYY-MM-DD.md            ← 每日日记
│   ├── memory.md                         ← 长期热记忆（结构化分区，Claude 直读）
│   ├── memory-archive.md                 ← 🌟 记忆冷归档（过期假设自动沉淀至此）
│   └── insights.jsonl                    ← 洞察日志（append-only）
│
├── quant/                                ← 职业/Quant 模块
│   ├── state.md                          ← 当前状态快照（脚本自动同步）
│   ├── roadmap.md                        ← 路线图（含指向日程的指针）
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
│   └── chat-mode.md
│
├── resources/                            ← 学习资料（PDF、课程等）
├── inbox/                                ← 零摩擦捕获缓冲区
├── templates/                            ← 日记模板
└── archives/                             ← 历史存档（论文、竞赛等）
```

---

## 3. 三种对话模式

系统根据输入内容自动判断模式。

---

### 3.1 Diary Mode（日记模式）

**触发方式：** 输入 `#YYYY-MM-DD`（例如 `#2026-03-30`）

**AI 执行流程（无预处理命令）：**

Claude 直接读取：
1. `journal/YYYY/MM/YYYY-MM-DD.md` — 当日日记
2. `journal/memory.md` — 长期记忆（Active Hypotheses 区块优先）
3. 目标日期前后 2-3 天的日记 — 时间上下文
4. 从当天内容抽出 `1-2` 条主线主题
5. `journal/insights.jsonl` — 历史索引层（找已有命名模式、refs、验证线索）
6. `journal/memory-archive.md` — 冷归档（找仍 relevant 的旧模式）
7. 按主线主题 Grep `journal/` — 原始样本日记（关键词、变体表达、相关意象）
8. 若命中文档中有 `[[...]]` wikilink，再额外读取一层
9. `prompts/diary-mode.md` — 模式行为规则

**Diary 输出要求（行为层）：**
- 每篇分析都默认做主题级历史检索，而不是只在想到时才查。
- 回答里要明确区分：这是旧模式复现、旧模式修正、旧假设验证，还是新模式出现。
- 结尾默认做一次简短 memory audit：`无需写入` / `值得记录为验证` / `值得记录为新模式`。
- `journal/insights.jsonl` 只作为检索索引层；面向用户仍优先引用 `[[YYYY-MM-DD]]`。

**写回日记（需要时）：**

```bash
# 先把 AI 分析写到临时文件（路径自定）
# 再执行写回（只允许追加到 ## What Life Copilot Said 之后）
python3 scripts/copilot.py writeback-journal \
  --date 2026-03-30 \
  --input-file <临时文件路径>
```

---

### 3.2 Quant Mode（量化模式）

**触发方式：** 输入 `#quant`，或消息中出现 `XP-` / `roadmap` / `Active Schedule`

**AI 执行流程：**

```bash
# Step 0: 先检查当天日记里的 ## 📊 Quant Protocol Feedback 是否有“实际填写内容”
# 仅标题存在、但下面仍是 ___% / High/Low / 空字段，不算有效反馈

# Step 1: 只有在反馈已填写时，才同步 quant-state
python3 scripts/copilot.py sync-quant-state --date 2026-03-30 --allow-missing-journal

# Step 2: 只有在反馈已填写时，才更新 / 刷新明日日程
python3 scripts/copilot.py update-schedule --date 2026-03-30
```

若当天日记没有已填写的 Quant Feedback：
- 不自动更新 `quant/state.md`
- 不自动生成 / 刷新次日日程
- 仍可读取 `quant/state.md`、`quant/roadmap.md` 做讨论

手动 override：
- 强制同步 quant-state：`sync-quant-state --date YYYY-MM-DD --allow-missing-journal --chat-note "..."`
- 强制生成 / 指向某天日程：`update-schedule --target-date YYYY-MM-DD`

然后 Claude 直接读取：
- `quant/state.md` — 当前状态
- `quant/roadmap.md` — 路线图（只关注未完成 XP + 里程碑）
- 具体 XP 的 `quant/arsenal/` 文件（若讨论具体任务）
- `prompts/quant-mode.md` — 模式行为规则

---

### 3.3 Chat Mode（通用对话模式）

**触发方式：** 不属于 Diary/Quant 的普通对话

Claude 直接读取：
- `journal/memory.md` — 长期记忆
- 按需 Grep 搜索 `journal/` 目录获取历史证据
- `prompts/chat-mode.md` — 模式行为规则

---

## 4. 脚本命令全览

所有命令格式：`python3 scripts/copilot.py <subcommand> [options]`

### Quant 状态管理

| 命令 | 用途 |
|------|------|
| `sync-quant-state --date YYYY-MM-DD [--allow-missing-journal] [--chat-note "..."]` | 从当日日记的**已填写** Quant Feedback 同步 state.md；若日记空白/缺失但你显式提供 `--chat-note`，可作为手动 override |
| `update-schedule --date YYYY-MM-DD` | 以该日期作为基准日，在当日日记存在**已填写** Quant Feedback 时生成 / 刷新次日日程并更新 roadmap 指针 |
| `update-schedule --target-date YYYY-MM-DD` | 手动 override：直接生成或指向指定日期的日程文件，不走日记反馈门槛 |
| `sync-roadmap-stats` | 重算 XP 完成率并更新 roadmap 头部 Total Readiness |

---

### Quant 任务产物

| 命令 | 用途 | 输出文件 |
|------|------|----------|
| `quant-mission --xp XP-XX [--date YYYY-MM-DD] [--force]` | 生成 XP 任务 Mission Guide 脚手架 | `quant/arsenal/xp-xx-mission-guide.md` |
| `quant-note --xp XP-XX --type <类型> --content "<内容>"` | 追加执行笔记 | `quant/arsenal/xp-xx-session-notes.md` |
| `quant-summary --xp XP-XX [--date YYYY-MM-DD] [--force]` | 生成 XP 完结总结 | `quant/arsenal/xp-xx-summary.md` |

`--type` 可选值：`question` / `decision` / `issue` / `result` / `insight`

---

### 记忆写回

| 命令 | 用途 |
|------|------|
| `writeback-journal --date YYYY-MM-DD --input-file <path>` | 把 AI 分析写回日记（只追加到 `## What Life Copilot Said` 之后） |
| `writeback-thought --date YYYY-MM-DD --title "<标题>" --input-file <path>` | 把对话内容写入日记 Thoughts & Reflections，并同步更新 Daily Log |
| `writeback-memory --date YYYY-MM-DD --kind "<类型>" --content "<内容>"` | 写入长期记忆 memory.md |
| `append-insight --date YYYY-MM-DD --kind "<类型>" --content "<内容>"` | **推荐**：同时写入 insights.jsonl + memory.md |

---

### 记忆维护

| 命令 | 用途 | 何时执行 |
|------|------|---------|
| `compact-memory` | 把 30 天以前的 Active Hypotheses 移入 Legacy Stream | 每月一次 |

---

## 5. 记忆系统

### 5.1 长期记忆结构（journal/memory.md）

文件分为四个区块：

| 区块 | 用途 | 更新频率 |
|------|------|----------|
| `Stable Profile` | 人格基线、偏好、语言模式 | 低频（月级） |
| `Active Hypotheses (Last 30 Days)` | 最近 30 天的高相关动态模式 | 每次有洞察时追加 |
| `Canonical Memories` | 多次验证后沉淀的高置信记忆 | 手动提升 |
| `journal/memory-archive.md` | 🌟 冷数据区（过期的假设和历史流均归档于此） | `compact-memory` 自动归档 |

新洞察**推荐**用 `append-insight` 命令写入，同时更新两个地方：
1. `journal/insights.jsonl`（append-only，结构化存储）
2. `journal/memory.md` 的 Active Hypotheses 区块

### 5.2 insights.jsonl 格式

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

## 6. 日程管理系统

### 6.1 文件结构

```
quant/schedules/
  2026/
    03/
      sched-2026-03-30.md    ← 命名格式：sched-YYYY-MM-DD.md
    04/
      sched-2026-04-01.md
```

**命名前缀 `sched-` 的原因：** 避免与日记文件（`YYYY-MM-DD.md`）在 Obsidian 中产生 wikilink 命名冲突。

### 6.2 roadmap 指针

`quant/roadmap.md` 中的 Active Schedule 区块只存指针：

```markdown
## ⚡️ Active Schedule
*Current: [[sched-2026-03-30]]* → `quant/schedules/2026/03/sched-2026-03-30.md`

> 日程文件统一管理于 `quant/schedules/YYYY/MM/sched-YYYY-MM-DD.md`，此处只保留指针。
```

### 6.3 日程生成门槛与刷新机制

`update-schedule --date YYYY-MM-DD` 现在有两层规则：

1. 只有当 `YYYY-MM-DD` 对应日记中的 `## 📊 Quant Protocol Feedback` **有实际填写内容**时，命令才会生成 / 刷新次日日程。
2. 一旦门槛通过，目标 `sched-*.md` 文件在重复运行时会按最新状态**重新生成**，而不是“已存在就跳过”。

若你需要绕过日记反馈门槛，直接手动指定某一天的日程，使用：

```bash
python3 scripts/copilot.py update-schedule --target-date YYYY-MM-DD
```

---

## 7. Quant 任务产物协议

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

```bash
python3 scripts/copilot.py quant-note \
  --xp XP-64 \
  --type question \
  --content "行列式为 0 时为什么矩阵不可逆？"
```

### Step 3: 收工 — 生成 Summary

```bash
python3 scripts/copilot.py quant-summary --xp XP-64 --date 2026-03-30
```

Summary 需要显式手动生成；`sync-quant-state` 不会自动代替你运行 `quant-summary`。

### 产物文件位置

```
quant/arsenal/
  xp-64-mission-guide.md      ← 教学文档（含 AI 填充内容）
  xp-64-session-notes.md      ← 执行笔记（append-only）
  xp-64-summary.md            ← 完结总结（自动生成）
  xp-64-derivation-guide.md   ← 副产品（可选）
```

---

## 8. 写回守则

| 规则 | 说明 |
|------|------|
| 临时文件路径自定 | 写回前先把内容存为临时文件，路径可在工作区内任意选择 |
| 禁用 heredoc | 禁止 `--input-file - <<EOF ... EOF` 格式 |
| 日记边界 | 只能在 `## What Life Copilot Said` 标题之后追加 |
| JSONL 只追加 | `insights.jsonl` 等 JSONL 文件只能 append，禁止行级编辑或删除 |
| 归档代替删除 | 需要"删除"一条 insight 时，将其 `status` 改为 `"archived"` |

---

## 9. 文件格式约定

| 格式 | 用途 | 特性 |
|------|------|------|
| **JSONL** | append-only 日志（insights.jsonl） | 每行自包含，流式友好，天然防覆写 |
| **Markdown** | 叙事内容（日记、记忆、指南） | Obsidian 兼容，可 diff，wikilink 支持 |

**JSONL schema 行约定：** 每个 JSONL 文件第一行为 schema 定义：
```json
{"_schema": "insight", "_version": "1.0", "_description": "..."}
```

---

## 10. 日常维护

### 每日
进入 Quant Mode 后，应先检查当天日记里的 `## 📊 Quant Protocol Feedback` 是否已填写。只有在反馈 section 至少有一个真实值时，才运行：

```bash
python3 scripts/copilot.py sync-quant-state --date YYYY-MM-DD --allow-missing-journal
python3 scripts/copilot.py update-schedule --date YYYY-MM-DD
```

如果只是模板空位，则跳过这两条命令，不自动改写 `quant/state.md` 或次日日程。

### 每月（手动）

```bash
# 压缩长期记忆：把 30 天前的 Active Hypotheses 从热内存剥离并存入 memory-archive.md 冷归档
python3 scripts/copilot.py compact-memory
```

---

## 11. 常见问题

**Q: 为什么 `update-schedule` 没有生成新日程？**
A: 最常见原因是：当日日记虽然保留了 `## 📊 Quant Protocol Feedback` 标题，但下面仍是模板空位。只有**已填写**的反馈才会触发 `update-schedule --date YYYY-MM-DD`。像 `___%`、`High/Low`、空的 `Roadblocks` / `Request for Tomorrow` 都不算有效内容。

**Q: 为什么我明明看到了 Quant Feedback section，还是没有更新 state / schedule？**
A: 因为“有 section”不等于“有反馈”。脚本现在看的是解析后的真实值，不是标题本身。只有至少一个字段被实际填写，才会更新 `quant/state.md` 或次日日程。

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

## 12. GitHub 部署与隐私保护

Life Copilot v4.1 原生支持**“开源系统引擎，私有核心数据”**的代码库部署架构。

根目录下的 `.gitignore` 作为一个硬性“防洪堤”，彻底拦截了以下敏感数据进入版本库：
- 日记区 (`journal/`)：含所有记忆池与每日复盘
- Quant 个人内容区 (`quant/` 下的各项目录、学习资料、简历和明确的目标大纲)
- 附件及缓冲区 (`resources/`, `inbox/`, `archives/`, `.obsidian/`)

**无负担的极客部署：**
在终端直接无脑执行 `git add .` -> `git push` 即可。Git 只会提取并推送如 `scripts/`、`prompts/` 等驱动框架，完美开源工作流，同时绝对保护你的生活隐私。

---

*最后更新：[[2026-03-30]]*
