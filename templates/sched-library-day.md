## ⚡️ Legacy Quant Schedule: {{weekday}}, {{date}}
> [!note] Legacy Template
> Used only by `scripts/copilot.py update-schedule`. v4.3 default schedule is a conversational projection (read `life-board.md` → pick next artifact). This template is for legacy Quant training or explicit `--target-date` manual override. Placeholders `{{xp-targets}}`, `{{xp-morning}}`, `{{xp-afternoon}}` are legacy Quant XP placeholders.
*Focus: {{xp-targets}}*

> **Current Phase**: {{phase-protocol}}
> **Target**: {{xp-targets}}
> **Context Hint**: {{yesterday-request}}; Roadblocks: {{yesterday-roadblocks}}

_Legacy Quant schedule — not the v4.3 default projection. Adjust based on actual energy and events._

| Time | Block Name | Target Task |
| :--- | :--------- | :---------- |
| **07:30 - 08:30** | **🌅 Morning Routine** | Wake, hygiene, ride to library. |
| **08:30 - 12:00** | **⚔️ Deep Work A** | {{xp-morning}} |
| **12:00 - 13:00** | **🍲 Lunch** | Fixed Time Anchor. |
| **13:00 - 14:00** | **💤 Power Nap** | Non-negotiable Recovery. |
| **14:00 - 17:00** | **⚔️ Deep Work B** | {{xp-afternoon}} |
| **17:00 - 18:00** | **🍲 Dinner** | Fixed Time Anchor. |
| **18:00 - 22:00** | **🕹️ Agency Time** | Free-choice block: sports / reading / social / podcast / casual exploration. No execution score applied. |
| **22:00 - 22:30** | **📔 Reflection** | Daily log + tomorrow projection input. |
| **22:30 - 23:00** | **🛌 Wind Down** | No screens. |
| **23:00** | **💤 Sleep** | System Shutdown. |

---

## 🏃 Sports Window Note

> 运动放在 **Agency Time（19:00-22:00）** 内灵活安排——规避正午高温，不侵占下午整段学习时间。  
> 若当天不想动，agency 时间也可以纯粹休息或阅读，不产生执行分。

---

## 🎯 Personal Actions (Non-Quant)

1. {{personal-action-1}}
2. {{personal-action-2}}

> **执行意图：** {{execution-intent}}

---

## 📐 Block Structure Rationale (Legacy Quant)

> This structure was designed for Quant training days. v4.3 default projection uses conversational planning from `life-board.md` instead of fixed time blocks.

| Old Structure | New Structure | Change Reason |
| :--- | :--- | :--- |
| Deep Work A (morning) | Unchanged | Morning is always the most productive window |
| Movement (15:30-17:00) | Moved to Agency Time (evening) | Heat avoidance; don't force midday interruption |
| Deep Work C (18:00-20:00) | Removed | Evening bleed-out on consecutive days; no forced output |
| Evening Build (20:00-22:00) | Merged into Agency Time | Lower execution pressure; allow flexible choice |
