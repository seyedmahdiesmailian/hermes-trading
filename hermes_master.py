#!/usr/bin/env python3
"""Hermes Master — single-cycle runner for the active trading daemon.

Executes one full cycle of the active trading daemon (bridge fetch, market analysis,
SMC structure check, news guard, gates evaluation, orders/ledger sync, and position exit management).
"""
from __future__ import annotations

import logging
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from entry.hermes import HermesDaemon


def run_cycle() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    env_path = _ROOT / ".env"
    token = ""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("HERMES_BRIDGE_TOKEN="):
                token = line.split("=", 1)[1].strip()

    daemon = HermesDaemon(bridge_token=token)
    try:
        daemon._entry_loop()
        daemon._exit_loop()
        return 0
    finally:
        daemon.close()


if __name__ == "__main__":
    sys.exit(run_cycle())
