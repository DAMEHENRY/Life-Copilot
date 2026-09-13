#!/bin/zsh
set -eu

readonly SOURCE_DIR="/Users/henry/Library/Mobile Documents/iCloud~md~obsidian/Documents/Life/"
readonly REMOTE_HOST="mechrevo-wsl"
readonly REMOTE_DIR="/home/henry/.life-sync-staging/"
readonly LOCK_DIR="/tmp/openclaw-life-sync.lock"
readonly STATUS_FILE="/tmp/openclaw-life-last-sync.txt"
readonly DURABLE_STATUS_FILE="/Users/henry/Library/Logs/openclaw-life-sync.status"
readonly SSH_COMMAND="/usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=3 -o ServerAliveInterval=10 -o ServerAliveCountMax=3"

readonly STALE_LOCK_SECONDS=1800

utc_now() {
  /bin/date -u '+%Y-%m-%dT%H:%M:%SZ'
}

# A run killed without its EXIT trap (sleep, logout, SIGKILL) used to leave the lock behind,
# and every later run then exited 0 without syncing. Record the holder's pid, keep the lock
# only while that process is alive and recent, and log every skip or recovery.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  holder=""
  if [[ -r "$LOCK_DIR/pid" ]]; then
    holder="$(<"$LOCK_DIR/pid")"
  fi
  lock_age=$(( $(/bin/date +%s) - $(/usr/bin/stat -f %m "$LOCK_DIR") ))
  if [[ -n "$holder" ]] && /bin/kill -0 "$holder" 2>/dev/null && (( lock_age < STALE_LOCK_SECONDS )); then
    echo "$(utc_now) skipped: sync already running (pid $holder, lock ${lock_age}s old)"
    exit 0
  fi
  echo "$(utc_now) removing stale lock (pid ${holder:-unknown}, ${lock_age}s old)"
  /bin/rm -rf "$LOCK_DIR"
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$(utc_now) failed: could not acquire $LOCK_DIR" >&2
    /bin/date -u '+failed %Y-%m-%dT%H:%M:%SZ' > "$DURABLE_STATUS_FILE"
    exit 1
  fi
fi
echo $$ > "$LOCK_DIR/pid"
trap 'rm -f "$STATUS_FILE"; rm -rf "$LOCK_DIR"' EXIT

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
