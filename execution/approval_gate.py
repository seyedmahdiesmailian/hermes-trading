#!/usr/bin/env python3
from __future__ import annotations

DRY_RUN_DEFAULT = True

VALID_COMMANDS = {"/trade", "/close", "/partial", "/modify", "/skip"}

def parse_command(text: str | None) -> dict | None:
    """Parse command text like: /trade BUY 0.05 4590 4620"""
    if not text:
        return None
    parts = text.strip().split()
    if not parts or parts[0] not in VALID_COMMANDS:
        return {"ok": False, "error": "unknown_command", "raw": text}
    cmd = parts[0]
    if cmd == "/skip":
        return {"ok": True, "command": cmd}
    try:
        if cmd == "/trade":
            # Format: /trade BUY 0.05 4590 4620  (side lot [sl_price] [tp_price])
            return {
                "ok": True,
                "command": cmd,
                "side": parts[1].upper(),
                "lot": float(parts[2]) if len(parts) > 2 else 0.01,
                "sl": float(parts[3]) if len(parts) > 3 else None,
                "tp": float(parts[4]) if len(parts) > 4 else None,
            }
        if cmd == "/close":
            return {"ok": True, "command": cmd, "ticket": int(parts[1])}
        if cmd == "/partial":
            return {"ok": True, "command": cmd, "ticket": int(parts[1]), "percent": float(parts[2])}
        if cmd == "/modify":
            out = {"ok": True, "command": cmd, "ticket": int(parts[1]), "sl": None, "tp": None}
            for p in parts[2:]:
                if p.startswith('sl='):
                    out['sl'] = float(p.split('=', 1)[1])
                if p.startswith('tp='):
                    out['tp'] = float(p.split('=', 1)[1])
            return out
    except Exception as e:
        return {"ok": False, "error": f"parse_error:{e}", "raw": text}
    return {"ok": False, "error": "unsupported", "raw": text}

def execute_approved_command(bridge, command: dict, dry_run: bool = DRY_RUN_DEFAULT) -> dict:
    """Execute a user-approved command. Never executes in dry-run mode."""
    if not command:
        return {"ok": True, "action": "none"}
    if not command.get("ok"):
        return command
    cmd = command.get("command")

    # Always skip in dry-run
    if cmd == "/skip":
        return {"ok": True, "skipped": True}

    if dry_run:
        return {"ok": True, "dry_run": True, "would_execute": command}

    if cmd == "/trade":
        # User provides actual SL/TP prices (not points)
        return bridge.send_order(
            side=command['side'],
            lot=command['lot'],
            symbol='XAUUSD',
            sl=command.get('sl'),
            tp=command.get('tp'),
        )
    if cmd == "/close":
        return bridge.close_position(command['ticket'])
    if cmd == "/partial":
        return bridge.partial_close(command['ticket'], command['percent'])
    if cmd == "/modify":
        return bridge.modify_position(command['ticket'], command.get('sl'), command.get('tp'))
    return {"ok": False, "error": "unsupported_command"}
