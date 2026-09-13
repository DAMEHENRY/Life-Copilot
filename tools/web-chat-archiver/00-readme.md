# 网页对话归档

把 Claude 网页版（claude.ai）和 ChatGPT 网页版（含 Health）的对话存到本地，日记流程跑 `writeback-ai-day` 时写进当天的 `claude-web` / `chatgpt-web` trace，并在 `## 💬 From Kai` 各挂一个链接。

抓取不依赖任何 AI 框架：Chrome 扩展用浏览器里现成的登录去读对话，本地小程序（native messaging host）把原始 JSON 写到磁盘，`scripts/copilot.py` 再从磁盘生成 trace。Claude Code 和 Codex 跑的都是同一条 `copilot.py` 命令。

## 怎么运转

1. `writeback-ai-day` 先检查扩展在不在线。Chrome 没开就用 `open -g -j -a "Google Chrome" --args --no-startup-window` 在后台启动（不开窗口、不抢焦点），同步完再退出；Chrome 本来开着就不动它。
2. 扩展收到同步请求后，列出 Claude 全部对话，以及 ChatGPT 普通、星标、归档、Health 和 Projects 里的对话，只下载更新过的那些。
3. 请求先直接从扩展后台发；如果被拒，就在一个后台标签页（同源的 `robots.txt`，必要时换成完整网页）里发。登录凭证和 token 始终不离开浏览器。
4. 本地小程序把每条对话写成 `~/.local/share/life-copilot/web-chats/<claude|chatgpt>/<对话 id>.json`，版本记录在同目录的 `index.json`。
5. `copilot.py` 从这些 JSON 里取当前可见分支的正文，按消息时间分到各天，过滤 thinking、工具调用和返回、隐藏上下文和引用标记。

扩展每小时也会自己同步一次，但日记流程不依赖这个定时同步。

## 安装（一次性）

```bash
python3 scripts/copilot.py install-web-chats
```

这条命令会：

- 把 `extension/` 和 `host/` 复制到 `~/.local/share/life-copilot/web-chat-archiver/`（放在 iCloud 之外，避免文件被移出本地或触发权限弹窗）。
- 在 `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/` 注册 `com.lifecopilot.web_chats`。

然后在 Chrome 里：

1. 打开 `chrome://extensions`，打开右上角「开发者模式」。
2. 点「加载已解压的扩展程序」，选 `~/.local/share/life-copilot/web-chat-archiver/extension`（文件选择框里按 Cmd+Shift+G 可以粘贴路径）。

扩展 ID 固定为 `kpdjiedddebakkcgmhldmldeboicgoja`，由 `manifest.json` 里的 `key` 决定，本地小程序只接受这个 ID 的连接。

改了这个目录下的代码后，把 `manifest.json` 的 `version` 加一，再重跑 `install-web-chats`。对未打包的扩展，Chrome 不会因为重启或版本号变化就换用新的后台脚本，所以安装命令会通知扩展自己重载（Chrome 没开时会后台启动，完事再关掉），并确认新版本号已经连上本地小程序。

## 常用命令

```bash
python3 scripts/copilot.py sync-web-chats                     # 立即同步（需要时自动启动 Chrome）
python3 scripts/copilot.py sync-web-chats --provider chatgpt  # 只同步一边
python3 scripts/copilot.py web-chats-status                   # 看上次同步结果和存档数量
python3 scripts/copilot.py preview-ai-day --date YYYY-MM-DD   # 只读本地存档，不同步
```

## 出问题时

- **`not logged in` / `auth_required`**：在 Chrome 里重新登录 claude.ai 或 chatgpt.com，再重跑。
- **`extension is not connected`**：扩展没加载或被停用了，按上面的安装步骤重新加载；`web-chats-status` 里 `native_host_registered` 应为 `true`。
- **ChatGPT 弹人机验证**：在 Chrome 里打开 chatgpt.com 手动通过，再重跑。
- **确实要跳过**：只有 Henry 明确接受不完整归档时，才给 `writeback-ai-day` 加 `--allow-missing-web-chats`，这时会改用上次的本地存档。
- 本地小程序的日志在 `~/.local/share/life-copilot/web-chats/host.log`，扩展图标上出现红色 `!` 时，把鼠标悬停在图标上可以看到错误信息。

## 文件

- `extension/manifest.json`、`extension/background.js`：Chrome 扩展（Manifest V3）。
- `host/web_chat_host.py`：本地小程序，只用 Python 标准库；同时开着和 Chrome 通信的 stdin/stdout，以及给 `copilot.py` 用的 Unix socket（`web-chats/host.sock`）。
- 两边接口都不是公开 API，网站改版可能失效。解析逻辑的测试在 `tests/test_web_chats.py`。
