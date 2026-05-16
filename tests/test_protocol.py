import json
from pathlib import Path
from colabsync import protocol

def test_put_msg(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    file_path = root / "test.txt"
    file_path.write_text("hello world")
    
    msg = protocol.put_msg(root, file_path)
    
    # Check format: header + \0 + body
    assert b"\0" in msg
    header_end = msg.index(b"\0")
    header = json.loads(msg[:header_end].decode())
    assert header["type"] == "put"
    assert header["path"] == "test.txt"
    assert msg[header_end+1:] == b"hello world"

def test_parse_binary_put(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    file_path = root / "test.txt"
    file_path.write_text("data")
    
    msg = protocol.put_msg(root, file_path)
    rel_path, data = protocol.parse_binary_put(msg)
    
    assert rel_path == "test.txt"
    assert data == b"data"

def test_batch_msg(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    f1 = root / "f1.txt"
    f1.write_text("content1")
    f2 = root / "f2.txt"
    f2.write_text("content2")
    
    m1 = protocol.put_msg(root, f1)
    m2 = protocol.put_msg(root, f2)
    m3 = protocol.delete_msg(root, root / "deleted.txt")
    
    batch = protocol.batch_msg([m1, m2, m3])
    results = protocol.parse_batch(batch)
    
    assert len(results) == 3
    assert results[0][0] == "put"
    assert results[0][1] == ("f1.txt", b"content1")
    assert results[1][0] == "put"
    assert results[1][1] == ("f2.txt", b"content2")
    assert results[2][0] == "json"
    assert results[2][1]["type"] == "delete"
    assert results[2][1]["path"] == "deleted.txt"
