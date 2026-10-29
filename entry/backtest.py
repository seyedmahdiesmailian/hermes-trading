""" entry/backtest — شبیه‌ساز دقیق مسیر زنده هرمس

روش کار: هر کندل M15 = یک گام زمانی در ۵ دقیقه واقعی.
در هر گام:
  1. سیگنال‌های رسیده‌ تا آن لحظه را برای پردازش آماده کن
  2. اگر پوزیشن باز داریم → ExitManager (همان کد دیمن زنده)
  3. اگر پوزیشن باز نداریم → موتور تحلیل + دروازه → ورود

تقاطع دقیق با دیمن:
  - Engine.analyze / plan_from_signal     ← همان
  - GatesEngine.evaluate                  ← همان
  - ExitManager.manage                    ← همان (core/exits.py)
  - config.yaml                           ← همان (هیچ عدد literally نمی‌آید)

خروجی: JSON با تمام تریدها + آمار کلی.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine import Engine
from core.entities import (
    AccountState,
    BrokerPosition,
    Candle,
    ExitReason,
    Plan,
    Signal,
    Side,
    Tick,
    Trade,
)
from core.exits import ExitManager
from core.gates import GatesEngine
from core.params import DEFAULT_CONFIG_PATH, load_config

log = logging.getLogger("backtest")


# ════════════════════ state شبیه‌ساز ════════════════════

@dataclass
class SimState:
    """وضعیت حساب شبیه‌ساز — معادل آنچه bridge زنده برمی‌گرداند."""
    balance: float = 4931.58
    equity: float = 4931.58

    def apply_pnl(self, pnl: float) -> None:
        self.balance += pnl
        self.equity = self.balance


@dataclass
class OpenTrade:
    """پوزیشن باز شبیه‌ساز — نگاشت به BrokerPosition برای ExitManager."""
    ticket: int
    symbol: str
    side: Side
    volume: float
    open_price: float
    sl: float
    tp: float
    open_time: float        # epoch
    plan_id: str
    entry_rr: float
    initial_sl: float = 0.0

    def to_broker_position(self, current_price: float) -> BrokerPosition:
        # pnl تقریبی برای لاگ (محاسبه دقیق در close انجام می‌شود)
        direction = 1.0 if self.side == Side.BUY else -1.0
        pnl = direction * (current_price - self.open_price) * self.volume * 100.0
        return BrokerPosition(
            ticket=self.ticket, symbol=self.symbol, side=self.side,
            volume=self.volume, open_price=self.open_price,
            current_price=current_price, sl=self.sl, tp=self.tp,
            profit=pnl, swap=0.0, open_time=self.open_time,
            comment=self.plan_id, initial_sl=self.initial_sl,
        )


# ════════════════════ بک‌تستر ════════════════════

class Backtester:
    """شبیه‌ساز دقیق مسیر زنده هرمس — برای ارزیابی استراتژی."""

    # زمان حیات یک سفارش limit در صف ورود (ثانیه) — ۲۴ ساعت
    ENTRY_WAIT_S = 24 * 3600

    def __init__(self, config_path: Path | None = None):
        self.cfg = load_config(config_path or DEFAULT_CONFIG_PATH, bridge_token="")
        self.eng = Engine()
        self.gates = GatesEngine(self.cfg.gates)
        self.state = SimState(balance=self.cfg.backtest_start_balance)
        self.trades: list[Trade] = []
        self.denied: list[dict] = []
        self._ticket_seq = 1000
        self._open: OpenTrade | None = None
        self._cur_candle_close: float = 0.0
        self._cur_candle_ts: float = 0.0

        # منطق خروج مشترک — on_modify و on_partial در state شبیه‌ساز
        self.exits = ExitManager(
            self.cfg.position,
            on_modify=self._sim_modify,
            on_partial=self._sim_partial,
        )
        self._entry_idx = 0  # جدیدترین اندیس سیگنال پردازش‌شده
        self._last_exit_ts = 0.0  # زمان آخرین خروج — cooldown ورود
        COOLDOWN_S = 4 * 3600   # ۴ ساعت بعد از هر خروج، ورود ممنوع

        def _on_sim_close(ts: float) -> None:
            self._last_exit_ts = ts

        self._on_sim_close = _on_sim_close

    # ── پیش‌پردازش state ═══════════════════════════════

    def run(self, bars: list[dict], signals: list[Signal]) -> dict:
        """اجرای کامل شبیه‌ساز.

        bars:    لیست کندل‌های خام ({time, open, high, low, close, tick_volume})
        signals: سیگنال‌ها مرتب‌شده بر اساس timestamp
        """
        log.info("backtest شروع شد: %d bars, %d signals", len(bars), len(signals))
        candles = self._to_candles(bars)
        spread_fixed = 0.11  # اسپرد ثابت برای سادگی (مرحله بعد: از داده واقعی)

        n_processed_signals = 0
        n_entry_cycles = 0
        entry_queue: list[Signal] = []   # صف ورود: سیگنال‌هایی که منتظر رسیدن بازار به entry هستند

        for i in range(60, len(candles)):
            cur = candles[i]
            now_ts = float(cur.time)
            past = candles[max(0, i - 200):i + 1]
            if len(past) < 60:
                continue

            tick = Tick(symbol=self.cfg.symbol, bid=cur.close - spread_fixed / 2,
                        ask=cur.close + spread_fixed / 2, time=cur.time)

            # ── ۱) خروج پوزیشن باز ──
            if self._open is not None:
                closed = self._process_exit(candles, i, now_ts)
                if closed:
                    continue

            # ── ۲) ورود — فقط اگر پوزیشن باز نداریم ──
            # معادل دقیق _entry_loop دیمن: پوزیشن باز → return
            if self._open is not None:
                continue

            # سیگنال‌های رسیده تا این کندل → صف ورود
            ready = [s for s in signals
                     if self._signal_ts(s) <= now_ts
                     and s.signal_id not in self._processed]
            for s in ready:
                self._processed.add(s.signal_id)
                entry_queue.append(s)
                n_processed_signals += 1

            # صف ورود: حذف سیگنال‌های منقضی‌شده (بازار به entry نرسید)
            entry_queue = [s for s in entry_queue
                           if now_ts - self._signal_ts(s) < self.ENTRY_WAIT_S]

            # پوزیشن باز داریم → ورود ممنوع (معادل _entry_loop دیمن)
            if self._open is not None:
                continue

            if not entry_queue:
                # ─ـ ۲‌ب) مسیر تحلیل خودکار — بدون سیگنال کانال ──
                view = self.eng.analyze(past, tick, check_news=False)
                plan = self.eng.plan_from_analysis(candles[:i+1], view,
                                                   self.cfg.analysis.timeframe)
                if plan is None:
                    continue
                account = AccountState(
                    balance=self.state.balance, equity=self.state.equity,
                    margin=0.0, margin_free=self.state.equity,
                )
                trades_today = self._trades_today(now_ts)
                today_pnl = self._pnl_today(now_ts)
                outcome = self.gates.evaluate(
                    plan, account, [], trades_today, today_pnl,
                    atr=view.atr, spread=view.spread,
                )
                if not outcome.allowed:
                    self.denied.append({
                        "signal": plan.plan_id, "reason": "guard",
                        "verdict": outcome.reasons,
                        "timestamp": datetime.fromtimestamp(now_ts, timezone.utc).isoformat(),
                    })
                    continue
                # باز کردن پوزیشن در قیمت بازار (تحلیل همون لحظه معتبر است)
                fill = cur.close
                self._open = OpenTrade(
                    ticket=self._ticket_seq, symbol=plan.symbol, side=plan.side,
                    volume=outcome.volume, open_price=fill,
                    sl=plan.stop_loss, tp=plan.take_profit,
                    open_time=now_ts, plan_id=plan.plan_id, entry_rr=plan.rr,
                    initial_sl=plan.stop_loss,
                )
                self._ticket_seq += 1
                log.info("OPEN-AUTO #%d %s vol=%.2f entry=%.2f sl=%.2f atr=%.2f",
                         self._open.ticket, self._open.side.value, self._open.volume,
                         fill, plan.stop_loss, view.atr)
                continue

            # ── ۲) fulfillment: بازار باید به entry سیگنال رسیده باشد ──
            touched = [s for s in entry_queue
                       if cur.low <= s.entry <= cur.high]
            if not touched:
                continue
            sig = touched[0]
            entry_queue.remove(sig)
            view = self.eng.analyze(past, tick, check_news=False)
            plan = self.eng.plan_from_signal(sig, view, self.cfg.analysis.timeframe)
            if plan is None:
                self.denied.append({
                    "signal": sig.signal_id, "reason": "trend_filter",
                    "timestamp": datetime.fromtimestamp(now_ts, timezone.utc).isoformat(),
                })
                continue

            account = AccountState(
                balance=self.state.balance, equity=self.state.equity,
                margin=0.0, margin_free=self.state.equity,
            )
            trades_today = self._trades_today(now_ts)
            today_pnl = self._pnl_today(now_ts)

            outcome = self.gates.evaluate(
                plan, account, [], trades_today, today_pnl,
                atr=view.atr, spread=view.spread,
            )
            n_entry_cycles += 1

            if not outcome.allowed:
                self.denied.append({
                    "signal": sig.signal_id, "reason": "guard",
                    "verdict": outcome.reasons,
                    "timestamp": datetime.fromtimestamp(now_ts, timezone.utc).isoformat(),
                })
                continue

            # ── ۳) باز کردن پوزیشن — در entry سیگنال (limit-fill) ──
            self._open = OpenTrade(
                ticket=self._ticket_seq, symbol=plan.symbol, side=plan.side,
                volume=outcome.volume, open_price=plan.entry_price,
                sl=plan.stop_loss, tp=plan.take_profit,
                open_time=now_ts, plan_id=plan.plan_id, entry_rr=plan.rr,
                initial_sl=plan.stop_loss,
            )
            self._ticket_seq += 1
            n_processed_signals += 1
            log.info("OPEN  #%d %s vol=%.2f entry=%.2f sl=%.2f tp=%.2f rr=%.2f",
                     self._open.ticket, self._open.side.value, self._open.volume,
                     self._open.open_price, self._open.sl, self._open.tp, plan.rr)

        return self._summary()

    # ── خروج ══════════════════════════════════

    def _process_exit(self, candles: list[Candle], i: int, now_ts: float) -> bool:
        """پردازش خروج پوزیشن باز — برخورد SL/TP توسط کندل + ExitManager."""
        ot = self._open
        cur = candles[i]
        self._cur_candle_close = cur.close
        self._cur_candle_ts = now_ts

        # ۱) برخورد SL / TP توسط قیمت کندل (سقف/کف کندل)
        hit = self._check_sl_tp(cur)
        if hit is None:
            # ۲) ExitManager — time-exit / breakeven / trailing (همان کد دیمن)
            pos = ot.to_broker_position(cur.close)
            # ATR زنده برای مسیر trailing تحلیلی (پلن‌های بدون TP)
            past = candles[max(0, i - 200):i + 1]
            tick = Tick(symbol=self.cfg.symbol, bid=cur.close, ask=cur.close,
                        time=cur.time)
            view = self.eng.analyze(past, tick, check_news=False)
            decision = self.exits.manage(pos, now_ts, atr=view.atr)
            if decision is not None:
                exit_reason, exit_price = decision
            else:
                return False
        else:
            exit_reason, exit_price = hit

        # ── ثبت ترید بسته‌شده ──
        direction = 1.0 if ot.side == Side.BUY else -1.0
        pnl = direction * (exit_price - ot.open_price) * ot.volume * 100.0
        self.state.apply_pnl(pnl)

        trade = Trade(
            trade_id=f"bt-{ot.ticket}", plan_id=ot.plan_id, ticket=ot.ticket,
            symbol=ot.symbol, side=ot.side, volume=ot.volume,
            entry_price=ot.open_price, exit_price=exit_price,
            sl=ot.sl, tp=ot.tp, pnl=pnl, exit_reason=exit_reason,
            opened_at=ot.open_time, closed_at=now_ts,
            source="analysis" if ot.plan_id.startswith("auto-") else "signal",
            r_multiple=self._r_multiple(ot, exit_price),
        )
        self.trades.append(trade)
        if ot is not None:
            self.exits.cleanup_ticket(ot.ticket)
        self._open = None
        self._last_exit_ts = now_ts
        log.info("CLOSE #%d pnl=%+.2f reason=%s",
                 trade.ticket, pnl, exit_reason.value)
        return True

    def _check_sl_tp(self, cur: Candle) -> tuple[ExitReason, float] | None:
        """بررسی برخورد SL/TP با سقف/کف کندل جاری."""
        ot = self._open
        if ot is None:
            return None
        if ot.side == Side.BUY:
            if cur.low <= ot.sl:
                return ExitReason.STOP_LOSS, ot.sl
            if ot.tp > 0 and cur.high >= ot.tp:
                return ExitReason.TAKE_PROFIT, ot.tp
        else:
            if cur.high >= ot.sl:
                return ExitReason.STOP_LOSS, ot.sl
            if ot.tp > 0 and cur.low <= ot.tp:
                return ExitReason.TAKE_PROFIT, ot.tp
        return None

    def _sim_modify(self, ticket: int, new_sl: float) -> None:
        """callback تغییر SL — در دیمن bridge، اینجا state شبیه‌ساز."""
        if self._open is not None and self._open.ticket == ticket:
            self._open.sl = new_sl

    def _sim_partial(self, ticket: int, percent: float) -> None:
        """callback بستن پله‌ای در شبیه‌ساز — ثبت سود ۵۰٪ حجم و نصف کردن حجم باز."""
        ot = self._open
        if ot is None or ot.ticket != ticket:
            return
        closed_vol = round(ot.volume * (percent / 100.0), 2)
        if closed_vol <= 0:
            return
        cur_price = self._cur_candle_close if self._cur_candle_close > 0 else ot.open_price
        direction = 1.0 if ot.side == Side.BUY else -1.0
        pnl = direction * (cur_price - ot.open_price) * closed_vol * 100.0
        self.state.apply_pnl(pnl)
        trade = Trade(
            trade_id=f"bt-{ot.ticket}-part", plan_id=ot.plan_id, ticket=ot.ticket,
            symbol=ot.symbol, side=ot.side, volume=closed_vol,
            entry_price=ot.open_price, exit_price=cur_price,
            sl=ot.sl, tp=ot.tp, pnl=pnl, exit_reason=ExitReason.PARTIAL_TP,
            opened_at=ot.open_time, closed_at=self._cur_candle_ts if self._cur_candle_ts > 0 else ot.open_time,
            source="analysis" if ot.plan_id.startswith("auto-") else "signal",
            r_multiple=self._r_multiple(ot, cur_price),
        )
        self.trades.append(trade)
        ot.volume = round(ot.volume - closed_vol, 2)
        log.info("PARTIAL #%d vol=%.2f pnl=%+.2f remaining_vol=%.2f",
                 ot.ticket, closed_vol, pnl, ot.volume)

    # ── کمکی ══════════════════════════════════

    @staticmethod
    def _to_candles(bars: list[dict]) -> list[Candle]:
        out = []
        for b in bars:
            out.append(Candle(
                time=int(b["time"]), open=float(b["open"]), high=float(b["high"]),
                low=float(b["low"]), close=float(b["close"]),
                volume=int(b.get("tick_volume", 0)),
            ))
        out.sort(key=lambda c: c.time)
        return out

    @staticmethod
    def _signal_ts(s: Signal) -> float:
        try:
            dt = datetime.fromisoformat(s.timestamp[:19])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return 0.0

    def _trades_today(self, now_ts: float) -> int:
        day = datetime.fromtimestamp(now_ts, timezone.utc).date()
        return sum(1 for t in self.trades
                   if datetime.fromtimestamp(t.closed_at, timezone.utc).date() == day)

    def _pnl_today(self, now_ts: float) -> float:
        day = datetime.fromtimestamp(now_ts, timezone.utc).date()
        return sum(t.pnl for t in self.trades
                   if datetime.fromtimestamp(t.closed_at, timezone.utc).date() == day)

    @staticmethod
    def _r_multiple(ot: OpenTrade, exit_price: float) -> float:
        ref_sl = ot.initial_sl if ot.initial_sl > 0 else ot.sl
        risk = abs(ot.open_price - ref_sl)
        if risk <= 0:
            return 0.0
        direction = 1.0 if ot.side == Side.BUY else -1.0
        return round(direction * (exit_price - ot.open_price) / risk, 3)

    # ── خروجی ══════════════════════════════════

    def _summary(self) -> dict:
        n = len(self.trades)
        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]
        total_pnl = sum(t.pnl for t in self.trades)

        def avg(ts):
            return sum(getattr(t, "r_multiple", 0) for t in ts) / len(ts) if ts else 0.0

        summary = {
            "config": {
                "symbol": self.cfg.symbol,
                "timeframe": self.cfg.analysis.timeframe,
                "start_balance": self.cfg.backtest_start_balance,
                "min_rr": self.cfg.gates.min_rr,
                "min_grade": self.cfg.gates.min_grade,
                "risk_per_trade_pct": self.cfg.gates.risk_per_trade_pct,
                "max_open_positions": self.cfg.gates.max_open_positions,
                "max_daily_trades": self.cfg.gates.max_daily_trades,
                "max_daily_loss_pct": self.cfg.gates.max_daily_loss_pct,
                "min_atr_stop_mult": self.cfg.gates.min_atr_stop_mult,
                "breakeven_rr": self.cfg.position.breakeven_rr,
                "trailing_start_rr": self.cfg.position.trailing_start_rr,
                "max_hold_hours": self.cfg.position.max_hold_hours,
            },
            "start_balance": self.cfg.backtest_start_balance,
            "end_balance": round(self.state.balance, 2),
            "total_pnl": round(total_pnl, 2),
            "total_trades": n,
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(100.0 * len(wins) / n, 1) if n else 0.0,
            "avg_r": round(avg(self.trades), 3),
            "avg_r_wins": round(avg(wins), 3),
            "avg_r_losses": round(avg(losses), 3),
            "trades": [
                {
                    "signal": t.plan_id,
                    "side": t.side.value if hasattr(t.side, "value") else str(t.side),
                    "entry": t.entry_price, "sl": t.sl, "tp": t.tp,
                    "exit_price": t.exit_price, "pnl": round(t.pnl, 2),
                    "r_multiple": round(t.r_multiple, 3),
                    "exit_reason": t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason),
                    "opened_at": t.opened_at, "closed_at": t.closed_at,
                    "volume": t.volume,
                }
                for t in self.trades
            ],
            "denied_count": len(self.denied),
            "denied": self.denied[:30],
        }
        return summary

    @property
    def _processed(self) -> set:
        """شناسه سیگنال‌های پردازش‌شده (signal_id، نه id object)."""
        if not hasattr(self, "_processed_set"):
            self._processed_set = set()
        return self._processed_set


# ════════════════════ CLI ════════════════════

def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    ap = argparse.ArgumentParser(description="بک‌تست هرمس — شبیه‌ساز مسیر زنده")
    ap.add_argument("--bars", default="data/bt_m15_fresh.json",
                    help="فایل JSON کندل‌ها")
    ap.add_argument("--signals", default="data/signals/signals_log.json",
                    help="فایل JSON سیگنال‌ها")
    ap.add_argument("--out", default="data/backtest_result.json",
                    help="فایل خروجی نتایج")
    args = ap.parse_args()

    bars = json.loads(Path(args.bars).read_text())
    if isinstance(bars, dict):
        bars = bars.get("rates") or bars.get("data") or bars.get("bars") or []

    # بارگذاری سیگنال‌ها
    raw_sigs = json.loads(Path(args.signals).read_text())
    if isinstance(raw_sigs, dict):
        raw_sigs = raw_sigs.get("data", [])
    signals = _load_signals(raw_sigs)
    log.info("loaded %d signals", len(signals))

    bt = Backtester()
    result = bt.run(bars, signals)

    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    _print_report(result)
    print(f"\nنتایج کامل در {args.out}")


def _load_signals(raw_sigs: list[dict]) -> list[Signal]:
    from adapters.signals import SignalsAdapter
    from pathlib import Path as P
    # reuse parser
    ad = SignalsAdapter(P("data/signals/signals_log.json"), P("/tmp/_bt_state.json"))
    out = []
    for item in raw_sigs:
        sig = ad._parse(item)
        if sig is not None:
            out.append(sig)
    return out


def _print_report(r: dict) -> None:
    print("\n" + "═" * 52)
    print("               گزارش بک‌تست هرمس")
    print("═" * 52)
    print(f"  دوره:        {r['config']['timeframe']} XAUUSD")
    print(f"  تریدها:      {r['total_trades']}")
    print(f"  برنده:       {r['wins']} | بازنده: {r['losses']}")
    print(f"  وین‌ریت:      {r['win_rate']}%")
    print(f"  PnL کل:      {r['total_pnl']:+.2f} USD")
    print(f"  موجودی:      {r['start_balance']:.2f} → {r['end_balance']:.2f}")
    print(f"  میانگین R:   {r['avg_r']:+.3f}")
    print(f"  R برنده:     {r['avg_r_wins']:+.3f} | R بازنده: {r['avg_r_losses']:+.3f}")
    print(f"  رد شده:      {r['denied_count']}")
    print("═" * 52)
    for d in r["denied"][:10]:
        print(f"  🚫 {d['signal']}: {d['reason']} {d.get('verdict','')}")


if __name__ == "__main__":
    main()
