"""
Join-link encoding/decoding.

A join link encodes two things that the local client needs:
  - the Cloudflare tunnel URL  (wss://…)
  - a shared HMAC secret       (for request authentication)

Format (before base64url):
    <url>\n<hex-secret>

The final link is prefixed with "cs1_" so the version can be bumped later.
"""

from __future__ import annotations

import base64
import os


PREFIX = "cs1_"


def encode(tunnel_url: str, secret: bytes) -> str:
    """Return a short join link from a tunnel URL and a secret."""
    payload = f"{tunnel_url}\n{secret.hex()}".encode()
    b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    return PREFIX + b64


def decode(link: str) -> tuple[str, bytes]:
    """
    Parse a join link and return ``(tunnel_url, secret)``.

    Raises ``ValueError`` on malformed input.
    """
    if not link.startswith(PREFIX):
        raise ValueError(f"Not a valid colabsync join link (expected prefix '{PREFIX}')")
    b64 = link[len(PREFIX):]
    # Re-add padding
    padding = 4 - len(b64) % 4
    if padding != 4:
        b64 += "=" * padding
    try:
        payload = base64.urlsafe_b64decode(b64).decode()
    except Exception as exc:
        raise ValueError(f"Could not decode join link: {exc}") from exc

    parts = payload.split("\n", 1)
    if len(parts) != 2:
        raise ValueError("Malformed join link payload")

    tunnel_url, secret_hex = parts
    try:
        secret = bytes.fromhex(secret_hex)
    except ValueError as exc:
        raise ValueError(f"Invalid secret in join link: {exc}") from exc

    return tunnel_url, secret


def generate_secret(nbytes: int = 32) -> bytes:
    return os.urandom(nbytes)
