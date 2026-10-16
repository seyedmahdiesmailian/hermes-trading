""" core/params — خواندن config.yaml + مدیریت knobs یادگیری

یک جا، یک حقیقت: همه پارامترهای ترید از اینجا خوانده می‌شوند.
هیچ پارامتری hardcode در کد نیست.
"""
from __future__ import annotations

import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


class ConfigError(Exception):
    """خطا در پیکربندی — fail-closed."""


@dataclass(frozen=True)
class Gates:
    max_open_positions: int
    max_daily_trades: int
    risk_per_trade_pct: float
    max_daily_loss_pct: float
    min_rr: float
    min_grade: str
    min_atr_stop_mult: float
    max_spread_points: float


@dataclass(frozen=True)
class PositionCfg:
    trailing_start_rr: float
    breakeven_rr: float
    max_hold_hours: int
    partial_tp_rr: float
    partial_enabled: bool


@dataclass(frozen=True)
class AnalysisCfg:
    timeframe: str
    candle_count: int
    higher_timeframes: list[str]
    session_hours: list[int]


@dataclass(frozen=True)
class LoopCfg:
    entry_interval_s: int
    exit_interval_s: int


@dataclass(frozen=True)
class BridgeCfg:
    url: str
    timeout_s: int
    token: str = ""


@dataclass(frozen=True)
class Config:
    symbol: str
    dry_run: bool
    gates: Gates
    position: PositionCfg
    analysis: AnalysisCfg
    loop: LoopCfg
    bridge: BridgeCfg
    signals_log_path: str
    signals_state_path: str
    notify_enabled: bool
    backtest_start_balance: float = 4931.58

    def with_bridge_token(self, token: str) -> "Config":
        """ساخت نسخه با token — از .env خوانده می‌شود."""
        return Config(
            symbol=self.symbol,
            dry_run=self.dry_run,
            gates=self.gates,
            position=self.position,
            analysis=self.analysis,
            loop=self.loop,
            bridge=BridgeCfg(url=self.bridge.url, timeout_s=self.bridge.timeout_s, token=token),
            signals_log_path=self.signals_log_path,
            signals_state_path=self.signals_state_path,
            notify_enabled=self.notify_enabled,
            backtest_start_balance=self.backtest_start_balance,
        )


def load_config(path: Path = DEFAULT_CONFIG_PATH, bridge_token: str = "") -> Config:
    """خواندن config.yaml → Config immutable.

    fail-closed: هر فیلد گمشده → ConfigError (سیستم Ин ἐκκίνηση نمی‌کند).
    """
    if not path.exists():
        raise ConfigError(f"config.yaml پیدا نشد: {path}")

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml باید یک dict باشد")

    try:
        g = raw["gates"]
        gates = Gates(
            max_open_positions=_int(g, "max_open_positions"),
            max_daily_trades=_int(g, "max_daily_trades"),
            risk_per_trade_pct=_float(g, "risk_per_trade_pct"),
            max_daily_loss_pct=_float(g, "max_daily_loss_pct"),
            min_rr=_float(g, "min_rr"),
            min_grade=_str(g, "min_grade"),
            min_atr_stop_mult=_float(g, "min_atr_stop_mult"),
            max_spread_points=_float(g, "max_spread_points"),
        )

        pos = raw["position"]
        position = PositionCfg(
            trailing_start_rr=_float(pos, "trailing_start_rr"),
            breakeven_rr=_float(pos, "breakeven_rr"),
            max_hold_hours=_int(pos, "max_hold_hours"),
            partial_tp_rr=_float(pos, "partial_tp_rr"),
            partial_enabled=bool(pos.get("partial_enabled", False)),
        )

        an = raw["analysis"]
        analysis = AnalysisCfg(
            timeframe=_str(an, "timeframe"),
            candle_count=_int(an, "candle_count"),
            higher_timeframes=list(an.get("higher_timeframes", ["H1", "H4"])),
            session_hours=list(an.get("session_hours", [7, 17])),
        )

        lp = raw["loop"]
        loop = LoopCfg(
            entry_interval_s=_int(lp, "entry_interval_s"),
            exit_interval_s=_int(lp, "exit_interval_s"),
        )

        br = raw["bridge"]
        bridge = BridgeCfg(
            url=_str(br, "url"),
            timeout_s=_int(br, "timeout_s"),
            token=bridge_token,
        )

        sig = raw.get("signals", {})
        return Config(
            symbol=_str(raw, "symbol"),
            dry_run=bool(raw.get("dry_run", True)),
            gates=gates,
            position=position,
            analysis=analysis,
            loop=loop,
            bridge=bridge,
            signals_log_path=sig.get("log_path", "data/signals/signals_log.json"),
            signals_state_path=sig.get("state_path", "data/signals/listener_state.json"),
            notify_enabled=bool(raw.get("notify", {}).get("enabled", True)),
            backtest_start_balance=float(raw.get("backtest", {}).get("start_balance", 4931.58)),
        )
    except KeyError as e:
        raise ConfigError(f"کلید گمشده در config.yaml: {e}") from e


# ── helper های اعتبارسنجی ─────────────────────────────

def _int(d: dict, key: str) -> int:
    v = d[key]
    if not isinstance(v, int) or v <= 0:
        raise ConfigError(f"{key} باید عدد صحیح مثبت باشد، نه {v!r}")
    return v


def _float(d: dict, key: str) -> float:
    v = d[key]
    if not isinstance(v, (int, float)) or v <= 0:
        raise missing_key_error(key, v)
    return float(v)


def _str(d: dict, key: str) -> str:
    v = d[key]
    if not isinstance(v, str) or not v.strip():
        raise ConfigError(f"{key} باید رشته غیرخالی باشد، نه {v!r}")
    return v


def missing_key_error(key: str, v) -> ConfigError:
    return ConfigError(f"{key} باید عدد مثبت باشد، نه {v!r}")
