"""
Join-link encoding/decoding.

A join link encodes:
  - the Cloudflare tunnel URL (wss://…)
  - a 4-byte shared secret

The URL is simplified by stripping the protocol and replacing common 
suffixes with short markers. The resulting string is packed into a 
compact 5-bit representation (custom Base32). The secret and URL 
are then combined at the bit-level to eliminate all padding and 
overhead before being encoded in Base62.
"""

from __future__ import annotations

import os


PREFIX = "cs1_"

# Markers for common URL parts that don't appear in subdomains
# $ = .trycloudflare.com
# $a = .cfargotunnel.com
_MARKERS = {
    ".trycloudflare.com": "$",
    ".cfargotunnel.com": "$a",
}
_REV_MARKERS = {
    "$a": ".cfargotunnel.com",
    "$": ".trycloudflare.com",
}

_PROTOCOLS = ["wss://", "ws://", "https://", "http://"]

_BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# 5-bit packing alphabet (32 characters max)
# 0-25: a-z
# 26: -
# 27: .
# 28: $
# 29: _
# 30: Escape (the next 8 bits are literal ASCII)
# 31: End of String
_PACK_ALPHABET = "abcdefghijklmnopqrstuvwxyz-.$_"
_CHAR_TO_VAL = {c: i for i, c in enumerate(_PACK_ALPHABET)}


def _base62_encode(n: int) -> str:
    """Encode a large integer to an alphanumeric string using Base62."""
    if n == 0:
        return "0"
    res = []
    while n:
        res.append(_BASE62_ALPHABET[n % 62])
        n //= 62
    return "".join(reversed(res))


def _base62_decode(s: str) -> int:
    """Decode a Base62 string back to an integer."""
    n = 0
    for char in s:
        n = n * 62 + _BASE62_ALPHABET.index(char)
    return n


def _simplify_url(url: str) -> str:
    """Strip protocol and replace common constant URL parts with short markers."""
    for proto in _PROTOCOLS:
        if url.startswith(proto):
            url = url[len(proto) :]
            break
    for full, marker in _MARKERS.items():
        url = url.replace(full, marker)
    return url


def _expand_url(simplified: str) -> str:
    """Restore markers back to their full URL parts."""
    for marker, full in _REV_MARKERS.items():
        simplified = simplified.replace(marker, full)
    return simplified


def encode(tunnel_url: str, secret: bytes) -> str:
    """Return a short join link from a tunnel URL and a secret."""
    if len(secret) != 4:
        raise ValueError("Secret must be exactly 4 bytes")

    simplified = _simplify_url(tunnel_url)
    
    # 1. Build a single bitstream: [1] + [secret_32bits] + [packed_url_bits]
    # The leading '1' bit ensures that the integer representation preserves all bits.
    n = 1
    
    # Add secret
    for b in secret:
        n = (n << 8) | b
        
    # Add packed URL
    for char in simplified:
        if char in _CHAR_TO_VAL:
            n = (n << 5) | _CHAR_TO_VAL[char]
        else:
            n = (n << 5) | 30 # Escape
            n = (n << 8) | ord(char)
            
    # Add End of String (31)
    n = (n << 5) | 31
    
    return PREFIX + _base62_encode(n)


def decode(link: str) -> tuple[str, bytes]:
    """Parse a join link and return (tunnel_url, secret)."""
    if not link.startswith(PREFIX):
        raise ValueError(f"Not a valid colabsync join link (expected prefix '{PREFIX}')")
    
    payload_str = link[len(PREFIX) :]
    try:
        n = _base62_decode(payload_str)
        
        # 1. Deconstruct from right to left (stack-like)
        # But bit-level deconstruction from right is hard for variable-length 5/8 bits.
        # It's better to convert n to a bitstream and read from left.
        
        # Convert n to bits, ignoring the leading '1' bit
        bit_str = bin(n)[3:] # strip '0b1'
        pos = 0
        
        def read_bits(count):
            nonlocal pos
            if pos + count > len(bit_str):
                return None
            res = int(bit_str[pos : pos + count], 2)
            pos += count
            return res
            
        # Read secret (first 32 bits)
        secret_bytes = bytearray()
        for _ in range(4):
            b = read_bits(8)
            if b is None: raise ValueError("Truncated secret")
            secret_bytes.append(b)
        secret = bytes(secret_bytes)
        
        # Read URL parts
        res = []
        while True:
            val = read_bits(5)
            if val is None or val == 31: # End
                break
            if val == 30: # Escape
                char_val = read_bits(8)
                if char_val is None: break
                res.append(chr(char_val))
            elif val < len(_PACK_ALPHABET):
                res.append(_PACK_ALPHABET[val])
            else:
                break
                
        tunnel_url = _expand_url("".join(res))
        
        # Ensure protocol
        if "://" not in tunnel_url:
            tunnel_url = "wss://" + tunnel_url
            
        return tunnel_url, secret
    except Exception as exc:
        raise ValueError(f"Invalid join link: {exc}") from exc


def generate_secret(nbytes: int = 4) -> bytes:
    return os.urandom(nbytes)
