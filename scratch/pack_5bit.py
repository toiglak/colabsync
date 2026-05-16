def pack_5bit(s: str) -> bytes:
    alphabet = "abcdefghijklmnopqrstuvwxyz-.$" # Added $ for trycloudflare marker
    char_to_val = {char: i for i, char in enumerate(alphabet)}
    
    # We will build a large integer and then convert to bytes
    n = 1 # Start with 1 to preserve leading zeros in bit representation
    for char in s:
        if char in char_to_val:
            n = (n << 5) | char_to_val[char]
        else:
            # Escape character (value 30) followed by 8-bit ASCII
            n = (n << 5) | 30
            n = (n << 8) | ord(char)
            
    # Convert to bytes
    return n.to_bytes((n.bit_length() + 7) // 8, byteorder="big")

def unpack_5bit(data: bytes) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz-.$"
    val_to_char = {i: char for i, char in enumerate(alphabet)}
    
    n = int.from_bytes(data, byteorder="big")
    res = []
    
    # We decode from right to left
    while n > 1:
        # Check if the next 5 bits represent an escape or a character
        # Actually, if we decode right-to-left, the last operation was either:
        # - append 5-bit val
        # - append 8-bit ascii then 5-bit escape (value 30)
        # So we can look at the lowest bits. But wait, if we go right-to-left:
        # If it was escaped, the lowest 8 bits are ASCII, and the next 5 bits are 30.
        # This is tricky because we don't know if the lowest 8 bits are ASCII unless we look ahead.
        # It's much easier to decode left-to-right.
        pass

# Left-to-right bit streaming is easier with a BitWriter/BitReader.
class BitWriter:
    def __init__(self):
        self.bits = []
    def write(self, val, num_bits):
        for i in range(num_bits - 1, -1, -1):
            self.bits.append((val >> i) & 1)
    def to_bytes(self):
        res = bytearray()
        for i in range(0, len(self.bits), 8):
            chunk = self.bits[i:i+8]
            val = 0
            for bit in chunk:
                val = (val << 1) | bit
            # If the last chunk is partial, pad with zeros
            if len(chunk) < 8:
                val <<= (8 - len(chunk))
            res.append(val)
        return bytes(res)

class BitReader:
    def __init__(self, data):
        self.bits = []
        for byte in data:
            for i in range(7, -1, -1):
                self.bits.append((byte >> i) & 1)
        self.pos = 0
    def read(self, num_bits):
        if self.pos + num_bits > len(self.bits):
            return None
        val = 0
        for _ in range(num_bits):
            val = (val << 1) | self.bits[self.pos]
            self.pos += 1
        return val

def pack(s: str) -> bytes:
    alphabet = "abcdefghijklmnopqrstuvwxyz-.$"
    char_to_val = {char: i for i, char in enumerate(alphabet)}
    writer = BitWriter()
    for char in s:
        if char in char_to_val:
            writer.write(char_to_val[char], 5)
        else:
            writer.write(30, 5) # Escape
            writer.write(ord(char), 8)
    return writer.to_bytes()

def unpack(data: bytes) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz-.$"
    reader = BitReader(data)
    res = []
    while True:
        val = reader.read(5)
        if val is None:
            break
        if val == 30:
            char_val = reader.read(8)
            if char_val is None:
                break
            res.append(chr(char_val))
        elif val < len(alphabet):
            res.append(alphabet[val])
        else:
            # Padding bits at the end of the byte
            break
    return "".join(res)

s = "resort-ethernet-honor-quickly$"
packed = pack(s)
unpacked = unpack(packed)
print(f"Original: {s} ({len(s)} chars)")
print(f"Packed:   {packed.hex()} ({len(packed)} bytes)")
print(f"Unpacked: {unpacked}")
