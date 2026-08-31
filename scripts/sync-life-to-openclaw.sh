#!/bin/zsh
set -eu

readonly SOURCE_DIR="/Users/henry/Library/Mobile Documents/iCloud~md~obsidian/Documents/Life/"
readonly REMOTE_HOST="mechrevo-wsl"
readonly REMOTE_DIR="/home/henry/.life-sync-staging/"
readonly LOCK_DIR="/tmp/openclaw-life-sync.lock"
readonly STATUS_FILE="/tmp/openclaw-life-last-sync.txt"
readonly DURABLE_STATUS_FILE="/Users/henry/Library/Logs/openclaw-life-sync.status"
readonly SSH_COMMAND="/usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=3 -o ServerAliveInterval=10 -o ServerAliveCountMax=3"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  exit 0
fi
trap 'rm -f "$STATUS_FILE"; rmdir "$LOCK_DIR"' EXIT

record_failure() {
  local exit_code=$?
  /bin/date -u '+failed %Y-%m-%dT%H:%M:%SZ' > "$DURABLE_STATUS_FILE"
  exit "$exit_code"
}
trap record_failure ZERR

/usr/bin/rsync \
  -az \
  --delete-delay \
  --partial \
  --timeout=60 \
  --exclude='/.git/' \
  --exclude='/.obsidian/' \
  --exclude='/archives/' \
  --exclude='/tmp/' \
  --exclude='/.tmp/' \
  --exclude='/.claude/' \
  --exclude='/.claudian/' \
  --exclude='/.codex/' \
  --exclude='/.antigravitycli/' \
  --exclude='/.pycache/' \
  --exclude='/.pytest_cache/' \
  --exclude='/.vscode/' \
  --exclude='node_modules/' \
  --exclude='__pycache__/' \
  --include='*/' \
  --include='*.md' \
  --include='*.json' \
  --include='*.jsonl' \
  --include='*.txt' \
  --exclude='*' \
  -e "$SSH_COMMAND" \
  --rsync-path='/usr/bin/rsync' \
  "$SOURCE_DIR" \
  "$REMOTE_HOST:$REMOTE_DIR"

/bin/date -u '+%Y-%m-%dT%H:%M:%SZ' > "$STATUS_FILE"

/usr/bin/rsync \
  -az \
  --timeout=60 \
  -e "$SSH_COMMAND" \
  --rsync-path='/usr/bin/rsync' \
  "$STATUS_FILE" \
  "$REMOTE_HOST:${REMOTE_DIR}.last-sync"

/bin/date -u '+ok %Y-%m-%dT%H:%M:%SZ' > "$DURABLE_STATUS_FILE"
