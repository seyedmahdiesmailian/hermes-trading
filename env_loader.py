"""Minimal .env loader fallback — used only when python-dotenv is absent.

Mirrors python-dotenv defaults: KEY=VALUE lines, '#' comments ignored,
optional matching surrounding quotes stripped, and existing environment
variables are NEVER overridden. Values are never logged.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path) -> None:
    p = Path(path)
    if not p.is_file():
        return
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
