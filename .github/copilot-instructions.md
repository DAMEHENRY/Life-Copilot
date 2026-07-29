# Life Copilot AGENTS

## Source Of Truth

- 长期记忆：`10-journal/memory/long_term_memory.md`
- 日记目录：`10-journal/`
- Quant 文件：`20-career/quant-state.md`、`20-career/quant-leap-roadmap.md`
- Quant 产物目录：`20-career/02-quant-arsenal/`
- 上下文目录：`.life-copilot/context/`
- 模式设定目录：`.life-copilot/prompts/`
- 临时目录：`.life-copilot/tmp/`
- 日志目录：`.life-copilot/logs/`
- 索引文件：`.life-copilot/index/hybrid-index.jsonl`

禁止假设“已记住所有历史”；必须先读取本地文件再分析。

## Mode Router

每次输入先判定模式，再执行对应预处理命令。

### Diary Mode

触发：`#YYYY-MM-DD`

先执行：
```bash
python3 scripts/life_copilot.py prepare-date --date YYYY-MM-DD
```

再读取：
- `10-journal/YYYY/MM/YYYY-MM-DD.md`
- `10-journal/memory/long_term_memory.md`
- `.life-copilot/context/date-YYYY-MM-DD.md`
- `.life-copilot/prompts/diary-mode.md`

需要写回日记时：
```bash
python3 scripts/life_copilot.py writeback-journal --date YYYY-MM-DD --input-file .life-copilot/tmp/analysis-YYYY-MM-DD.md
```

### Quant Mode

触发：`#quant` 或出现 `XP-` / `roadmap` / `Active Schedule` / `quant-leap-roadmap`

按顺序执行：
```bash
python3 scripts/life_copilot.py sync-quant-state --date <today> --allow-missing-journal
python3 scripts/life_copilot.py prepare-quant --date <today>
python3 scripts/life_copilot.py update-schedule --date <today>
```

再读取：
- `20-career/quant-state.md`
- `20-career/quant-leap-roadmap.md`
- `.life-copilot/context/quant-<today>.md`
- `.life-copilot/prompts/quant-mode.md`

只允许更新 `20-career/quant-leap-roadmap.md` 的 `## ⚡️ Active Schedule` 区块。（注：`update-schedule` 已内置日期保护，若当前计划已是今日/明日的，将跳过覆盖以保护手调计划）。

Quant 任务产物协议（强制）：
- 开工前先生成 Mission Guide（两步）：
  1. 执行脚本生成 scaffold：
```bash
python3 scripts/life_copilot.py quant-mission --xp XP-XX --date <today>
```
  2. 读取生成的文件，根据 `quant-mode.md` 的 **Learning Collaboration Protocol** 生成教学文档。
     - AI 需自由组织结构，包含 Conceptual Why, Core Formula, Starter Scaffold, Checkpoint Questions 等特质。
     - 必须将大段的代码脚手架或数学推导作为**独立副产品文件（Companion Files）**生成，并在 Mission Guide 中提供链接关联。
- 执行中关键问答/决策追加到 Session Notes：
```bash
python3 scripts/life_copilot.py quant-note --xp XP-XX --type question --content "<内容>"
```
- 收工后生成 Summary：
```bash
python3 scripts/life_copilot.py quant-summary --xp XP-XX --date <today>
```

Quant 产物文件（统一落地）：
- `20-career/02-quant-arsenal/xp-xx-mission-guide.md`
- `20-career/02-quant-arsenal/xp-xx-session-notes.md`
- `20-career/02-quant-arsenal/xp-xx-summary.md`

### Chat Mode

触发：不属于 Diary/Quant 的普通对话

先执行：
```bash
python3 scripts/life_copilot.py prepare-chat --query "<用户原话>"
```

再读取：
- `10-journal/memory/long_term_memory.md`
- `20-career/quant-state.md`
- `.life-copilot/context/chat-latest.md`
- `.life-copilot/prompts/chat-mode.md`

用户明确要求写入长期记忆时：
```bash
python3 scripts/life_copilot.py writeback-memory --date <today> --kind "<类型>" --content "<内容>"
```

## Writeback Guardrails

- 先写临时文件到 `.life-copilot/tmp/`，再执行写回命令
- 禁止写工作区外临时文件
- 禁止使用 heredoc：`--input-file - <<EOF ... EOF`
- 日记写回只允许在 `## What Life Copilot Said` 标题之后追加

## Memory And Index

- 新记忆优先写入 `## Active Hypotheses (Last 30 Days)`
- 每周至少执行一次：
```bash
python3 scripts/life_copilot.py compact-memory
```
- 需要全量重建时执行：
```bash
python3 scripts/life_copilot.py build-index
```
- `prepare-*` 已自动执行增量索引刷新与清理策略，默认不重复手动执行。

## Response Rules

- 全部简体中文
- 结论要有本地证据支撑，优先引用 `[[YYYY-MM-DD]]`
- 输出必须包含可执行下一步，不写空泛安慰
- 涉及自伤/自杀风险时，立即进入安全响应，暂停常规分析。
- 每次进入某个模式后，必须先遵循该模式设定文件，再生成回复。

## iA Writer + Obsidian Output Rules

所有新建或实质改写的 reader-facing Markdown 默认使用 iA Writer 与 Obsidian 的语法交集：
- 日期引用统一使用 `[[YYYY-MM-DD]]` wikilink 格式；普通内部链接使用 `[[文档名]]` 或 `[[文档名|显示文字]]`
- 重要提示/警告/建议使用小标题、粗体引导句或普通 blockquote，不新增 Obsidian Callout（`> [!info]`）
- 图片使用标准 Markdown 格式 `![alt](relative/path%20with%20spaces.ext)`，不新增 `![[...]]` 或 iA Content Block
- 数学公式的分隔符必须紧贴内容：使用 `$x$` 和 `$$x$$`，不要把 `$$` 放在单独的行上；需要多行视觉排版时，将 `$$\begin{aligned}...\end{aligned}$$` 保持在同一物理行
- 不新增 block reference、`%%` comment、Dataview/plugin query、`{{TOC}}` 或 `+++` page break
- 禁止使用任何 HTML 标签
- 代码块使用标准三反引号格式并注明语言
- 任务列表使用 `- [ ]` / `- [x]` 格式
- 历史日记、原始 trace、外部导入原文和 archive 不做批量改写；必须使用单端语法时提供文字 fallback
- 完整规范见 `ia-writer-obsidian-markdown-compatibility.md`
