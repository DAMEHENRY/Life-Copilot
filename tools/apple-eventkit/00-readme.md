# Apple EventKit CLI (`eventkit-ctl`)

原生 Swift EventKit 命令行工具，供 Codex 与 Antigravity 直接读写 macOS 日历（Calendar）与提醒事项（Reminders），统一输出 JSON。

默认 `--backend auto`：若当前宿主进程已获得 EventKit 完全访问权限，直接走原生 EventKit；否则自动回落到同目录下的 `jxa_bridge.js`（通过 `osascript -l JavaScript` 调用 `Calendar.app` / `Reminders.app`），命令参数与 JSON 输出格式保持一致。可用 `--backend eventkit` 或 `--backend jxa` 强制指定后端。

## 编译

```bash
swiftc -O tools/apple-eventkit/main.swift \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker tools/apple-eventkit/Info.plist \
  -o tools/apple-eventkit/eventkit-ctl
```

## 权限检查与授权

```bash
./tools/apple-eventkit/eventkit-ctl status
./tools/apple-eventkit/eventkit-ctl authorize
```

若系统未弹出授权框，可在「系统设置 → 隐私与安全性 → 日历 / 提醒事项」中为运行该命令的宿主应用开启权限。

## 日历（Calendar）

```bash
# 列出所有日历
./tools/apple-eventkit/eventkit-ctl cal lists

# 查询日程（默认今天 00:00 起 7 天内，默认跳过节假日订阅与冗余提醒日历以提速；加 --all-calendars 可全查）
./tools/apple-eventkit/eventkit-ctl cal events
./tools/apple-eventkit/eventkit-ctl cal events --from 2026-11-16 --days 3 --calendar "Calendar"

# 新建日程（默认时长 60 分钟；支持 --place 别名或 --location 自动匹配常用地名表）
# 默认提醒策略：非全天且无地点默认提前 30 分钟（-30）；有地点留空交由苹果计算「出发时间提醒」；全天日程默认当天 09:00（+540）；可用 --alert 覆盖（如 --alert -15,0 / --alert 9am / --alert none）
./tools/apple-eventkit/eventkit-ctl cal add --title "1:1" --start "2026-11-17T10:00:00+08:00" --duration 30
./tools/apple-eventkit/eventkit-ctl cal add --title "上课" --start "2026-11-17T15:20:00+08:00" --place "求索楼"

# 查看常用地名表（places.json）
./tools/apple-eventkit/eventkit-ctl places

# 更新 / 删除日程
./tools/apple-eventkit/eventkit-ctl cal update --id "<event-id>" --title "New Title" --alert -15
./tools/apple-eventkit/eventkit-ctl cal delete --id "<event-id>"
```

## 提醒事项（Reminders）

按 Life 约定，Henry 说「加到我的 reminder」时默认写入 `Backlog` 列表。

```bash
# 列出所有提醒列表
./tools/apple-eventkit/eventkit-ctl rem lists

# 查询未完成提醒
./tools/apple-eventkit/eventkit-ctl rem list --list Backlog

# 新建提醒（带具体时刻默认同时写 EKAlarm 到点弹窗，可用 --no-alarm 关闭；纯日期 YYYY-MM-DD 仅设日期不写闹钟，走 iPhone 全天提醒时间）
./tools/apple-eventkit/eventkit-ctl rem add --list Backlog --title "整理周报" --due "2026-11-17 18:00" --priority medium

# 更新 / 完成 / 删除提醒
./tools/apple-eventkit/eventkit-ctl rem update --id "<rem-id>" --priority high
./tools/apple-eventkit/eventkit-ctl rem complete --id "<rem-id>"
./tools/apple-eventkit/eventkit-ctl rem delete --id "<rem-id>"
```

## 日程镜像（Snapshot）

```bash
# 手动导出未来 30 天日历 + 全部未完成提醒到 tools/apple-eventkit/schedule-snapshot.json
./tools/apple-eventkit/eventkit-ctl snapshot
```

每次通过 `eventkit-ctl` 增删改日历或提醒事项后会自动刷新该快照；`scripts/copilot.py refresh-ai-day` 也会按 15 分钟节流自动刷新（内容无变化时不重写文件，文件已加入 `.gitignore`，但会随 `rsync` 推给 Kai）。
