import pytest
from colabsync import link

def test_encode_decode_mnemonic():
    # nurse and cave are in BIP-39, ownership and read are NOT.
    url = "wss://nurse-cave-ownership-read.trycloudflare.com"
    secret = b"1234"
    
    encoded = link.encode(url, secret)
    decoded_url, decoded_secret = link.decode(encoded)
    
    assert decoded_url == url
    assert decoded_secret == secret
    
    # Check if shortening actually happened (intermediate string should be shorter)
    shortened = link._shorten_url(url)
    assert ".tc" in shortened
    assert "xo" in shortened # nurse -> xo
    assert "86" in shortened # cave -> 86
    assert "_ownership" in shortened
    assert "_read" in shortened

def test_encode_decode_full_mnemonic():
    # All these words are in BIP-39
    url = "wss://nurse-cave-above-absent.trycloudflare.com"
    secret = b"abcd"
    
    encoded = link.encode(url, secret)
    decoded_url, decoded_secret = link.decode(encoded)
    
    assert decoded_url == url
    assert decoded_secret == secret
    
    shortened = link._shorten_url(url)
    # indices for nurse (1212), cave (294), above (4), absent (5)
    assert shortened == "xo-86-4-5.tc" 

def test_fallback_non_mnemonic():
    # Words that are definitely NOT in BIP-39
    url = "wss://xyz123-qwerty-asdfgh.example.com"
    secret = b"4321"
    
    encoded = link.encode(url, secret)
    decoded_url, decoded_secret = link.decode(encoded)
    
    assert decoded_url == url
    assert decoded_secret == secret
    
    shortened = link._shorten_url(url)
    assert shortened == "_xyz123-_qwerty-_asdfgh.example.com"

def test_mixed_subdomain():
    # custom and tunnel ARE in BIP-39 (436 and 1876), 'my' is NOT.
    url = "wss://my-custom-tunnel.example.com"
    secret = b"mixd"
    
    encoded = link.encode(url, secret)
    decoded_url, decoded_secret = link.decode(encoded)
    
    assert decoded_url == url
    assert decoded_secret == secret
    
    shortened = link._shorten_url(url)
    assert shortened == "_my-c4-1g4.example.com"

def test_different_protocols():
    protocols = ["https://", "http://", "ws://", "wss://"]
    secret = b"prot"
    
    for p in protocols:
        url = f"{p}test-tunnel.example.com"
        encoded = link.encode(url, secret)
        decoded_url, decoded_secret = link.decode(encoded)
        
        expected = url if p == "wss://" else "wss://" + url[len(p):]
        assert decoded_url == expected

def test_no_subdomain():
    url = "wss://localhost"
    secret = b"local"
    encoded = link.encode(url, secret)
    decoded_url, decoded_secret = link.decode(encoded)
    assert decoded_url == url

def test_invalid_link():
    with pytest.raises(ValueError, match="Not a valid colabsync join link"):
        link.decode("invalid_link")
    
    # Very short or non-base64 characters usually result in "too short" 
    # because base64.urlsafe_b64decode is lenient by default.
    with pytest.raises(ValueError, match="Join link payload too short"):
        link.decode("colabsync1_@@@")
