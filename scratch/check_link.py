import zlib
from colabsync import link

def test_example(url, secret):
    encoded = link.encode(url, secret)
    decoded_url, decoded_secret = link.decode(encoded)
    print(f"URL:     {url}")
    print(f"Encoded: {encoded}")
    print(f"Decoded: {decoded_url}")
    print(f"Length:  {len(encoded)}")
    print("-" * 20)

secret = b"test"
test_example("wss://resort-ethernet-honor-quickly.trycloudflare.com", secret)
test_example("wss://nurse-cave-above-absent.trycloudflare.com", secret)
test_example("wss://localhost", secret)
