"""
Wire protocol between the local client and the Colab server.

All control messages are JSON-encoded and sent as WebSocket text frames.
File data (PUT) is sent as WebSocket binary frames.

Client → Server (Text)
---------------
  { "type": "auth", "secret": "<hex>" }
  { "type": "delete", "path": "<relative>" }
  { "type": "batch", "msgs": [ { "type": "delete", ... }, { "type": "put", ... } ] }

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


def batch_msg(msgs: list[str | bytes]) -> bytes:
    """Combine multiple messages into a single binary batch message."""
    # We use a binary format for the batch to support binary PUTs inside it
    # Format: [header_json] + \0 + [len1 (4 bytes)] + [msg1] + [len2 (4 bytes)] + [msg2] ...
    header = json.dumps({"type": "batch", "count": len(msgs)}).encode()
    payload = byteorder_to_bytes(len(header)) + header
    for msg in msgs:
        if isinstance(msg, str):
            msg = msg.encode()
        payload += byteorder_to_bytes(len(msg)) + msg
    return payload


def byteorder_to_bytes(n: int) -> bytes:
    return n.to_bytes(4, byteorder="big")


def bytes_to_int(b: bytes) -> int:
    return int.from_bytes(b, byteorder="big")


def parse_batch(raw: bytes) -> list[tuple[str, any]]:
    """Parse a binary batch message and return a list of (type, payload) tuples."""
    try:
        offset = 0
        
        # Read header
        header_len = bytes_to_int(raw[offset:offset+4])
        offset += 4
        header = json.loads(raw[offset:offset+header_len].decode())
        offset += header_len
        
        if header.get("type") != "batch":
            raise ValueError("Not a batch message")
            
        results = []
        for _ in range(header.get("count", 0)):
            msg_len = bytes_to_int(raw[offset:offset+4])
            offset += 4
            msg_raw = raw[offset:offset+msg_len]
            offset += msg_len
            
            # Sub-message could be binary PUT or JSON text
            try:
                # Try JSON first (text control messages)
                msg_text = msg_raw.decode()
                results.append(("json", json.loads(msg_text)))
            except (UnicodeDecodeError, json.JSONDecodeError):
                # Must be a binary PUT
                results.append(("put", parse_binary_put(msg_raw)))
                
        return results
    except Exception as exc:
        raise ValueError(f"Malformed batch message: {exc}") from exc


def parse_binary_put(raw: bytes) -> tuple[str, bytes]:
    """Parse a single binary PUT message: Header (JSON) + \0 + Body."""
    try:
        header_end = raw.index(b"\0")
        header = json.loads(raw[:header_end].decode())
        if header.get("type") != "put":
            raise ValueError("Not a put message")
        rel_path = header.get("path")
        data = raw[header_end + 1:]
        return rel_path, data
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Malformed binary put: {exc}") from exc
