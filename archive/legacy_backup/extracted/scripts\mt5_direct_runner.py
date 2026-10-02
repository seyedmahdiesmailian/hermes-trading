import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run_mt5_direct_command(argv):
    script = ROOT / "mt5_direct.py"
    cmd = [sys.executable, str(script), *argv]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    stdout = (result.stdout or "").strip()
    if not stdout:
        return {"ok": False, "error": "empty_stdout", "exit_code": result.returncode, "stderr": result.stderr}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid_json", "exit_code": result.returncode, "stdout": stdout, "stderr": result.stderr}
    payload["exit_code"] = result.returncode
    return payload
