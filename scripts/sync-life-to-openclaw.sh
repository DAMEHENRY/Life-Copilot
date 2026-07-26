#!/bin/zsh
set -eu

readonly SOURCE_DIR="/Users/henry/Library/Mobile Documents/iCloud~md~obsidian/Documents/Life/"
readonly REMOTE_HOST="mechrevo"
readonly REMOTE_DIR="/home/henry/.life-sync-staging/"
readonly LOCK_DIR="/tmp/openclaw-life-sync.lock"
readonly STATUS_FILE="/tmp/openclaw-life-last-sync.txt"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  exit 0
fi
trap 'rm -f "$STATUS_FILE"; rmdir "$LOCK_DIR"' EXIT

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
  --rsync-path='wsl -d Ubuntu -u henry -- rsync' \
  "$SOURCE_DIR" \
  "$REMOTE_HOST:$REMOTE_DIR"

/bin/date -u '+%Y-%m-%dT%H:%M:%SZ' > "$STATUS_FILE"

/usr/bin/rsync \
  -az \
  --timeout=60 \
  --rsync-path='wsl -d Ubuntu -u henry -- rsync' \
  "$STATUS_FILE" \
  "$REMOTE_HOST:${REMOTE_DIR}.last-sync"
