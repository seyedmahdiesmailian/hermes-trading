"""WP2 — the ONE canonical reader of infrastructure configuration.

Why this module exists (b40/b52 pattern: one fact, one reader): the bridge
host, the Telegram chat id and the DRY_RUN parse each lived in 5–14 places
with subtly different fallback chains. A relocation (new Windows box, new
owner chat) meant hunting literals across daemons, engines and scripts —
and the copies had already drifted (ops chat: flat default in the daemons
vs nested fallback in the monitors).

Rules:
- Call-time reads (b39 discipline): every accessor reads os.environ when
  called, never at import — except where the CALLER needs import-time
  values (bridge_client's module constants), which just call these
  functions at import. Same timing, one spelling.
- Values are IDENTICAL to the pre-WP2 literals (pinned by
  tests/test_wp2_config_parity.py), with exactly two documented
  normalizations (see bridge_url() and ops_chat_id()).
- Leaf module: imports nothing from engines (no import cycle possible).
  engines.paths.PRODUCTION_ROOT stays where it is (b66 pins its home);
  use production_root() only as a discoverable pointer to it.

INTENTIONALLY NOT centralized here (strategy thresholds stay with the
modules that own them — they are pinned by behaviour tests that import
them by name, e.g. b197 reads auto_executor.MAX_RISK_PER_TRADE_PCT):
  auto_executor: MAX_RISK_PER_TRADE_PCT=0.02, MIN_RISK_REWARD=1.5,
      MAX_DAILY_LOSS_PCT=0.05, MAX_DAILY_TRADES=5, MAX_OPEN_POSITIONS=1
  kill_switch: DAILY_LOSS_LIMIT_PCT=0.05, EQUITY_DRAWDOWN_LIMIT_PCT=0.10,
      CONSECUTIVE_LOSSES_LIMIT=4, MARGIN_RATIO_MIN=10, COOLDOWN_HOURS=4
  learning: RISK_PCT_CEILING=0.02, RISK_PCT_FLOOR=0.005,
      RR_FLOOR 1.0–2.5, GRADE_CEILING=A, MIN_TRADES_SAMPLE=15
  plan: SMC_CONF_FLOOR=0.4, RANGE_KILL_CONF=0.35, MIN_SETUP_GRADE=B,
      REANCHOR_STOP_ATR_CAP=2.0, REANCHOR_MIN_RR=1.5
  cooldown/macro/market: POST_OPEN 15m, RESTART 5m, news blackout 30m,
      XAUUSD Sun 23:00 → Fri 22:00 UTC, broker SANITY ±14h
  Rewiring those is Phase-3 engine work, not WP2 plumbing.
"""
from __future__ import annotations

import os

# ─── Canonical defaults (each literal lives HERE and nowhere else) ───
DEFAULT_WIN_IP = "192.168.10.51"     # Windows MT5 bridge host (last-known)
DEFAULT_BRIDGE_PORT = 5050           # bridge HTTP port
DEFAULT_LAN_IP = "192.168.10.18"     # this Linux box, as seen by Windows
DEFAULT_CHAT_ID = "194015957"        # owner chat (trade bot + ops fallback)
DEFAULT_WIN_USER = "Administrator"   # WinRM user for deploy + backup
# NOTE: the double backslash is INTENTIONAL — offsite_backup.py shipped
# 'C:\\\\HermesBackups' (two literal backslashes; PowerShell tolerates it)
# and WP2 preserves the value byte-for-byte. Do not "fix" this here; file
# a backlog item if the path should ever be normalized.
DEFAULT_WIN_BACKUP_DIR = "C:\\\\HermesBackups"


# ─── Network identity ────────────────────────────────────────────────

def win_ip() -> str:
    """Windows bridge host: HERMES_WIN_IP, else last-known default."""
    return os.getenv("HERMES_WIN_IP", DEFAULT_WIN_IP)


def win_host() -> str:
    """WinRM target: explicit WIN_HOST override > HERMES_WIN_IP > default.

    The b62 chain, previously restated in offsite_backup.py (deploy scripts
    keep their own restatement: manual SecOps tools, deliberately untouched).
    """
    return os.getenv("WIN_HOST") or os.getenv("HERMES_WIN_IP", DEFAULT_WIN_IP)


def bridge_url() -> str:
    """Bridge base URL. Precedence (b52/b63): explicit HERMES_BRIDGE_URL >
    derived from HERMES_WIN_IP > last-known default.

    NORMALIZATION (documented): the empty-string URL now falls back to the
    derived URL (``or``-form, like weekly_report/health already did) instead
    of being honored as "" (bridge_client's old getenv-default form). An
    empty URL was never a working value — it only produced requests to
    "/health" — so this strictly trades a confusing breakage for the
    derived address every other consumer already used.
    """
    return (os.getenv("HERMES_BRIDGE_URL")
            or f"http://{win_ip()}:{DEFAULT_BRIDGE_PORT}")


def bridge_token() -> str | None:
    """Bearer token for the bridge (None = unauthenticated call)."""
    return os.getenv("HERMES_BRIDGE_TOKEN")


def lan_ip() -> str:
    """This box's LAN address (Windows pulls the backup tarball from here)."""
    return os.getenv("HERMES_LAN_IP", DEFAULT_LAN_IP)


def win_user() -> str:
    return os.getenv("WIN_USER", DEFAULT_WIN_USER)


def win_pass() -> str:
    """WinRM password, soft form ('' when unset — offsite_backup checks)."""
    return os.getenv("WIN_PASS", "")


def win_backup_dir() -> str:
    return os.getenv("WIN_BACKUP_DIR", DEFAULT_WIN_BACKUP_DIR)


# ─── Bridge timeouts (seconds; values unchanged from bridge_client) ──
BRIDGE_TIMEOUT_GET = 8
BRIDGE_TIMEOUT_POST = 12
BRIDGE_TIMEOUT_HEALTH = 5


# ─── Telegram identity ───────────────────────────────────────────────

def telegram_bot_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "")


def telegram_chat_id() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", DEFAULT_CHAT_ID)


def ops_bot_token() -> str:
    """Ops/3rd bot with falsy-fallback to the trade bot (b37 routing).

    ``or``-form preserved exactly: an explicitly emptied ops token falls
    back to the trade token, it does not mute ops alerts.
    """
    return (os.getenv("AUTOPILOT_REPORT_BOT_TOKEN", "")
            or os.getenv("TELEGRAM_BOT_TOKEN", ""))


def ops_chat_id() -> str:
    """Ops chat: AUTOPILOT_REPORT_CHAT_ID > TELEGRAM_CHAT_ID > default.

    NORMALIZATION (documented): the daemons and dashboard_bot used a FLAT
    default (REPORT_CHAT_ID else the owner literal), the monitors used this
    NESTED chain. Nested wins: when REPORT_CHAT_ID is unset but
    TELEGRAM_CHAT_ID
    is set, ops alerts follow the trade chat instead of the literal. On the
    production .env both are set (to the same id), so this is a no-op
    there — and everywhere else it is the coherent reading of b37.
    """
    return os.getenv("AUTOPILOT_REPORT_CHAT_ID",
                     os.getenv("TELEGRAM_CHAT_ID", DEFAULT_CHAT_ID))


def signal_group() -> str:
    """Telegram signal-group chat id(s), comma-separated; '' = unconfigured."""
    return os.getenv("TELEGRAM_SIGNAL_GROUP", "")


# ─── Runtime mode ────────────────────────────────────────────────────

def dry_run() -> bool:
    """True unless HERMES_DRY_RUN explicitly says otherwise.

    The exact 5x-repeated parse (hermes_master, hermes_runtime.main,
    position/signal daemons, signal_monitor): default 'true', false only
    for {'0', 'false', 'no'} (case-insensitive). Safe default preserved.
    """
    return os.getenv("HERMES_DRY_RUN", "true").lower() not in {
        "0", "false", "no"}


# ─── Repo root pointer (b66: the literal itself stays in paths) ──────

def production_root():
    """Discoverable pointer to the ONE canonical install default.

    The literal lives in engines.paths.PRODUCTION_ROOT (pinned there by
    test_b66 — do NOT move it); this accessor exists so config readers
    find it without learning a second module. Imported lazily to keep
    this module cycle-free.
    """
    from engines import paths
    return paths.PRODUCTION_ROOT
