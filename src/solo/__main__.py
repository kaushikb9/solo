"""Entry point: uv run python -m solo

Configures SSL trust before importing telegram/httpx.
Handles corporate proxies (Zscaler) by appending custom CA
certs to certifi's bundle.
"""

import os
import tempfile
from pathlib import Path

import certifi


def _build_ca_bundle() -> str:
    """Build a CA bundle that includes certifi + any custom certs in certs/."""
    custom_certs_dir = Path(__file__).resolve().parents[2] / "certs"
    custom_pems = list(custom_certs_dir.glob("*.pem")) if custom_certs_dir.is_dir() else []

    if not custom_pems:
        return certifi.where()

    bundle = Path(certifi.where()).read_text()
    for pem in custom_pems:
        bundle += "\n" + pem.read_text()

    fd, path = tempfile.mkstemp(suffix=".pem", prefix="solo-ca-")
    os.write(fd, bundle.encode())
    os.close(fd)
    return path


os.environ["SSL_CERT_FILE"] = _build_ca_bundle()

import logging  # noqa: E402

logging.basicConfig(level=logging.INFO)

from solo.bot import main  # noqa: E402

main()
