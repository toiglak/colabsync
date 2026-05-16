"""
Join-link encoding/decoding.

A join link encodes:
  - the Cloudflare tunnel URL (wss://…)
  - a 4-byte shared secret

The URL is simplified by stripping the protocol and replacing common 
suffixes with short markers. The resulting string is packed into a 
compact 5-bit representation (custom Base32) to significantly reduce 
the length, then combined with the secret and encoded in Base62.
"""

from __future__ import annotations

import os


PREFIX = "cs1_"

# Markers for common URL parts that don't appear in subdomains
# $ = .trycloudflare.com
_MARKERS = {
    ".trycloudflare.com": "$",
}
_REV_MARKERS = {
    "$": ".trycloudflare.com",
}

_PROTOCOLS = ["wss://", "ws://", "https://", "http://"]

_BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# 5-bit packing alphabet (32 characters max)
# 0-25: a-z
# 26: -
# 27: .
# 28: $
# 29: _ (used as a generic delimiter if needed)
# 30: Escape (the next 8 bits are literal ASCII)
# 31: Padding/End
_PACK_ALPHABET = "abcdefghijklmnopqrstuvwxyz-.$_"
_CHAR_TO_VAL = {c: i for i, c in enumerate(_PACK_ALPHABET)}


def _base62_encode(data: bytes) -> str:
    """Encode bytes to an alphanumeric string using Base62."""
    n = int.from_bytes(b"\x01" + data, byteorder="big")
    res = []
    while n:
        res.append(_BASE62_ALPHABET[n % 62])
        n //= 62
    return "".join(reversed(res))


def _base62_decode(s: str) -> bytes:
    """Decode a Base62 string back to bytes."""
    n = 0
    for char in s:
        n = n * 62 + _BASE62_ALPHABET.index(char)
    data = n.to_bytes((n.bit_length() + 7) // 8, byteorder="big")
    return data[1:]


def _pack_url(s: str) -> bytes:
    """Pack a URL string into a compact bitstream (5 bits per common char)."""
    bits = []
    for char in s:
        if char in _CHAR_TO_VAL:
            val = _CHAR_TO_VAL[char]
            for i in range(4, -1, -1):
                bits.append((val >> i) & 1)
        else:
            # Escape character (30) followed by 8-bit ASCII
            for i in range(4, -1, -1):
                bits.append((30 >> i) & 1)
            val = ord(char)
            for i in range(7, -1, -1):
                bits.append((val >> i) & 1)
    
    # End of string marker (31)
    for i in range(4, -1, -1):
        bits.append((31 >> i) & 1)

    # Pad to byte boundary
    while len(bits) % 8 != 0:
        bits.append(0)
        
    res = bytearray()
    for i in range(0, len(bits), 8):
        byte_bits = bits[i:i+8]
        byte_val = 0
        for b in byte_bits:
            byte_val = (byte_val << 1) | b
        res.append(byte_val)
    return bytes(res)


def _unpack_url(data: bytes) -> str:
    """Unpack the 5-bit bitstream back to a URL string."""
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    
    res = []
    pos = 0
    while pos + 5 <= len(bits):
        val = 0
        for _ in range(5):
            val = (val << 1) | bits[pos]
            pos += 1
            
        if val == 30: # Escape
            if pos + 8 > len(bits):
                break
            char_val = 0
            for _ in range(8):
                char_val = (char_val << 1) | bits[pos]
                pos += 1
            res.append(chr(char_val))
        elif val == 31: # Padding
            break
        elif val < len(_PACK_ALPHABET):
            res.append(_PACK_ALPHABET[val])
        else:
            break
            
    return "".join(res)


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
    packed_url = _pack_url(simplified)
    data = secret + packed_url
    
    return PREFIX + _base62_encode(data)


def decode(link: str) -> tuple[str, bytes]:
    """Parse a join link and return (tunnel_url, secret)."""
    if not link.startswith(PREFIX):
        raise ValueError(f"Not a valid colabsync join link (expected prefix '{PREFIX}')")
    
    payload_str = link[len(PREFIX) :]
    try:
        payload_bytes = _base62_decode(payload_str)
        
        if len(payload_bytes) < 4:
            raise ValueError("Payload too short")
            
        secret = payload_bytes[:4]
        packed_url = payload_bytes[4:]
        
        simplified = _unpack_url(packed_url)
        tunnel_url = _expand_url(simplified)
        
        # Ensure protocol
        if "://" not in tunnel_url:
            tunnel_url = "wss://" + tunnel_url
            
        return tunnel_url, secret
    except Exception as exc:
        raise ValueError(f"Invalid join link: {exc}") from exc


def generate_secret(nbytes: int = 4) -> bytes:
    return os.urandom(nbytes)
