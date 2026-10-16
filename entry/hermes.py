""" entry/hermes — دیمن اصلی هرمس

یک پروسه. یک حلقه. یک حقیقت.

تایمر ورود (هر	config.loop.entry_interval_s):
	bridge → candles/tick/account/positions → signals → engine → gates → order

تایمر خروج (هر config.loop.exit_interval_s):
	bridge → positions زنده → breakeven/trailing/time-exit → close

هرگز از دیتابیس برای تصمیم نمی‌خواند. دیتابیس = دفتر کل فقط.
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.mt5 import BridgeError, Mt5Adapter
from adapters.notify import NotifyAdapter
from adapters.signals import SignalsAdapter
from core.db import Ledger
from core.engine import Engine
from core.entities import (
    BrokerPosition,
    ExitReason,
    OrderStatus,
    Plan,
    SetupGrade,
    Signal,
    Side,
    Trade,
    TradeStatus,
)
from core.gates import GatesEngine
from core.params import DEFAULT_CONFIG_PATH, load_config

log = logging.getLogger("hermes")


class HermesDaemon:
    """یک پروسه. یک حلقه. یک حقیقت."""

    def __init__(self, config_path: Path | None = None, bridge_token: str = ""):
        # ── پیکربندی ────────────────────────────────────
        cfg_path = config_path or DEFAULT_CONFIG_PATH
        self.cfg = load_config(cfg_path, bridge_token)
        self.dry_run = self.cfg.dry_run

        # ─ـ زیرساخت ────────────────────────────────────
        self.mt5 = Mt5Adapter(
            self.cfg.bridge.url, self.cfg.bridge.token,
            self.cfg.bridge.timeout_s, dry_run=self.dry_run,
        )
        self.led = Ledger()
        self.eng = Engine()
        self.gates = GatesEngine(self.cfg.gates)
        self.signals = SignalsAdapter(
            Path(self.cfg.signals_log_path), Path(self.cfg.signals_state_path)
        )

        # تلگرام — از .env خوانده می‌شود
        self.notify = self._build_notify()

        # سیگنال‌های قدیمی را رد کن — فقط آینده پردازش می‌شود
        self.signals.skip_backlog()

        self._running = True
        self._last_entry_loop = 0.0

    # ───────────────────────────────────────────────────
    # چرخه حیات
    # ───────────────────────────────────────────────────

    def run(self) -> None:
        """حلقه اصلی — دو تایمر در یک پروسه."""
        log.info(
            "هرمس روشن شد | symbol=%s dry_run=%s entry=%ss exit=%ss",
            self.cfg.symbol, self.dry_run,
            self.cfg.loop.entry_interval_s, self.cfg.loop.exit_interval_s,
        )
        self.notify.status(
            f"هرمس روشن شد\nسymbol: {self.cfg.symbol}\n"
            f"حالت: {'DRY-RUN (آموزشی)' if self.dry_run else 'LIVE'}"
        )

        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGTERM, self._stop)

        while self._running:
            now = time.time()

            # تایمر ورود
            if now - self._last_entry_loop >= self.cfg.loop.entry_interval_s:
                try:
                    self._entry_loop()
                except BridgeError as e:
                    log.warning("entry loop: bridge خطا: %s", e)
                except Exception:
                    log.exception("entry loop خطای پیش‌بینی‌نشده")
                self._last_entry_loop = now

            # تایمر خروج — هر چرخه
            try:
                self._exit_loop()
            except BridgeError as e:
                log.warning("exit loop: bridge خطا: %s", e)
            except Exception:
                log.exception("exit loop خطای پیش‌بینی‌نشده")

            time.sleep(1)

        log.info("هرمس خاموش شد")
        self.notify.status("هرمس خاموش شد")

    def _stop(self, *_a) -> None:
        self._running = False

    # ───────────────────────────────────────────────────
    # حلقه ورود
    # ───────────────────────────────────────────────────

    def _entry_loop(self) -> None:
        """تحلیل بازار → ساخت plan → دروازه → ثبت سفارش."""
        # ۱) داده زنده از bridge
        candles = self.mt5.get_candles(
            self.cfg.symbol, self.cfg.analysis.timeframe, self.cfg.analysis.candle_count
        )
        tick = self.mt5.get_tick(self.cfg.symbol)
        account = self.mt5.get_account()
        positions = self.mt5.get_open_positions(self.cfg.symbol)

        # ۲) snapshot موجودی
        self.led.snapshot_equity(account)

        # ۳) سیگنال‌های جدید کانال
        new_signals = self.signals.read_new()
        for sig in new_signals:
            self.led.save_signal(sig)

        # ۴) اگر پوزیشن باز داریم → ورود جدید ممنوع (یک کلیک = یک معامله)
        if positions:
            return

        # ۵) تحلیل بازار
        view = self.eng.analyze(candles, tick)
        log.info(
            "بازار: %s strength=%.2f atr=%.2f spread=%.2f signals=%d",
            view.trend, view.trend_strength, view.atr, view.spread, len(new_signals),
        )

        # ۶) ساخت plan — اولویت با سیگنال کانال
        plan = None
        for sig in new_signals:
            plan = self.eng.plan_from_signal(sig, view, self.cfg.analysis.timeframe)
            if plan is not None:
                break

        if plan is None:
            return  # سیگنال جدیدی نیست → منتظر می‌مانیم

        # ۷) داده زنده برای دروازه
        trades_today = len(self.led.get_today_trades())
        today_pnl = self._today_pnl()

        # ۸) دروازه — fail-closed
        outcome = self.gates.evaluate(
            plan, account, positions, trades_today, today_pnl,
            atr=view.atr, spread=view.spread,
            learning_min_rr=float(self.led.get_param("min_rr", "0") or 0),
            learning_min_grade=self.led.get_param("min_grade", ""),
        )

        # ۹) ثبت در دفتر کل (شفافیت کامل)
        self.led.save_plan(plan, status="approved" if outcome.allowed else "denied")
        self.led.log_guard(
            outcome.verdict, outcome.reasons,
            plan.plan_id, plan.side.value, plan.symbol, outcome.volume,
        )

        if not outcome.allowed:
            self.notify.guard_denied(plan.side.value, plan.symbol, outcome.reasons)
            return

        # ۱۰) اجرا — تنها مسیر ثبت سفارش در کل سیستم
        order = self.mt5.place_order(
            order_id=f"hms-{plan.plan_id}",
            symbol=plan.symbol,
            side=plan.side,
            volume=outcome.volume,
            sl=plan.stop_loss,
            tp=plan.take_profit,
        )
        order.plan_id = plan.plan_id
        self.led.save_order(order)

        self.notify.trade_opened(
            plan.side.value, plan.symbol, outcome.volume,
            plan.entry_price, plan.stop_loss, plan.take_profit, self.dry_run,
        )
        log.info("سفارش ثبت شد: ticket=%s vol=%.2f", order.ticket, order.volume)

    # ───────────────────────────────────────────────────
    # حلقه خروج
    # ───────────────────────────────────────────────────

    def _exit_loop(self) -> None:
        """مدیریت پوزیشن‌های باز — breakeven / trailing / time-exit."""
        positions = self.mt5.get_open_positions(self.cfg.symbol)
        if not positions:
            return

        account = self.mt5.get_account()
        self.led.snapshot_equity(account)

        pos_cfg = self.cfg.position
        now = time.time()

        for pos in positions:
            # فقط پوزیشن‌های خودمان (magic comment hms-)
            if pos.comment and not pos.comment.startswith("hms"):
                continue

            decision = self._manage_position(pos, pos_cfg, now)
            if decision is not None:
                exit_reason, exit_price = decision
                self._close_position(pos, exit_reason, exit_price)

    def _manage_position(self, pos: BrokerPosition, pos_cfg, now: float):
        """تصمیم مدیریت یک پوزیشن → (reason, price) یا None."""
        rr = pos.rr_progress  # 0=استاپ، 1=TP

        # ۱) خروج زمانی
        age_h = (now - pos.open_time) / 3600.0
        if age_h >= pos_cfg.max_hold_hours:
            return ExitReason.TIME_EXIT, pos.current_price

        # ۲) breakeven — جابجایی SL به نقطه ورود
        if rr >= pos_cfg.breakeven_rr and pos.sl != pos.open_price:
            new_sl = pos.open_price
            if pos.is_buy and new_sl > pos.sl:
                self.mt5.modify_position(pos.ticket, new_sl, pos.tp)
                log.info("breakeven: ticket=%s sl=%.2f", pos.ticket, new_sl)
            elif not pos.is_buy and (pos.sl == 0 or new_sl < pos.sl):
                self.mt5.modify_position(pos.ticket, new_sl, pos.tp)
                log.info("breakeven: ticket=%s sl=%.2f", pos.ticket, new_sl)

        # ۳) trailing stop — SL را دنبال قیمت می‌کند
        if rr >= pos_cfg.trailing_start_rr and pos.sl > 0:
            new_sl = self._trail_sl(pos, pos_cfg)
            if new_sl is not None:
                self.mt5.modify_position(pos.ticket, new_sl, pos.tp)

        # ۴) خروج دستی اضطراری — پوزیشن در سود و نزدیک TP
        # (SL بروکر خودش فعال می‌شود — اینجا فقط time-exit مدیریت می‌کنیم)
        return None

    def _trail_sl(self, pos: BrokerPosition, pos_cfg) -> float | None:
        """محاسبه SL جدید برای trailing — فقط در جهت سود."""
        # فاصله ATR-مانند: نیمی از فاصله فعلی تا TP
        if pos.tp <= 0:
            return None
        dist = abs(pos.tp - pos.current_price) * 0.5
        if dist <= 0:
            return None
        if pos.is_buy:
            new_sl = pos.current_price - dist
            if new_sl > pos.sl:
                return new_sl
        else:
            new_sl = pos.current_price + dist
            if pos.sl == 0 or new_sl < pos.sl:
                return new_sl
        return None

    def _close_position(self, pos: BrokerPosition, reason: ExitReason, exit_price: float) -> None:
        """بستن پوزیشن و ثبت در دفتر کل."""
        ok = self.mt5.close_position(pos.ticket)
        if not ok:
            log.warning("close failed: ticket=%s", pos.ticket)
            return

        # رکورد ترید در دفتر کل
        pnl = pos.profit
        trade = Trade(
            trade_id=f"trade-{pos.ticket}",
            plan_id=pos.comment or "",
            ticket=pos.ticket,
            symbol=pos.symbol,
            side=pos.side,
            volume=pos.volume,
            entry_price=pos.open_price,
            exit_price=exit_price,
            sl=pos.sl,
            tp=pos.tp,
            pnl=pnl,
            exit_reason=reason,
            opened_at=pos.open_time,
            closed_at=time.time(),
            source="signal",
        )
        self.led.save_trade(trade)
        self.notify.trade_closed(pos.side.value, pos.symbol, pnl, reason.value)
        log.info("پوزیشن بسته شد: ticket=%s pnl=%.2f reason=%s", pos.ticket, pnl, reason.value)

    # ───────────────────────────────────────────────────
    # کمکی
    # ───────────────────────────────────────────────────

    def _today_pnl(self) -> float:
        """مجموع PnL معاملات بسته‌شده امروز."""
        return sum(t.pnl for t in self.led.get_today_trades())

    def _build_notify(self) -> NotifyAdapter:
        """خواندن توکن تلگرام از .env — اختیاری."""
        env_path = Path(__file__).resolve().parent.parent / ".env"
        token, chat = "", ""
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    chat = line.split("=", 1)[1].strip()
        return NotifyAdapter(token, chat, enabled=self.cfg.notify_enabled)

    def close(self) -> None:
        self.led.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # bridge token از .env
    env_path = Path(__file__).resolve().parent.parent / ".env"
    token = ""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("HERMES_BRIDGE_TOKEN="):
                token = line.split("=", 1)[1].strip()

    daemon = HermesDaemon(bridge_token=token)
    try:
        daemon.run()
    finally:
        daemon.close()


if __name__ == "__main__":
    main()
