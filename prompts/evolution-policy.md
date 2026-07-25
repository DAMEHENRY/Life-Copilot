# Life Copilot Evolution Policy (v4.4)

## Purpose

Life Copilot 可以从真实使用中修正低风险规则，但不能借“自我改进”扩大权限。演化是离线、受评测、可回滚的规则维护，不是在当前回答里递归改写自己。

## Levels

- **L0 — 运行规则**：语气、检索顺序、Capture 阈值、模式内输出结构、低风险路由启发式。只允许修改四个 mode prompt。
- **L1 — 元规则**：失败归类、候选生成、评测选择、晋升与回滚条件。只允许修改本文件。
- **L2 — I-level**：`AGENTS.md` 中的用户主权、安全、事实与 provenance、section 语义、可编辑白名单、硬评测下限、回滚能力和权限不扩张。L2 不可自动修改；只允许 Henry 明确要求后人工修改。

L0/L1 自动流程也不得修改 `scripts/`、`tests/`、`evals/`、`.codex/`、`AGENTS.md` 或 Git 配置。

## Trigger

满足任一条件时可以启动审核：

1. Henry 明确指出系统设计或行为问题。
2. 同类失败在 30 天内至少出现两次。
3. 当前 model slug 与上次完整兼容性审核不同。
4. 距上次完整兼容性审核至少 90 天。

无证据且未到兼容性审核周期时返回 `no_op`。

L1 候选必须来自一次明确的系统设计要求，或至少两个不同日期的独立证据。一次纠正可以成为 L0 候选，但仍需通过全部评测。

## Loop

`真实对话 / 用户纠正 → 问题归类 → 最小候选补丁 → 影子评测 → 自动晋升 → 7 天观察 → 保留或回滚`

1. 候选只改一个规则族，并记录模型、证据引用、目标、before hash 和预期改善。
2. 在 `evals/life-copilot-golden-cases.jsonl` 与近期真实 trace 上比较新旧规则。
3. 所有硬约束必须通过；目标案例必须改善；其他案例不得退化。
4. 每次闭合最多晋升一个候选。新规则从下一次任务开始生效。
5. 目标文件有未提交修改时暂停；不得覆盖 Henry 的修改。
6. 晋升只提交白名单目标文件，生成独立 Git commit、before snapshot 和 append-only ledger 记录。
7. 观察期为 7 天。期间出现硬约束失败、Henry 明确说“变差了”，或同类软回归两次，运行回滚。

## Candidate Contract

候选 manifest 存放在 `journal/system-evolution-candidates/`，内容文件也必须留在该目录。核心字段：

```json
{
  "id": "short-kebab-id",
  "layer": "L0",
  "target": "prompts/chat-mode.md",
  "model": "model-slug",
  "explicit_system_design_request": true,
  "evidence": [{"date": "YYYY-MM-DD", "ref": "trace-or-journal-ref"}],
  "before_sha256": "...",
  "candidate_content_file": "short-kebab-id.md",
  "evaluation": {
    "hard_constraints_passed": true,
    "target_improved": true,
    "regressions": [],
    "passed_golden_cases": ["all hard case ids"],
    "recent_trace_refs": ["at least one trace"]
  }
}
```

CLI:

```bash
python3 scripts/copilot.py audit-system-rules --date YYYY-MM-DD --model MODEL
python3 scripts/copilot.py audit-system-rules --date YYYY-MM-DD --model MODEL --complete-review --review-evidence-file REVIEW.json
python3 scripts/copilot.py audit-system-rules --date YYYY-MM-DD --model MODEL --candidate-file MANIFEST
python3 scripts/copilot.py promote-system-rule --candidate-file MANIFEST
python3 scripts/copilot.py rollback-system-rule --candidate-id ID --reason REASON
```

## Ledger

`journal/system-evolution.jsonl` 是 append-only 事实账本。记录 candidate ID、层级、model、证据、前后 hash、评测、状态、commit 和观察期。不得通过修改旧行来“修正历史”；后续事件用新行表达。

允许状态包括 `candidate_ready`、`probation`、`stable`、`dirty_target`、`tests_failed`、`rolled_back` 与 `no_op`。
