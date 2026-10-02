"""b67 probe 3: WHY did probe 2 route to 'halted'? Isolate the kill-switch input."""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = Path(tempfile.mkdtemp(prefix="b67probe3_"))
import engines.paths as paths  # noqa: E402
paths.set_data_root(_tmp / "data")

from engines.kill_switch import check_kill_switch  # noqa: E402

now = datetime.now(timezone.utc)
# exactly what cycle() passes when the tick is dead but the account is healthy
for label, kw in {
    "healthy acct, no deals": dict(balance=4982.77, equity=4990.0, daily_pnl=0.0,
                                   consecutive_losses=0, margin_free=4890.0, margin=100.0),
    "dead account (all zero)": dict(balance=0, equity=0, daily_pnl=0.0,
                                    consecutive_losses=0, margin_free=0, margin=0),
}.items():
    print(label, "->", check_kill_switch(now=now, **kw))
