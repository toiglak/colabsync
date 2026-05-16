"""
Wire protocol between the local client and the Colab server.

All control messages are JSON-encoded and sent as WebSocket text frames.
File data (PUT) is sent as WebSocket binary frames.

Client → Server (Text)
---------------
  { "type": "auth", "secret": "<hex>" }
  { "type": "delete", "path": "<relative>" }

Client → Server (Binary)
-----------------
  Header (JSON) + \0 + File Body
  Header: { "type": "put", "path": "<relative>" }

Server → Client (Text)
---------------
  { "type": "ok" }
  { "type": "error", "message": "..." }
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


def put_msg(root: Path, path: Path) -> bytes:
    rel = path.relative_to(root).as_posix()
    header = json.dumps({"type": "put", "path": rel}).encode()
    body = path.read_bytes()
    return header + b"\0" + body


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


def parse_binary_put(raw: bytes) -> tuple[str, bytes]:
    """Parse a binary put message: header_json + \0 + body."""
    try:
        header_part, body = raw.split(b"\0", 1)
        header = json.loads(header_part.decode())
        if header.get("type") != "put":
            raise ValueError(f"Expected type 'put', got {header.get('type')}")
        return header["path"], body
    except Exception as exc:
        raise ValueError(f"Malformed binary put message: {exc}") from exc
