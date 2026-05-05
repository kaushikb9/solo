"""Diagnose SSL certificate issues for the solo bot."""

import os
import ssl
import sys


def main() -> None:
    print(f"Python: {sys.version}")
    print(f"Platform: {sys.platform}")
    print(f"SSL library: {ssl.OPENSSL_VERSION}")
    print()

    # Check certifi
    try:
        import certifi

        ca_path = certifi.where()
        print(f"certifi CA bundle: {ca_path}")
        print(f"  exists: {os.path.exists(ca_path)}")
    except ImportError:
        print("certifi: NOT INSTALLED")
        return

    # Check SSL_CERT_FILE env var
    env_cert = os.environ.get("SSL_CERT_FILE")
    print(f"SSL_CERT_FILE env: {env_cert or '(not set)'}")
    print()

    # Test 1: stdlib SSL context (no certifi)
    print("--- Test 1: ssl.create_default_context() (system certs) ---")
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        import socket

        with socket.create_connection(("api.telegram.org", 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname="api.telegram.org") as ssock:
                print(f"  OK — connected to api.telegram.org ({ssock.version()})")
    except Exception as e:
        print(f"  FAIL — {e}")

    # Test 2: SSL context with certifi
    print("--- Test 2: ssl.create_default_context(cafile=certifi) ---")
    try:
        ctx = ssl.create_default_context(cafile=certifi.where())
        with socket.create_connection(("api.telegram.org", 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname="api.telegram.org") as ssock:
                print(f"  OK — connected to api.telegram.org ({ssock.version()})")
    except Exception as e:
        print(f"  FAIL — {e}")

    # Test 3: httpx with default config
    print("--- Test 3: httpx GET https://api.telegram.org (default verify) ---")
    try:
        import httpx

        r = httpx.get("https://api.telegram.org", timeout=5)
        print(f"  OK — status {r.status_code}")
    except Exception as e:
        print(f"  FAIL — {e}")

    # Test 4: httpx with certifi
    print("--- Test 4: httpx GET https://api.telegram.org (verify=certifi) ---")
    try:
        r = httpx.get("https://api.telegram.org", timeout=5, verify=certifi.where())
        print(f"  OK — status {r.status_code}")
    except Exception as e:
        print(f"  FAIL — {e}")

    # Test 5: httpx with SSL_CERT_FILE
    print("--- Test 5: httpx with SSL_CERT_FILE set ---")
    try:
        os.environ["SSL_CERT_FILE"] = certifi.where()
        r = httpx.get("https://api.telegram.org", timeout=5)
        print(f"  OK — status {r.status_code}")
    except Exception as e:
        print(f"  FAIL — {e}")

    print()
    print("If Test 1 fails but Test 2/4 pass, the fix is to use certifi explicitly.")


if __name__ == "__main__":
    main()
