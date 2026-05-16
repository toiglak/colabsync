import pytest
from colabsync import link

def test_encode_decode_roundtrip():
    urls = [
        "wss://resort-ethernet-honor-quickly.trycloudflare.com",
        "wss://nurse-cave-above-absent.trycloudflare.com",
        "https://my-custom-tunnel.example.com",
        "wss://localhost",
    ]
    secret = b"test"
    
    for url in urls:
        encoded = link.encode(url, secret)
        decoded_url, decoded_secret = link.decode(encoded)
        
        # Protocol might be normalized to wss://
        expected_url = url if "://" in url else "wss://" + url
        if expected_url.startswith("https://"):
            expected_url = "wss://" + expected_url[8:]
        elif expected_url.startswith("http://"):
            expected_url = "wss://" + expected_url[7:]
        elif expected_url.startswith("ws://"):
            expected_url = "wss://" + expected_url[5:]
            
        assert decoded_url == expected_url
        assert decoded_secret == secret

def test_different_protocols():
    protocols = ["https://", "http://", "ws://", "wss://"]
    secret = b"prot"
    
    for p in protocols:
        url = f"{p}test-tunnel.example.com"
        encoded = link.encode(url, secret)
        decoded_url, decoded_secret = link.decode(encoded)
        
        assert decoded_url == "wss://test-tunnel.example.com"
        assert decoded_secret == secret

def test_invalid_link():
    with pytest.raises(ValueError, match="Not a valid colabsync join link"):
        link.decode("invalid_link")
    
    # Garbage data after prefix will cause decoding errors
    with pytest.raises(ValueError, match="Invalid join link"):
        link.decode("cs1_@@@")

def test_secret_length():
    with pytest.raises(ValueError, match="Secret must be exactly 4 bytes"):
        link.encode("wss://test", b"too_long_secret")
