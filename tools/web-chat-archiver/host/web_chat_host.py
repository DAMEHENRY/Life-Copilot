#!/usr/bin/env python3
"""Native messaging host for the Life Copilot web chat archiver.

Chrome starts this process when the extension connects. It keeps two
channels open for as long as Chrome runs:

- stdin/stdout: Chrome native messaging (4-byte little-endian length + JSON)
  to the extension, which fetches conversations with the browser login.
- a Unix socket next to the archive: newline-delimited JSON commands from
  `scripts/copilot.py` (`ping`, `sync`, `status`).

The archive layout is the contract with copilot.py:
  <data dir>/<provider>/<conversation id>.json   raw conversation + list metadata
  <data dir>/index.json                          stored/listed versions, last sync
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

PROVIDERS = ("claude", "chatgpt")
DATA_DIR = Path(
    os.environ.get(
        "LIFE_WEB_CHATS_DIR",
        str(Path.home() / ".local" / "share" / "life-copilot" / "web-chats"),
    )
)
SOCKET_NAME = "host.sock"
INDEX_NAME = "index.json"
LOG_NAME = "host.log"
LOG_MAX_BYTES = 1024 * 1024
STALE_SYNC_SECONDS = 15 * 60
SAFE_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_conversation_id(value: object) -> Optional[str]:
    text = str(value or "")
    if not text or len(text) > 128 or any(ch not in SAFE_ID_CHARS for ch in text):
        return None
    return text


def atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Native messaging framing
# ---------------------------------------------------------------------------
def read_native_message(stream) -> Optional[dict]:
    header = stream.read(4)
    if len(header) < 4:
        return None
    (length,) = struct.unpack("<I", header)
    body = stream.read(length)
    if len(body) < length:
        return None
    message = json.loads(body.decode("utf-8"))
    return message if isinstance(message, dict) else {}


def encode_native_message(message: dict) -> bytes:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    return struct.pack("<I", len(body)) + body


# ---------------------------------------------------------------------------
# Archive store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.index_path = data_dir / INDEX_NAME
        self.lock = threading.Lock()
        self.index = self._load_index()

    def _load_index(self) -> dict:
        try:
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            index = {}
        if not isinstance(index, dict):
            index = {}
        index.setdefault("version", 1)
        providers = index.setdefault("providers", {})
        for provider in PROVIDERS:
            entry = providers.setdefault(provider, {})
            entry.setdefault("stored", {})
            entry.setdefault("listed", {})
        return index

    def _save(self) -> None:
        atomic_write_json(self.index_path, self.index)

    def known(self) -> Dict[str, Dict[str, str]]:
        """Stored versions, limited to files still on disk so a deleted file
        is fetched again on the next sync."""
        with self.lock:
            return {
                provider: {
                    conv_id: version
                    for conv_id, version in self.index["providers"][provider]["stored"].items()
                    if (self.data_dir / provider / f"{conv_id}.json").exists()
                }
                for provider in PROVIDERS
            }

    def record_index(self, provider: str, items: list) -> None:
        if provider not in PROVIDERS:
            return
        listed = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            conv_id = safe_conversation_id(item.get("id"))
            if not conv_id:
                continue
            listed[conv_id] = {
                "title": str(item.get("title") or ""),
                "created_at": item.get("created_at") or "",
                "update_time": item.get("update_time") or "",
                "tags": [tag for tag in item.get("tags") or [] if isinstance(tag, str)],
            }
        with self.lock:
            entry = self.index["providers"][provider]
            entry["listed"] = listed
            entry["listed_at"] = utc_now()
            self._save()

    def write_conversation(self, message: dict) -> bool:
        provider = message.get("provider")
        conv_id = safe_conversation_id(message.get("id"))
        conversation = message.get("conversation")
        if provider not in PROVIDERS or not conv_id or not isinstance(conversation, dict):
            return False
        record = {
            "provider": provider,
            "id": conv_id,
            "title": str(message.get("title") or ""),
            "created_at": message.get("created_at") or "",
            "update_time": message.get("update_time") or "",
            "tags": [tag for tag in message.get("tags") or [] if isinstance(tag, str)],
            "fetched_at": utc_now(),
            "conversation": conversation,
        }
        atomic_write_json(self.data_dir / provider / f"{conv_id}.json", record)
        with self.lock:
            self.index["providers"][provider]["stored"][conv_id] = record["update_time"]
            self._save()
        return True

    def record_sync(self, request_id: str, reason: str, result: dict) -> None:
        finished = utc_now()
        with self.lock:
            for provider, outcome in (result.get("providers") or {}).items():
                if provider not in PROVIDERS or not isinstance(outcome, dict):
                    continue
                entry = self.index["providers"][provider]
                entry["last_attempt_at"] = finished
                entry["last_result"] = outcome
                if outcome.get("ok"):
                    entry["last_success_at"] = finished
            self.index["last_sync"] = {
                "request_id": request_id,
                "reason": reason,
                "finished_at": finished,
                "ok": bool(result.get("ok")),
            }
            self._save()

    def status(self) -> dict:
        with self.lock:
            summary = {}
            for provider in PROVIDERS:
                entry = self.index["providers"][provider]
                summary[provider] = {
                    "stored": len(entry["stored"]),
                    "listed": len(entry["listed"]),
                    "last_success_at": entry.get("last_success_at", ""),
                    "last_result": entry.get("last_result", {}),
                }
            return {"providers": summary, "last_sync": self.index.get("last_sync", {})}


# ---------------------------------------------------------------------------
# Host
# ---------------------------------------------------------------------------
class Host:
    def __init__(self, data_dir: Path, stdin, stdout) -> None:
        self.data_dir = data_dir
        self.stdin = stdin
        self.stdout = stdout
        self.store = Store(data_dir)
        self.write_lock = threading.Lock()
        self.state = threading.Condition()
        self.current: Optional[dict] = None
        self.results: Dict[str, dict] = {}
        self.extension_version = ""
        self.connected_at = utc_now()
        self.socket_path = data_dir / SOCKET_NAME
        self.socket_inode: Optional[int] = None
        self.server: Optional[socket.socket] = None

    # -- logging -----------------------------------------------------------
    def log(self, message: str) -> None:
        path = self.data_dir / LOG_NAME
        try:
            if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
                path.write_text("", encoding="utf-8")
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(f"{utc_now()} {message}\n")
        except OSError:
            pass

    # -- extension channel -------------------------------------------------
    def send(self, message: dict) -> None:
        data = encode_native_message(message)
        with self.write_lock:
            self.stdout.write(data)
            self.stdout.flush()

    def start_sync(self, providers, reason: str, wait: bool) -> Optional[str]:
        """Start a sync. Waits for a running sync to finish when `wait` is set;
        otherwise returns None if one is already running."""
        with self.state:
            while self.current is not None:
                stale = time.time() - self.current["started"] > STALE_SYNC_SECONDS
                if stale:
                    self.log(f"dropping stale sync {self.current['request_id']}")
                    self.current = None
                    break
                if not wait:
                    return None
                self.state.wait(timeout=5)
            request_id = uuid.uuid4().hex
            self.current = {"request_id": request_id, "reason": reason, "started": time.time()}
        wanted = [p for p in (providers or PROVIDERS) if p in PROVIDERS]
        self.log(f"sync {request_id} started ({reason}): {','.join(wanted)}")
        self.send({
            "type": "sync",
            "request_id": request_id,
            "providers": wanted,
            "known": self.store.known(),
        })
        return request_id

    def wait_result(self, request_id: str, timeout: float) -> Optional[dict]:
        deadline = time.time() + timeout
        with self.state:
            while request_id not in self.results:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self.state.wait(timeout=min(remaining, 5))
            return self.results.pop(request_id)

    def handle_extension_message(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "hello":
            self.extension_version = str(message.get("extension_version") or "")
            self.log(f"extension connected v{self.extension_version}")
        elif kind == "want_sync":
            reason = str(message.get("reason") or "extension")
            threading.Thread(
                target=self._background_sync, args=(reason,), daemon=True
            ).start()
        elif kind == "index":
            self.store.record_index(str(message.get("provider")), message.get("items") or [])
        elif kind == "conversation":
            if not self.store.write_conversation(message):
                self.log(f"rejected conversation message for {message.get('provider')}/{message.get('id')}")
        elif kind == "log":
            self.log(f"extension {message.get('level', 'info')}: {message.get('message', '')}")
        elif kind == "done":
            self._finish(message)

    def _background_sync(self, reason: str) -> None:
        request_id = self.start_sync(None, reason, wait=False)
        if request_id:
            self.wait_result(request_id, STALE_SYNC_SECONDS)

    def _finish(self, message: dict) -> None:
        request_id = str(message.get("request_id") or "")
        result = {
            "ok": bool(message.get("ok")),
            "providers": message.get("providers") or {},
            "error": message.get("error") or "",
        }
        with self.state:
            reason = self.current["reason"] if self.current and self.current["request_id"] == request_id else "unknown"
            if self.current and self.current["request_id"] == request_id:
                self.current = None
            self.results[request_id] = result
            self.state.notify_all()
        self.store.record_sync(request_id, reason, result)
        self.log(f"sync {request_id} finished ok={result['ok']}: {json.dumps(result['providers'], ensure_ascii=False)[:2000]}")

    # -- CLI channel -------------------------------------------------------
    def serve_socket(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        server.listen(4)
        self.socket_inode = self.socket_path.stat().st_ino
        self.server = server
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=self.handle_client, args=(conn,), daemon=True).start()

    def handle_client(self, conn: socket.socket) -> None:
        with conn:
            try:
                raw = b""
                while not raw.endswith(b"\n") and len(raw) < 65536:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    raw += chunk
                request = json.loads(raw.decode("utf-8") or "{}")
                response = self.handle_command(request if isinstance(request, dict) else {})
            except Exception as exc:  # noqa: BLE001 - report every failure to the CLI
                response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            try:
                conn.sendall(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
            except OSError:
                pass

    def handle_command(self, request: dict) -> dict:
        cmd = request.get("cmd")
        if cmd == "ping":
            return {
                "ok": True,
                "extension_version": self.extension_version,
                "connected_at": self.connected_at,
                "syncing": self.current is not None,
            }
        if cmd == "status":
            return {"ok": True, **self.store.status()}
        if cmd == "reload_extension":
            # The extension reloads, drops this port, and starts a fresh host.
            self.send({"type": "reload"})
            return {"ok": True, "previous_extension_version": self.extension_version}
        if cmd == "sync":
            timeout = float(request.get("timeout") or 600)
            request_id = self.start_sync(request.get("providers"), "copilot", wait=True)
            result = self.wait_result(request_id, timeout) if request_id else None
            if result is None:
                return {"ok": False, "error": f"sync did not finish within {int(timeout)}s", "providers": {}}
            return {"request_id": request_id, **result}
        return {"ok": False, "error": f"unknown command: {cmd}"}

    # -- main loop ---------------------------------------------------------
    def run(self) -> int:
        threading.Thread(target=self.serve_socket, daemon=True).start()
        try:
            while True:
                message = read_native_message(self.stdin)
                if message is None:
                    break
                try:
                    self.handle_extension_message(message)
                except Exception as exc:  # noqa: BLE001 - keep the host alive
                    self.log(f"error handling {message.get('type')}: {type(exc).__name__}: {exc}")
        finally:
            self.log("extension disconnected; host exiting")
            if self.server is not None:
                self.server.close()
            # A newer host may already own the socket path after a reconnect.
            try:
                if self.socket_path.stat().st_ino == self.socket_inode:
                    self.socket_path.unlink()
            except OSError:
                pass
        return 0


def main() -> int:
    return Host(DATA_DIR, sys.stdin.buffer, sys.stdout.buffer).run()


if __name__ == "__main__":
    raise SystemExit(main())
