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
from core.exits import ExitManager
from core.gates import GatesEngine
from core.learning import AdaptiveLearner
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
            sim_state_path=str(Path(__file__).resolve().parent.parent / "data" / "sim_book.json"),
        )
        self.led = Ledger()
        self.eng = Engine()
        self.gates = GatesEngine(self.cfg.gates)
        self.signals = SignalsAdapter(
            Path(self.cfg.signals_log_path), Path(self.cfg.signals_state_path)
        )

        # تلگرام — از .env خوانده می‌شود
        self.notify = self._build_notify()

        # منطق خروج مشترک (دیمن زنده + بک‌تستر یک کد اجرا می‌کنند)
        def _on_modify(ticket: int, new_sl: float) -> None:
            self.mt5.modify_position(ticket, new_sl, 0.0)
            log.info("SL modified: ticket=%s sl=%.2f", ticket, new_sl)

        def _on_partial(ticket: int, percent: float) -> None:
            ok = self.mt5.partial_close(ticket, percent)
            if ok:
                log.info("Partial close: ticket=%s percent=%.1f%% executed", ticket, percent)
                self.notify.status(f"🎯 بستن پله‌ای: {percent}% حجم پوزیشن #{ticket} سیو سود شد.")

        self.exits = ExitManager(self.cfg.position, on_modify=_on_modify, on_partial=_on_partial)
        self.learner = AdaptiveLearner()

        # سیگنال‌های قدیمی را رد کن — فقط آینده پردازش می‌شود
        self.signals.skip_backlog()

        self._running = True
        self._last_entry_loop = 0.0
        self._last_exit_loop = 0.0
        self._last_atr = 0.0  # آخرین ATR زنده — trailing تحلیلی

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
        mode_str = "DRY-RUN (شبیه‌ساز)" if self.dry_run else "LIVE (واقعی)"
        self.notify.status(
            f"🟢 *هرمس فعال شد*\n"
            f"• نماد: `{self.cfg.symbol}`\n"
            f"• وضعیت: `{mode_str}`"
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

            # تایمر خروج — هر config.loop.exit_interval_s
            if now - self._last_exit_loop >= self.cfg.loop.exit_interval_s:
                try:
                    self._exit_loop()
                except BridgeError as e:
                    log.warning("exit loop: bridge خطا: %s", e)
                except Exception:
                    log.exception("exit loop خطای پیش‌بینی‌نشده")
                self._last_exit_loop = now

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
        h1_candles = []
        if "H1" in self.cfg.analysis.higher_timeframes:
            try:
                h1_candles = self.mt5.get_candles(self.cfg.symbol, "H1", 50)
            except Exception as e:
                log.warning("H1 candles fetch failed: %s", e)

        tick = self.mt5.get_tick(self.cfg.symbol)
        account = self.mt5.get_account()
        positions = self.mt5.get_open_positions(self.cfg.symbol)

        # ۲) snapshot موجودی + یادگیری تطبیقی
        self.led.snapshot_equity(account)
        self.learner.adapt(self.led)

        # ۳) سیگنال‌های جدید کانال
        new_signals = self.signals.read_new()
        for sig in new_signals:
            self.led.save_signal(sig)

        # ۴) اگر پوزیشن باز داریم → ورود جدید ممنوع (یک کلیک = یک معامله)
        if positions:
            return

        # ۵) سشن معاملاتی برای تحلیل خودکار — فقط در session_hours (UTC).
        #    خارج از سشن نقدینگی کم است و اسپرد/اسلیپیج بالا.
        #    بک‌تست: بازه ۰۰-۰۴ UTC با EV منفی. fail-closed.
        #    سیگنال‌های کانال معاف هستند — صادرکننده زمانشان را تعیین کرده.
        h_utc = time.gmtime().tm_hour
        h0, h1 = self.cfg.analysis.session_hours
        auto_allowed = h0 <= h_utc < h1
        if not auto_allowed:
            log.info(
                "سشن بسته: %02d UTC خارج بازه [%d,%d) — تحلیل خودکار ممنوع",
                h_utc, h0, h1,
            )

        # ۶) تحلیل چندبعدی بازار (Technical + SMC/ICT + News)
        view = self.eng.analyze(candles, tick, h1_candles=h1_candles)
        self._last_atr = view.atr  # برای trailing تحلیلی در exit loop
        log.info(
            "بازار: %s str=%.2f atr=%.2f spread=%.2f | SMC: %s (conf=%.2f zone=%s) | News: %s",
            view.trend, view.trend_strength, view.atr, view.spread,
            view.smc.bias if view.smc else "none",
            view.smc.confidence if view.smc else 0.0,
            view.smc.zone.value if view.smc else "none",
            f"BLACKOUT ({view.news_reason})" if view.news_blackout else "CLEAR",
        )

        # ۶) ساخت plan — اولویت با سیگنال کانال، سپس تحلیل خودکار
        plan = None
        for sig in new_signals:
            plan = self.eng.plan_from_signal(sig, view, self.cfg.analysis.timeframe)
            if plan is not None:
                break

        if plan is None and not positions and auto_allowed:
            # تحلیل خودکار: ستاپ روند-EMA (تاییدشده با بک‌تست)
            plan = self.eng.plan_from_analysis(candles, view, self.cfg.analysis.timeframe)
            if plan is not None:
                log.info("تحلیل خودکار: ستاپ روند-EMA %s تشخیص داده شد", plan.side.value)

        if plan is None:
            return  # ستاپی وجود ندارد → منتظر می‌مانیم

        # ۷) داده زنده برای دروازه
        trades_today = self._today_trades_count()
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

        now = time.time()

        # ATR زنده برای مسیر trailing تحلیلی (پلن‌های بدون TP)
        # وقتی پوزیشن باز است entry loop رد می‌شود → اینجا تازه‌سازی می‌کنیم
        try:
            candles = self.mt5.get_candles(
                self.cfg.symbol, self.cfg.analysis.timeframe, self.cfg.analysis.candle_count
            )
            tick = self.mt5.get_tick(self.cfg.symbol)
            view_now = self.eng.analyze(candles, tick)
            self._last_atr = view_now.atr
        except Exception:
            log.warning("exit loop: ATR تازه‌سازی نشد — از مقدار قبلی استفاده می‌شود")

        for pos in positions:
            # فقط پوزیشن‌های خودمان (magic comment hms-)
            if pos.comment and not pos.comment.startswith("hms"):
                continue

            # b240: در dry_run بروکری وجود ندارد — خودمان SL/TP را اجرا می‌کنیم
            # (در حالت LIVE بروکر این کار را می‌کند)
            if self.dry_run and pos.sl > 0:
                hit = None
                if pos.is_buy and pos.current_price <= pos.sl:
                    hit = pos.sl
                elif not pos.is_buy and pos.current_price >= pos.sl:
                    hit = pos.sl
                if hit is not None:
                    self._close_position(pos, ExitReason.STOP_LOSS, hit)
                    continue
            if self.dry_run and pos.tp > 0:
                hit = None
                if pos.is_buy and pos.current_price >= pos.tp:
                    hit = pos.tp
                elif not pos.is_buy and pos.current_price <= pos.tp:
                    hit = pos.tp
                if hit is not None:
                    self._close_position(pos, ExitReason.TAKE_PROFIT, hit)
                    continue

            # ATR زنده برای مسیر trailing تحلیلی (پلن‌های بدون TP)
            # منطق خروج مشترک — همان کدی که بک‌تستر اجرا می‌کند
            decision = self.exits.manage(pos, now, atr=self._last_atr)
            if decision is not None:
                exit_reason, exit_price = decision
                self._close_position(pos, exit_reason, exit_price)

    def _close_position(self, pos: BrokerPosition, reason: ExitReason, exit_price: float) -> None:
        """بستن پوزیشن و ثبت در دفتر کل."""
        ok = self.mt5.close_position(pos.ticket)
        if not ok:
            log.warning("close failed: ticket=%s", pos.ticket)
            return

        # رکورد ترید در دفتر کل
        # b240: در dry_run سود را از قیمت خروج واقعی محاسبه می‌کنیم
        if self.dry_run and exit_price > 0:
            if pos.is_buy:
                gross = (exit_price - pos.open_price) * pos.volume * 100.0
            else:
                gross = (pos.open_price - exit_price) * pos.volume * 100.0
            # b210: کسر کمیسیون استاندارد و سواپ جهت احتساب سود خالص
            comm = pos.commission if pos.commission != 0.0 else -7.0 * pos.volume
            pnl = round(gross + comm + pos.swap, 2)
        else:
            pnl = pos.net_profit
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
            source="analysis" if (pos.comment or "").startswith("hms-auto") else "signal",
        )
        self.led.save_trade(trade)
        self.notify.trade_closed(pos.side.value, pos.symbol, pnl, reason.value)
        log.info("پوزیشن بسته شد: ticket=%s pnl=%.2f reason=%s", pos.ticket, pnl, reason.value)

    # ───────────────────────────────────────────────────
    # کمکی
    # ───────────────────────────────────────────────────

    def _today_pnl(self) -> float:
        """مجموع PnL خالص معاملات بسته‌شده امروز (b210: شامل سود، کمیسیون و سواپ)."""
        if not self.dry_run:
            try:
                deals = self.mt5.get_history_deals(days=1, symbol=self.cfg.symbol)
                today_start = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).timestamp()
                net_pnl = 0.0
                has_deals = False
                for d in deals:
                    if d.get("time", 0) >= today_start:
                        net_pnl += float(d.get("profit", 0.0)) + float(d.get("swap", 0.0)) + float(d.get("commission", 0.0))
                        has_deals = True
                if has_deals:
                    return round(net_pnl, 2)
            except Exception as e:
                log.warning("عدم دسترسی به تاریخچه معاملات بروکر برای daily_pnl: %s", e)

        return round(sum(t.pnl for t in self.led.get_today_trades()), 2)

    def _today_trades_count(self) -> int:
        """تعداد معاملات بسته‌شده امروز جهت ارزیابی گیت max_daily_trades."""
        local_count = len(self.led.get_today_trades())
        if not self.dry_run:
            try:
                deals = self.mt5.get_history_deals(days=1, symbol=self.cfg.symbol)
                today_start = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).timestamp()
                exit_deals = [d for d in deals if d.get("time", 0) >= today_start and d.get("entry") == 1]
                return max(local_count, len(exit_deals))
            except Exception as e:
                log.warning("عدم دسترسی به تاریخچه معاملات بروکر برای شمارش: %s", e)
        return local_count

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
        self.mt5.close()


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
