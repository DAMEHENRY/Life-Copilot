# Life Copilot — Codex

> Version: v4.3 (2026-06-04). See [[life-copilot-v4.3-rfc]] for rationale and migration notes.

## 文件地图

| 概念         | 路径                                            |
| ---------- | --------------------------------------------- |
| 日记         | `journal/YYYY/MM/YYYY-MM-DD.md`               |
| AI 原始对话索引 | 日记内 `## 💬 From Kai`（wikilink 索引到 trace 文件；Telegram/Kai 手动粘贴） |
| AI 对话 trace | `journal/ai-conversations/YYYY/MM/YYYY-MM-DD-{codex,life-claude-renderer}-trace.md` |
| 长期记忆（热）    | `journal/memory.md`                           |
| 长期记忆（冷）    | `journal/memory-archive.md`                   |
| 洞察日志       | `journal/insights.jsonl`（append-only）         |
| Active Board | `life-board.md`                               |
| Seeds        | `seeds/`（候选项目孵化区）                          |
| Quant 路线（历史参考） | `quant/roadmap.md`                       |
| Quant 状态（历史参考） | `quant/state.md`                         |
| XP 产物      | `quant/arsenal/xp-XX-{type}.md`               |
| 日程         | `quant/schedules/YYYY/MM/sched-YYYY-MM-DD.md` |
| 日记模式设定     | `prompts/diary-mode.md`                       |
| Quant 模式设定 | `prompts/quant-mode.md`                       |
| Chat 模式设定  | `prompts/chat-mode.md`                        |
| Study 模式设定 | `prompts/study-mode.md`                       |
| 脚本         | `scripts/copilot.py`                          |

禁止假设"已记住所有历史"；必须先读取本地文件再分析。

## 模式路由

> **v4.3 routing philosophy**: mode triggers are **soft suggestions**, not hard gates. The system reads `life-board.md` + `journal/memory.md` + today's diary to decide what matters. When a conversation blends tracks, route by context, not keyword. See [[life-copilot-v4.3-rfc]] §4.

### Index-Guided Routing (v4.3)

Before routing to a specific mode, assess context:
1. Read `life-board.md` — what tracks are active?
2. Read `journal/memory.md` — what hypotheses are hot?
3. Read today's diary (if exists) — what is already in motion?
4. Route based on the intersection, not the keyword.

### Diary Mode

触发（软触发）：`#YYYY-MM-DD`，或对话明显围绕某天的日记 / 情绪复盘

0. 若目标日期日记文件已存在，先执行：
```bash
python3 scripts/copilot.py writeback-ai-day --date YYYY-MM-DD
```
说明：这会把当天全部 Codex 和 Life Claude Renderer 对话归档到 `journal/ai-conversations/YYYY/MM/` 下的独立 trace 文件（`YYYY-MM-DD-codex-trace.md` 和 `YYYY-MM-DD-life-claude-renderer-trace.md`），并在日记 `## 💬 From Kai` 追加 wikilink 索引。脚本按 wikilink 去重，重复分析同一天时不应重复写入。若日记文件不存在或当天无 AI conversations，说明后跳过，不要因此中断分析。历史 `*-claudian-trace.md` 文件是旧版产物，保持不动。
1. 读 `prompts/diary-mode.md`
2. 读 `journal/YYYY/MM/YYYY-MM-DD.md`
   - 若有 `## 💬 From Kai`，把它视为当天 AI 原始对话流证据层，保留 Henry / Kai / Codex 的说话人区分
3. 读 `journal/memory.md`（热记忆：Active Hypotheses + Canonical）
4. 读目标日期前后 2-3 天的日记（提供时间上下文）
5. 从当天内容先抽出 `1-2` 条主线主题
6. 围绕主线主题默认继续查三层历史：
   - `journal/insights.jsonl`（索引层：已有命名模式、refs、验证线索）
   - `journal/memory-archive.md`（冷归档：仍 relevant 的旧模式）
   - `journal/` 目录（原始样本日记：关键词、变体表达、相关意象）
7. 若当天主题涉及实效性外部信息，可联网搜索作为辅助校验
8. 若命中文档里包含 `[[...]]` wikilink，继续跟读一层
9. 回复时必须明确区分：这是旧模式复现、旧假设验证、旧模式修正，还是新模式出现
10. 回复结尾默认做一次简短 memory audit：`无需写入` / `值得记录为验证` / `值得记录为新模式`
11. 按 diary-mode.md 的规则回复

**Diary Mode Completion Contract（默认收尾）**

除非 Henry 明确说“只调查 / 不要写回 / dry run”，完成某天 diary analysis 后必须继续做四个收尾动作：

1. **Analysis writeback**：把当天分析正文写入临时 markdown 文件，然后执行：
```bash
python3 scripts/copilot.py writeback-journal --date YYYY-MM-DD --input-file <临时文件路径>
```
写入内容只包含对当天日记的分析、镜子、建议和 memory audit；不要包含工具日志、执行报告或 inbox audit；不要伪装成 Henry 的日记正文。

2. **Inbox audit / inbox closure check**：读取 `inbox/00-readme.md`，列出 `inbox/` 中待处理文件（忽略 `.DS_Store`、`00-readme.md`、`flush-log.md`），对每个文件给出建议去向、confidence 和 reason。默认只提出建议，不移动或删除文件，除非 Henry 明确要求 flush/move。如果 inbox 为空或无需操作，在回复中简短说明。如果 inbox 有待处理文件且 Henry 明确要求 flush/move，执行后再进入下一步。

3. **Daily Suggestion writeback**：基于 post-inbox-closure 状态产出次日建议，写入另一个临时 markdown 文件，然后执行：
```bash
python3 scripts/copilot.py writeback-daily-suggestion --source-date YYYY-MM-DD --input-file <临时文件路径>
```
输入文件只写建议正文，不要手写 `Generated from ...` provenance；脚本会自动添加。若目标日记已有不同 provenance 或无 provenance 内容，不要自动 `--force`，先报告冲突。

4. **Final response**。

需要写回日记时，先写临时文件再执行：
```bash
python3 scripts/copilot.py writeback-journal --date YYYY-MM-DD --input-file <临时文件路径>
```

**Diary 写回语义（强制区分）**
- 如果写回内容是 **对该篇日记的分析 / 镜子 / Copilot 建议**，一律使用 `writeback-journal`，写入 `## What Life Copilot Said`。
- 如果写回内容是 **想作为“我自己的日记正文补充”保存的对话片段/想法/后续澄清**，才使用 `writeback-thought`，它会写进 `## 💭 Thoughts & Reflections`。
- 如果写回内容是 **基于前一天日记分析生成的次日执行建议**，使用 `writeback-daily-suggestion`，写入目标日日记的 `## 🧭 Daily Suggestion`。建议正文使用目标日语态（`今天` / `today`），应基于 inbox closure 后的状态。`What Life Copilot Said` 只保存对当前日记的分析、镜子和 memory audit，不再承载次日建议。
- 如果内容是 **当天 Telegram 上与 Kai 的原始对话**，手动粘贴到 `## 💬 From Kai`；如果内容是 **当天 Codex 或 Life Claude Renderer conversations**，使用 `writeback-ai-day` 自动归档 trace 文件并在 `## 💬 From Kai` 追加 wikilink 索引。
- **禁止** 用 `writeback-thought` 去写 Copilot 分析；**禁止** 用 `writeback-journal` 去伪装用户口吻续写正文。

### Diary Mode Completion Contract（v4.3）

完成某天的 diary analysis 后，以下四步是**默认收尾动作**，除非 Henry 明确说"只调查 / 不要写回 / dry run"：

**Step 1 — Analysis Writeback（默认执行）**
1. 将分析正文（镜子、memory audit、历史锚点、微行动）写入临时 markdown 文件。
2. 执行：
   ```bash
   python3 scripts/copilot.py writeback-journal --date YYYY-MM-DD --input-file <tmp-analysis-file>
   ```
3. 写入内容只能是对当天日记的分析、镜子、memory audit。**不要**包含工具日志、inbox audit 报告、执行报告，也不要伪装成 Henry 的日记正文。
4. **禁止** heredoc 作为 writeback input；必须先写临时文件再 `--input-file`。
5. **禁止** 使用 `writeback-thought` 写 Copilot 分析。

**Step 2 — Inbox Audit / Inbox Closure Check（默认执行）**
1. 读取 `inbox/00-readme.md`，了解 flush 规则和 destination map。
2. 列出 `inbox/` 里待处理文件；忽略 `.DS_Store`、`00-readme.md`、`flush-log.md`。
3. 对每个待处理文件做轻量判断：建议去向（`journal/`、`quant/` 或相关 project、`resources/`、`seeds/`、`delete`）、confidence、reason。
4. 默认只"提出应该挪到哪里"，不要移动或删除，除非 Henry 明确要求 flush/move。
5. 如果 inbox 为空或无需操作，在回复中简短说明。
6. 如果 Henry 明确要求 flush/move，执行后再进入 Step 3。

**Step 3 — Daily Suggestion Writeback（默认执行）**
1. 基于当天分析和 post-inbox-closure 状态，产出一个短小、可执行、目标日当天可启动的建议。
2. 将建议写入**另一个**临时 markdown 文件。
3. 执行：
   ```bash
   python3 scripts/copilot.py writeback-daily-suggestion --source-date YYYY-MM-DD --input-file <tmp-suggestion-file>
   ```
4. 边界：`What Life Copilot Said` 不承载次日建议；次日建议只进目标日日记的 `## 🧭 Daily Suggestion`。
5. 如果 `writeback-daily-suggestion` 因已有不同 provenance 或无 provenance 内容而失败，**不要**自动 `--force`；报告冲突，让 Henry 决定。

**Step 4 — Final Response**

**Completion Contract 总结**：分析 → 写回分析 → inbox audit / closure check → 写回次日建议 → 最终回复。Inbox audit 在 Daily Suggestion 之前完成，确保建议基于 inbox closure 后的状态。

### Quant Mode

触发（软触发）：`#quant`，或出现 `XP-` / `roadmap` / `Active Schedule`，或对话明显围绕量化学习 / 职业准备

> **Post-roadmap note** (v4.3): The roadmap is 100% complete. `sync-quant-state --date` 和 `update-schedule --date` 不再是默认 daily loop；它们仍保留原本的 Legacy Quant Feedback gate，用作 legacy Quant / 新训练阶段 / 明确手动 override 的工具。一般生活规划先读 `life-board.md`，不要因为出现 `roadmap` 这个词就自动跑 Quant scripts。
>
> **Template note**: Default diary template (`templates/daily-log.md`) no longer includes `## 📊 Legacy Quant Feedback`. When legacy Quant scripts need filled feedback, paste the snippet from `templates/legacy-quant-feedback.md` into today's journal first.

1. 若需要同步量化状态（仅在有新 roadmap 或手动 override 时）：
```bash
python3 scripts/copilot.py sync-quant-state --date <today> --allow-missing-journal --chat-note "manual override"
python3 scripts/copilot.py update-schedule --target-date YYYY-MM-DD
```
2. 读 `prompts/quant-mode.md`
3. 读 `quant/state.md`（历史参考）
4. 读 `quant/roadmap.md`（历史参考；`life-board.md` 是 slow-variable active context map，取代 roadmap 作为生活全景）
5. 若讨论具体 XP，读对应 arsenal 文件
6. 按 quant-mode.md 的规则回复

### Study Mode

触发（软触发）：`#study`，或对话围绕学习主题（阅读、概念理解、代码练习），且不属于 Quant 专业化

1. 读 `prompts/study-mode.md`
2. 读 `journal/memory.md`（热记忆）
3. 搜索已有笔记（`quant/arsenal/` 或相关目录）再决定是否新建
4. 按 study-mode.md 的规则回复

### Chat Mode

触发：不属于 Diary / Quant / Study 的普通对话

1. 读 `prompts/chat-mode.md`
2. 读 `journal/memory.md`（热记忆：Active Hypotheses + Canonical）
3. 若需要历史证据，用 Grep 搜索 `journal/memory-archive.md` 或 `journal/` 目录
4. 按 chat-mode.md 的规则回复

## 通用护栏

- **语言**：日记/聊天全部简体中文，Quant / Study 用英文
- **Obsidian 兼容**：`[[YYYY-MM-DD]]` wikilink、Obsidian Callout（`> [!info]`）、无 HTML
- **Wikilink 主动链接**：输出中应主动使用 `[[文档名]]` 链接到已存在的文档（日记、XP 文件、roadmap、life-board 等），目标是构建丰富的 Obsidian Graph View。不要凭空创造链接，只链接确实存在的文件。
- **Quant 问题链接协议**：Quant Q&A 中出现可复用学习问题时，必须先搜索 `quant/arsenal/` 和 `quant/roadmap.md` 已有文件，再决定是直接链接、扩展已有文件、还是新建笔记。遵循最小必要干预原则，优先用 `[[target#heading|question]]` 别名链接，避免笔记膨胀。用 `python3 scripts/copilot.py quant-question-link --question "..."` 检索候选链接。**注意：`quant-question-link` 只是候选检索，不是最终判断。** Claude/Claudian/Codex 必须打开候选文件读相关段落验证；如果候选不够好，要主动用 `rg` 换同义词、机制词、XP 上下文关键词继续搜。禁止因为候选排名低或列表为空就直接新建文件——排名低意味着需要更多搜索，不是需要更多笔记。
- **Wikilink 解析（深度 1）**：读取任何文档时，若文档内包含 `[[...]]` wikilink，需额外读取这些被链接的文档（仅一层，不递归——即被链接文档中的 wikilink 不再跟进）。
- **记忆存储**：热记忆在 `journal/memory.md`，冷归档在 `journal/memory-archive.md`，不使用系统级记忆工具
- **洞察日志角色**：`journal/insights.jsonl` 是历史检索的索引层，不是最终面向用户的主要引用层；面向用户优先落到 `[[YYYY-MM-DD]]`
- **证据标准**：结论必须有本地证据支撑，引用 `[[YYYY-MM-DD]]`；证据不足时明确说明
- **联网搜索边界**：联网搜索只用于实效性外部事实校验，是辅助证据；不得用外部搜索替代日记、记忆、insights 或 `[[YYYY-MM-DD]]` 历史锚点
- **安全协议**：涉及自伤/自杀风险时，立即进入安全响应，暂停常规分析
- **输出要求**：必须包含可执行下一步，不写空泛安慰
- **写回护栏**：禁止使用 heredoc（`--input-file - <<EOF`）；用户正文补充写入 `Thoughts & Reflections`，Telegram/Kai 原始对话手动粘贴到 `💬 From Kai`，Codex/Life Claude Renderer conversations 用 `writeback-ai-day` 自动归档 trace 文件并在 `💬 From Kai` 追加 wikilink 索引，Copilot 夜间分析写入 `What Life Copilot Said`，次日执行建议（目标日语态）写入 `Daily Suggestion`
- **命名规则**：新建文件夹和普通文档一律使用 lowercase kebab-case；不要使用 `01-xxx` 这类排序前缀。例外：`AGENTS.md`、`CLAUDE.md` 保持大写；`00-index.md`、`00-readme.md` 这类目录入口文件可保留 `00-` 前缀。

## Active Board（v4.3）

`life-board.md` 是 slow-variable active context map，不是 daily planner 或 todo list。它取代了 `quant/roadmap.md` 作为生活全景的隐含假设。

每个 track 有四个字段：
- **Active question** — 当前待回答的问题
- **Next artifact** — 下一个具体产出物
- **Stop condition** — 什么时候算完成
- **Status** — `active` / `waiting` / `paused` / `done`

**更新语义**：Daily projection 读 board，但默认不更新它。Board 更新应 event-driven 且 evidence-based：next artifact 完成、active question 已答/过期、seed promoted、track paused/waiting/done/deleted，或重复日记证据显示 board 不再匹配生活。

**定期审计**：每 7-14 天，或当日记证据显示 drift 时，Life Copilot 应提醒 Henry 并提议最小 patch。Henry 批准后 Copilot 执行维护。Henry 不应手动维护整个 board。审计可提议 add/change/delete/pause/done，但未经 Henry 确认不得自动应用（除非他明确要求）。

当用户问"我现在该做什么"或"我有什么进行中的项目"时，先读 `life-board.md`。

## Seeds 与 Inbox Flush

- `inbox/` 是零摩擦捕获缓冲区
- `seeds/` 是候选项目孵化区（详见 `seeds/00-index.md`）
- Inbox flush 流程：inbox 中高置信但暂不可行的想法 → `seeds/`（带 confidence + reason + source）
- Seeds 在 inbox flush 时审查；3+ 个月未动且不再共鸣的种子可修剪（git history 里还在）
- Seeds 升级为 active track 需满足：有 active question、有 next artifact、有 stop condition、不挤占更高优先级项目

## Schedule as Projection（v4.3）

默认日程是**投影**，不是训练时代那种由脚本自动生成的执行清单。
- 日程投影在日记分析或用户要求时以对话形式产生，不要求 Quant Feedback 或 XP targets
- 读 `life-board.md` → 每个 active track 的 next artifact → 今天最重要的一件事 = 日程投影
- `update-schedule` 脚本仍保留 legacy/manual 用途（尤其是 `--target-date`），但不再是日常默认入口

**Tomorrow Projection Input 语义**：日记模板中的 `## 🧭 Tomorrow Projection Input` 是明天对话投影的低摩擦输入面，不是任务清单或脚本门控。字段说明：
- **Tomorrow anchor**：明天的固定事件、最小产出物，或两者组合；不意味着明天只能有一件事。
- **Context / track**：自然语言如 `study`、`quant`、`body`、`family`、`Life Copilot`、`untracked`，或留空。Henry 不必手动对照 `life-board.md` 分类；Copilot 在分析时自动映射。
- **Known limits**：已知承诺/约束，如 NBA 比赛、睡眠、deadline、身体状态、旅行、家庭电话、注意力残留。不要求预测明天的精力。`unknown` 是可接受的。
- **Do-not-expand**：主动边界——这件事不应变成什么，例如"读论文但不写代码"、"看比赛但之后不刷论坛"、"移动 inbox 笔记但不重构 vault"。

**Daily Suggestion 语义**：`## 🧭 Daily Suggestion` 写入目标日的日记，在目标日当天被阅读。因此：
- 建议正文必须使用**目标日语态**：用 `今天` / `today`，不要用 `明天` / `tomorrow`（除非确实指目标日之后的那天）。
- Provenance 行不变：`> Generated from [[YYYY-MM-DD]] diary analysis.`
- 传递给 `writeback-daily-suggestion` 的 input file 应已经是目标日语态。脚本只写 provenance 和正文，不改代词。

**Daily Suggestion 与 inbox 联动**：Completion Contract 中 inbox audit 在 Daily Suggestion 之前完成。建议正文应基于 inbox closure 后的状态：
- 如果文件在 nightly flush 中已移走，Daily Suggestion 应将其视为已完成上下文，不列为待办。
- 如果 `inbox/` 为空，Daily Suggestion 不应提及 inbox flush。
- 仅当相关文件在 inbox audit 后仍存在于 `inbox/` 且操作确实需要等到目标日时，才将 inbox 操作写入建议。

## Negative Backlog（v4.3）

以下项目已从默认流程退役，但仍保留在代码库中：

| 退役项 | 退役原因 |
|--------|---------|
| `sync-quant-state --date` 默认日常入口 | Post-roadmap，无每日 Legacy Quant Feedback 可填；脚本 gate 保留给 legacy/manual Quant |
| `update-schedule --date` 默认日常入口 | 同上；一般日程改用 conversational projection |
| FULL POWER 每日默认 | 不是每天都是训练日 |
| XP-only 日程投影 | 生活不止 Quant 一个 track |
| 硬模式触发（`#quant`、`#YYYY-MM-DD`） | 对话跨 track；上下文路由更优 |
| `quant/roadmap.md` 作为生活全景 | `life-board.md` 替代此角色 |

> **复用规则**：若新建 Quant roadmap 或 Henry 明确进入训练阶段，以上可重新激活。退役是阶段感知的，不是永久的。

## 写入长期记忆

```bash
python3 scripts/copilot.py writeback-memory --date <today> --kind "<类型>" --content "<内容>"
```

新洞察追加到 JSONL（只写 `journal/insights.jsonl`，不写 memory.md）：
```bash
python3 scripts/copilot.py append-insight --date <today> --kind "<类型>" --content "<内容>"
```

## 将对话写入日记正文

1. 提炼 2-6 个中文字标题
2. 写入临时文件
3. 执行：
```bash
python3 scripts/copilot.py writeback-thought --date YYYY-MM-DD --title "<标题>" --input-file <临时文件路径>
```

适用范围：
- 仅用于“把对话沉淀成用户自己的日记补充”
- 写入 `## 💭 Thoughts & Reflections`，不要求 `Daily Log` 存在
- 不用于粘贴 AI 原始对话；Telegram/Kai 原始对话直接放入 `## 💬 From Kai`，Codex/Life Claude Renderer conversations 使用 `writeback-ai-day`
- 不用于 `## What Life Copilot Said` 分析写回

## 写入次日执行建议

```bash
python3 scripts/copilot.py writeback-daily-suggestion --source-date YYYY-MM-DD --input-file <临时文件路径>
```

适用范围：
- 基于前一天日记分析生成的次日执行建议
- 目标日记不存在时自动从模板创建
- 写入 `## 🧭 Daily Suggestion`，添加 provenance 标注来源日期
- 建议正文使用**目标日语态**（`今天` / `today`），不用 `明天` / `tomorrow`（除非确实指目标日之后的那天）
- 建议正文应基于 inbox closure 后的状态——不在建议中提及已在 inbox audit 中完成的操作
- 重复执行同一 source-date 不会产生重复 section
- `What Life Copilot Said` 只保存对当前日记的分析，不承载次日建议

## XP 完成协议

用户确认 XP 完成时：
1. 在 roadmap 中将 `- [ ]` 改为 `- [x]`，行末追加 `(Completed: YYYY-MM-DD)`
2. 执行：
```bash
python3 scripts/copilot.py sync-roadmap-stats
```
