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
import zlib
from mnemonic import Mnemonic


PREFIX = "colabsync1_"

# Common suffixes to shorten before compression
SUFFIX_MAP = {
    ".trycloudflare.com": ".tc",
}
REV_SUFFIX_MAP = {v: k for k, v in SUFFIX_MAP.items()}

_MNEMONIC = Mnemonic("english")
_WORD_TO_IDX = {word: i for i, word in enumerate(_MNEMONIC.wordlist)}


def _to_base36(n: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    res = []
    while n:
        res.append(chars[n % 36])
        n //= 36
    return "".join(reversed(res))


def _from_base36(s: str) -> int:
    return int(s, 36)


def _shorten_url(url: str) -> str:
    """Apply dictionary-based shortening to the URL string."""
    # 1. Handle protocol (already stripped in encode, but let's be safe)
    for p in ["https://", "wss://", "http://", "ws://"]:
        if url.startswith(p):
            url = url[len(p) :]
            break

    # 2. Shorten common suffixes
    for full, short in SUFFIX_MAP.items():
        if url.endswith(full):
            url = url[: -len(full)] + short
            break

    # 3. Shorten mnemonic subdomain words
    if "." in url:
        subdomain, rest = url.split(".", 1)
        tokens = subdomain.split("-")
        encoded_tokens = []
        for t in tokens:
            if t in _WORD_TO_IDX:
                # Use base36 to represent the word index
                encoded_tokens.append(_to_base36(_WORD_TO_IDX[t]))
            else:
                # Escape non-dictionary words with a prefix that won't occur in base36
                # (actually base36 uses all valid chars, so let's use an underscore)
                encoded_tokens.append(f"_{t}")
        url = "-".join(encoded_tokens) + "." + rest

    return url


def _expand_url(shortened: str) -> str:
    """Reverse the shortening process."""
    if "." in shortened:
        subdomain, rest = shortened.split(".", 1)
        decoded_tokens = []
        for t in subdomain.split("-"):
            if t.startswith("_"):
                decoded_tokens.append(t[1:])
            else:
                try:
                    idx = _from_base36(t)
                    decoded_tokens.append(_MNEMONIC.wordlist[idx])
                except (ValueError, IndexError):
                    # Fallback for unexpected tokens
                    decoded_tokens.append(t)
        shortened = "-".join(decoded_tokens) + "." + rest

    # Expand suffixes
    for short, full in REV_SUFFIX_MAP.items():
        if shortened.endswith(short):
            shortened = shortened[: -len(short)] + full
            break

    return shortened


def encode(tunnel_url: str, secret: bytes) -> str:
    """Return a short join link from a tunnel URL and a secret."""
    # 1. Shorten the URL string
    short_url = _shorten_url(tunnel_url)

    # 2. Pack as: [4_bytes_secret] + [short_url_bytes]
    # Then compress the whole thing.
    if len(secret) != 4:
        raise ValueError("Secret must be exactly 4 bytes")
    data = secret + short_url.encode()
    compressed = zlib.compress(data)
    
    b64 = base64.urlsafe_b64encode(compressed).rstrip(b"=").decode()
    return PREFIX + b64


def decode(link: str) -> tuple[str, bytes]:
    """
    Parse a join link and return ``(tunnel_url, secret)``.

    Raises ``ValueError`` on malformed input.
    """
    if not link.startswith(PREFIX):
        raise ValueError(f"Not a valid colabsync join link (expected prefix '{PREFIX}')")
    b64 = link[len(PREFIX) :]
    # Re-add padding
    padding = 4 - len(b64) % 4
    if padding != 4:
        b64 += "=" * padding
    try:
        b64_decoded = base64.urlsafe_b64decode(b64)
    except Exception as exc:
        raise ValueError(f"Could not decode join link: {exc}") from exc

    try:
        decompressed = zlib.decompress(b64_decoded)
        if len(decompressed) < 4:
            raise ValueError("Decompressed payload too short")
            
        secret = decompressed[:4]
        url_part = decompressed[4:].decode()
        
        # Expand back to original URL
        tunnel_url = _expand_url(url_part)
        
        # Add protocol if missing
        if "://" not in tunnel_url:
            tunnel_url = "wss://" + tunnel_url
    except Exception as exc:
        raise ValueError(f"Invalid join link data: {exc}") from exc

    return tunnel_url, secret


def generate_secret(nbytes: int = 4) -> bytes:
    return os.urandom(nbytes)
