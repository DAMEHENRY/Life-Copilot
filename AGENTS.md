# Life Copilot — Codex

## 文件地图

| 概念         | 路径                                            |
| ---------- | --------------------------------------------- |
| 日记         | `journal/YYYY/MM/YYYY-MM-DD.md`               |
| Kai 原始对话  | 日记内 `## From Kai`（手动粘贴 Telegram 当天对话） |
| 长期记忆（热）    | `journal/memory.md`                           |
| 长期记忆（冷）    | `journal/memory-archive.md`                   |
| 洞察日志       | `journal/insights.jsonl`（append-only）         |
| Quant 路线   | `quant/roadmap.md`                            |
| Quant 状态   | `quant/state.md`                              |
| XP 产物      | `quant/arsenal/xp-XX-{type}.md`               |
| 日程         | `quant/schedules/YYYY/MM/sched-YYYY-MM-DD.md` |
| 日记模式设定     | `prompts/diary-mode.md`                       |
| Quant 模式设定 | `prompts/quant-mode.md`                       |
| Chat 模式设定  | `prompts/chat-mode.md`                        |
| 脚本         | `scripts/copilot.py`                          |

禁止假设"已记住所有历史"；必须先读取本地文件再分析。

## 模式路由

### Diary Mode

触发：`#YYYY-MM-DD`

1. 读 `prompts/diary-mode.md`
2. 读 `journal/YYYY/MM/YYYY-MM-DD.md`
   - 若有 `## From Kai`，把它视为当天 Telegram 原始对话流证据层，保留 Henry / Kai 的说话人区分
3. 读 `journal/memory.md`（热记忆：Active Hypotheses + Canonical）
4. 读目标日期前后 2-3 天的日记（提供时间上下文）
5. 从当天内容先抽出 `1-2` 条主线主题
6. 围绕主线主题默认继续查三层历史：
   - `journal/insights.jsonl`（索引层：已有命名模式、refs、验证线索）
   - `journal/memory-archive.md`（冷归档：仍 relevant 的旧模式）
   - `journal/` 目录（原始样本日记：关键词、变体表达、相关意象）
7. 若命中文档里包含 `[[...]]` wikilink，继续跟读一层
8. 回复时必须明确区分：这是旧模式复现、旧假设验证、旧模式修正，还是新模式出现
9. 回复结尾默认做一次简短 memory audit：`无需写入` / `值得记录为验证` / `值得记录为新模式`
10. 按 diary-mode.md 的规则回复

需要写回日记时，先写临时文件再执行：
```bash
python3 scripts/copilot.py writeback-journal --date YYYY-MM-DD --input-file <临时文件路径>
```

**Diary 写回语义（强制区分）**
- 如果写回内容是 **对该篇日记的分析 / 镜子 / Copilot 建议**，一律使用 `writeback-journal`，写入 `## What Life Copilot Said`。
- 如果写回内容是 **想作为“我自己的日记正文补充”保存的对话片段/想法/后续澄清**，才使用 `writeback-thought`，它会写进 `## 📝 Daily Log` 与 `## 💭 Thoughts & Reflections`。
- 如果内容是 **当天 Telegram 上与 Kai 的原始对话**，手动粘贴到 `## From Kai`；当前版本不使用脚本自动整理或改写。
- **禁止** 用 `writeback-thought` 去写 Copilot 分析；**禁止** 用 `writeback-journal` 去伪装用户口吻续写正文。

### Quant Mode

触发：`#quant` 或出现 `XP-` / `roadmap` / `Active Schedule` / `quant-leap-roadmap`

1. 执行：
```bash
python3 scripts/copilot.py sync-quant-state --date <today> --allow-missing-journal
python3 scripts/copilot.py update-schedule --date <today>
```
说明：
- `update-schedule --date <today>` 的语义是“把 `<today>` 当基准日，生成明日日程”。
- 若需要直接生成或指向某个明确日期的日程，使用 `python3 scripts/copilot.py update-schedule --target-date YYYY-MM-DD`。
2. 读 `prompts/quant-mode.md`
3. 读 `quant/state.md`
4. 读 `quant/roadmap.md`（只关注未完成 XP + 里程碑）
5. 若讨论具体 XP，读对应 arsenal 文件
6. 按 quant-mode.md 的规则回复

### Chat Mode

触发：不属于 Diary/Quant 的普通对话

1. 读 `prompts/chat-mode.md`
2. 读 `journal/memory.md`（热记忆：Active Hypotheses + Canonical）
3. 若需要历史证据，用 Grep 搜索 `journal/memory-archive.md` 或 `journal/` 目录
4. 按 chat-mode.md 的规则回复

## 通用护栏

- **语言**：日记/聊天全部简体中文，Quant 用英文
- **Obsidian 兼容**：`[[YYYY-MM-DD]]` wikilink、Obsidian Callout（`> [!info]`）、无 HTML
- **Wikilink 主动链接**：输出中应主动使用 `[[文档名]]` 链接到已存在的文档（日记、XP 文件、roadmap 等），目标是构建丰富的 Obsidian Graph View。不要凭空创造链接，只链接确实存在的文件。
- **Wikilink 解析（深度 1）**：读取任何文档时，若文档内包含 `[[...]]` wikilink，需额外读取这些被链接的文档（仅一层，不递归——即被链接文档中的 wikilink 不再跟进）。
- **记忆存储**：热记忆在 `journal/memory.md`，冷归档在 `journal/memory-archive.md`，不使用系统级记忆工具
- **洞察日志角色**：`journal/insights.jsonl` 是历史检索的索引层，不是最终面向用户的主要引用层；面向用户优先落到 `[[YYYY-MM-DD]]`
- **证据标准**：结论必须有本地证据支撑，引用 `[[YYYY-MM-DD]]`；证据不足时明确说明
- **安全协议**：涉及自伤/自杀风险时，立即进入安全响应，暂停常规分析
- **输出要求**：必须包含可执行下一步，不写空泛安慰
- **写回护栏**：禁止使用 heredoc（`--input-file - <<EOF`）；用户正文补充写入 `Daily Log` / `Thoughts & Reflections`，Kai 原始对话手动粘贴到 `From Kai`，Copilot 夜间分析写入 `What Life Copilot Said`

## 写入长期记忆

```bash
python3 scripts/copilot.py writeback-memory --date <today> --kind "<类型>" --content "<内容>"
```

新洞察同时写入 JSONL：
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
- 不用于粘贴 Kai / Telegram 原始对话；Kai 原始对话直接放入 `## From Kai`
- 不用于 `## What Life Copilot Said` 分析写回

## XP 完成协议

用户确认 XP 完成时：
1. 在 roadmap 中将 `- [ ]` 改为 `- [x]`，行末追加 `(Completed: YYYY-MM-DD)`
2. 执行：
```bash
python3 scripts/copilot.py sync-roadmap-stats
```
