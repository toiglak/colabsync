"""
Wire protocol between the local client and the Colab server.

All messages are JSON-encoded and sent as WebSocket text frames.

Client → Server
---------------
  { "type": "auth", "secret": "<hex>" }
      Must be the first message. Server closes the connection if auth fails.

  { "type": "put", "path": "<relative>", "data": "<base64>" }
      Create or overwrite a file.

  { "type": "delete", "path": "<relative>" }
      Delete a file.

  { "type": "ping" }
      Keepalive.

Server → Client
---------------
  { "type": "ok" }
      Auth accepted.

  { "type": "error", "message": "..." }
      Auth rejected or other error.

  { "type": "pong" }
      Reply to ping.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def auth_msg(secret: bytes) -> str:
    return json.dumps({"type": "auth", "secret": secret.hex()})


def put_msg(root: Path, path: Path) -> str:
    rel = path.relative_to(root).as_posix()
    data = base64.b64encode(path.read_bytes()).decode()
    return json.dumps({"type": "put", "path": rel, "data": data})


def delete_msg(root: Path, path: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return json.dumps({"type": "delete", "path": rel})


def ping_msg() -> str:
    return json.dumps({"type": "ping"})


def ok_msg() -> str:
    return json.dumps({"type": "ok"})


def error_msg(message: str) -> str:
    return json.dumps({"type": "error", "message": message})


def pong_msg() -> str:
    return json.dumps({"type": "pong"})


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse(raw: str) -> dict:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    if "type" not in msg:
        raise ValueError("Message missing 'type' field")
    return msg


def decode_put(msg: dict) -> tuple[str, bytes]:
    """Return (relative_path_str, file_bytes)."""
    try:
        return msg["path"], base64.b64decode(msg["data"])
    except (KeyError, Exception) as exc:
        raise ValueError(f"Malformed put message: {exc}") from exc
