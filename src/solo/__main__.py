"""Entry point: uv run python -m solo."""

import logging

from solo.bot import main

logging.basicConfig(level=logging.INFO)
main()
