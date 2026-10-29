""" entry/hermes — دیمن اصلی هرمس

یک پروسه. یک حلقه. یک حقیقت.

تایمر ورود (هر	config.loop.entry_interval_s):
	bridge → candles/tick/account/positions → signals → engine → gates → order

تایمر خروج (هر config.loop.exit_interval_s):
	bridge → positions زنده → breakeven/trailing/time-exit → close

هرگز از دیتابیس برای تصمیم نمی‌خواند. دیتابیس = دفتر کل فقط.
"""
from __future__ import annotations

import dataclasses
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
from adapters.watchdog import load_watchdog_from_env
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
        def _on_modify(ticket: int, new_sl: float, tp: float = 0.0, reason: str = "modify") -> None:
            try:
                # b233: حفظ TP فعلی در صورت عدم ارسال مقدار جدید تا در بروکر پاک نشود
                if tp <= 0.0 and ticket in self._tracked_positions:
                    tp = self._tracked_positions[ticket].tp
                self.mt5.modify_position(ticket, new_sl, tp)
                log.info("SL modified: ticket=%s sl=%.2f tp=%.2f reason=%s", ticket, new_sl, tp, reason)
                if ticket in self._tracked_positions:
                    p = self._tracked_positions[ticket]
                    if reason == "breakeven":
                        self.notify.breakeven_activated(ticket, p.symbol, p.side.value, new_sl)
                    elif reason == "trailing":
                        self.notify.trailing_ratcheted(ticket, p.symbol, new_sl, p.current_price)
            except BridgeError as e:
                log.warning("modify_position failed: ticket=%s error=%s", ticket, e)

        def _on_partial(ticket: int, percent: float) -> None:
            # جستجوی پوزیشن قبل از کاهش حجم جهت محاسبه دقیق سود پله‌ای
            cur_pos = None
            try:
                positions = self.mt5.get_open_positions(self.cfg.symbol)
                cur_pos = next((p for p in positions if p.ticket == ticket), None)
            except Exception as e:
                log.warning("خطا در خواندن پوزیشن قبل از partial: %s", e)

            try:
                ok = self.mt5.partial_close(ticket, percent)
            except BridgeError as e:
                log.warning("partial_close failed: ticket=%s error=%s", ticket, e)
                return

            if ok and cur_pos:
                closed_vol = round(cur_pos.volume * (percent / 100.0), 2)
                if closed_vol > 0:
                    exit_price = cur_pos.current_price
                    direction = 1.0 if cur_pos.is_buy else -1.0
                    gross = direction * (exit_price - cur_pos.open_price) * closed_vol * 100.0
                    comm = -7.0 * closed_vol
                    pnl = round(gross + comm, 2)

                    plan = self.led.get_plan_by_ticket(ticket)
                    if not plan and cur_pos.comment:
                        plan_id = cur_pos.comment.replace("hms-", "")
                        plan = self.led.get_plan(plan_id)

                    grade = plan.grade if plan else SetupGrade.C
                    source = plan.source if plan else ("analysis" if (cur_pos.comment or "").startswith("hms-auto") else ("smc" if ((cur_pos.comment or "").startswith("hms-smc") or (cur_pos.comment or "").startswith("hms-rtm")) else "signal"))

                    initial_sl = cur_pos.initial_sl if cur_pos.initial_sl > 0 else (self.exits._initial_sl.get(ticket) or (plan.stop_loss if plan else cur_pos.sl))
                    risk_denom = abs(cur_pos.open_price - initial_sl) if initial_sl > 0 else 0.0
                    r_mult = round(((exit_price - cur_pos.open_price) if cur_pos.is_buy else (cur_pos.open_price - exit_price)) / risk_denom, 2) if risk_denom > 0 else 0.0

                    trade = Trade(
                        trade_id=f"trade-{ticket}-part",
                        plan_id=plan.plan_id if plan else (cur_pos.comment or ""),
                        ticket=ticket,
                        symbol=cur_pos.symbol,
                        side=cur_pos.side,
                        volume=closed_vol,
                        entry_price=cur_pos.open_price,
                        exit_price=exit_price,
                        sl=cur_pos.sl,
                        tp=cur_pos.tp,
                        pnl=pnl,
                        exit_reason=ExitReason.PARTIAL_TP,
                        opened_at=cur_pos.open_time,
                        closed_at=time.time(),
                        grade=grade,
                        source=source,
                        r_multiple=r_mult,
                    )
                    self.led.save_trade(trade)
                    log.info("Partial close: ticket=%s percent=%.1f%% executed vol=%.2f pnl=%.2f",
                             ticket, percent, closed_vol, pnl)
                    self.notify.partial_closed(ticket, cur_pos.symbol, percent, closed_vol, pnl)
            elif ok:
                log.info("Partial close: ticket=%s percent=%.1f%% executed", ticket, percent)
                self.notify.status(f"🎯 بستن پله‌ای: {percent}% حجم پوزیشن #{ticket} سیو شد.")

        self.exits = ExitManager(self.cfg.position, on_modify=_on_modify, on_partial=_on_partial)
        self.learner = AdaptiveLearner()

        self.watchdog = load_watchdog_from_env()
        self._bridge_error_count = 0

        # سیگنال‌های قدیمی را رد کن — فقط آینده پردازش می‌شود
        self.signals.skip_backlog()

        self._running = True
        self._last_entry_loop = 0.0
        self._last_exit_loop = 0.0
        self._last_atr = 0.0  # آخرین ATR زنده — trailing تحلیلی
        self._tracked_positions: dict[int, BrokerPosition] = {}

    def _handle_bridge_error(self, e: Exception) -> None:
        self._bridge_error_count += 1
        log.warning("خطای ارتباط با بریج MT5 (#%d): %s", self._bridge_error_count, e)
        if self._bridge_error_count >= 3:
            log.error("۳ خطای متوالی در بریج MT5! فعال‌سازی نگهبان خودکار و احیا...")
            ok, msg = self.watchdog.revive()
            if ok:
                self._bridge_error_count = 0
                self.notify.status(f"🔄 <b>نگهبان هوشمند هرمس:</b> ارتباط با متاتریدر ۵ در سرور ویندوز احیا شد.\n{msg}")
            else:
                self.notify.status(f"🚨 <b>هشدار بحرانی:</b> تلاش برای احیای خودکار متاتریدر ۵ ناموفق بود:\n{msg}")

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
                    self._bridge_error_count = 0
                except BridgeError as e:
                    self._handle_bridge_error(e)
                except Exception:
                    log.exception("entry loop خطای پیش‌بینی‌نشده")
                self._last_entry_loop = now

            # تایمر خروج — هر config.loop.exit_interval_s
            if now - self._last_exit_loop >= self.cfg.loop.exit_interval_s:
                try:
                    self._exit_loop()
                    self._bridge_error_count = 0
                except BridgeError as e:
                    self._handle_bridge_error(e)
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

        # ۶) تحلیل چندبعدی بازار (Technical + SMC/ICT + News + DXY Intermarket)
        eur_candles = None
        jpy_candles = None
        try:
            eur_candles = self.mt5.get_candles("EURUSD", "M15", 30)
            jpy_candles = self.mt5.get_candles("USDJPY", "M15", 30)
        except Exception as e:
            log.warning("عدم دریافت داده‌های بین‌بازاری دلار: %s", e)

        view = self.eng.analyze(
            candles, tick, h1_candles=h1_candles,
            eur_candles=eur_candles, jpy_candles=jpy_candles
        )
        self._last_atr = view.atr  # برای trailing تحلیلی در exit loop
        log.info(
            "بازار: %s str=%.2f atr=%.2f spread=%.2f | SMC: %s (conf=%.2f zone=%s) | USD: %s | News: %s",
            view.trend, view.trend_strength, view.atr, view.spread,
            view.smc.bias if view.smc else "none",
            view.smc.confidence if view.smc else 0.0,
            view.smc.zone.value if view.smc else "none",
            view.usd_bias,
            f"BLACKOUT ({view.news_reason})" if view.news_blackout else "CLEAR",
        )

        # ۶) ساخت plan — اولویت با سیگنال کانال (اجرا یا واچ‌لیست)، سپس واچ‌لیست فعال، سپس تحلیل خودکار
        self.led.prune_expired_watchlist(time.time())
        plan = None

        for sig in new_signals:
            decision, plan_cand, wl_item = self.eng.evaluate_signal(
                sig, view, tick, self.cfg.analysis.timeframe
            )
            if decision == "EXECUTE" and plan_cand is not None:
                plan = plan_cand
                log.info("سیگنال کانال تایید شد و آماده اجراست: %s", sig.signal_id)
                break
            elif decision == "WATCHLIST" and wl_item is not None:
                self.led.add_to_watchlist(wl_item)
                log.info("سیگنال به واچ‌لیست رفت: %s — %s", sig.signal_id, wl_item.get("reason"))
                self.notify.status(f"⏳ سیگنال به واچ‌لیست رفت:\n{wl_item.get('reason')}")

        # اگر پلنی از سیگنال‌های جدید نیامده، واچ‌لیست‌های گذشته را چک کن
        wl_executed_item_id = None
        if plan is None:
            active_wl = self.led.get_active_watchlist(self.cfg.symbol)
            for item in active_wl:
                side = Side(item["side"])
                # چک کردن آیا قیمت به ناحیه پولبک رسیده است
                reached = (side == Side.BUY and tick.ask <= item["trigger_price"] + 0.50 and tick.ask >= item["sl"]) or \
                          (side == Side.SELL and tick.bid >= item["trigger_price"] - 0.50 and tick.bid <= item["sl"])

                if reached and not view.news_blackout:
                    rr = round(abs(item["tp"] - tick.mid) / max(0.1, abs(tick.mid - item["sl"])), 2)
                    plan = Plan(
                        plan_id=f"wl-exec-{item['signal_id']}",
                        symbol=item["symbol"],
                        side=side,
                        entry_price=tick.mid,
                        stop_loss=item["sl"],
                        take_profit=item["tp"],
                        volume=0.0,
                        grade=SetupGrade.A,
                        source="watchlist_pullback",
                        timeframe=self.cfg.analysis.timeframe,
                        rr=rr,
                        confidence=0.85,
                        reasoning=f"واچ‌لیست پولبک فعال شد: {item['reason']}",
                    )
                    wl_executed_item_id = item["item_id"]
                    log.info("سیگنال واچ‌لیست پولبک زد و تبدیل به پلن شد: %s", plan.plan_id)
                    break

                # چک کردن آیا استاپ لاس یا تارگت قبل از پولبک لمس شده و باطل شده
                target_hit = (side == Side.BUY and tick.ask >= item["tp"]) or \
                             (side == Side.SELL and tick.bid <= item["tp"])
                sl_hit = (side == Side.BUY and tick.bid <= item["sl"]) or \
                         (side == Side.SELL and tick.ask >= item["sl"])
                if target_hit:
                    self.led.update_watchlist_status(item["item_id"], "target_reached")
                    log.info("سیگنال واچ‌لیست به تارگت رسید و بسته شد: %s", item["item_id"])
                elif sl_hit:
                    self.led.update_watchlist_status(item["item_id"], "invalidated")
                    log.info("سیگنال واچ‌لیست ابطال شد (لمس SL): %s", item["item_id"])

        if plan is None and not positions and auto_allowed:
            # ۱) اولویت نخست: ستاپ سازمانی هوشمند SMC/ICT (گرید A+)
            plan = self.eng.plan_from_smc(candles, view, h1_candles, self.cfg.analysis.timeframe)
            if plan is not None:
                log.info("تحلیل خودکار: ستاپ سازمانی SMC %s (%s) تشخیص داده شد", plan.side.value, plan.reasoning)

            # ۲) اولویت دوم: ستاپ تاییدشده روند EMA (گرید B با تاییدیه H1)
            if plan is None:
                plan = self.eng.plan_from_analysis(candles, view, self.cfg.analysis.timeframe, h1_candles=h1_candles)
                if plan is not None:
                    log.info("تحلیل خودکار: ستاپ روند-EMA %s تشخیص داده شد", plan.side.value)

        if plan is None:
            return  # ستاپی وجود ندارد → منتظر می‌مانیم

        # ۷) داده زنده برای دروازه
        trades_today = self._today_trades_count()
        today_pnl = self._today_pnl()

        # ۸) دروازه — fail-closed (قرارداد b221)
        # هر دو مسیر ورود (سیگنال کانال/واچ‌لیست و تحلیل خودکار) منحصراً از این گیت زنده ارزیابی می‌شوند.
        # بریج خاموش یا اطلاعات ناقص به هیچ وجه چراغ سبز دریافت نمی‌کند (رد fail-closed).
        last_loss = self.led.get_last_loss_time()
        outcome = self.gates.evaluate(
            plan, account, positions, trades_today, today_pnl,
            atr=view.atr, spread=view.spread,
            learning_min_rr=float(self.led.get_param("min_rr", "0") or 0),
            learning_min_grade=self.led.get_param("min_grade", ""),
            last_loss_ts=last_loss,
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
        if wl_executed_item_id:
            self.led.update_watchlist_status(wl_executed_item_id, "executed")
        if order.ticket > 0 and plan.stop_loss > 0:
            self.exits.register_initial_sl(order.ticket, plan.stop_loss)

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
        if positions is None:
            log.warning("exit loop: positions is None (bridge unreadable) — fail-closed, skipping exit pass")
            return

        # ۱) تطبیق معاملات بسته‌شده در سمت بروکر (Broker Reconciliation)
        # اگر پوزیشنی در چرخه قبل باز بوده ولی اکنون بسته شده، اطلاعات خروج را از هیستوری دیل‌ها استخراج و در ژورنال ثبت می‌کنیم.
        current_map = {p.ticket: p for p in (positions or []) if not p.comment or p.comment.startswith("hms")}
        closed_tickets = [t for t in self._tracked_positions if t not in current_map]
        if closed_tickets:
            self._reconcile_broker_closed_positions(closed_tickets)
        self._tracked_positions = current_map

        if not positions:
            return

        account = self.mt5.get_account()
        self.led.snapshot_equity(account)

        now = time.time()

        # ATR زنده برای مسیر trailing تحلیلی (پلن‌های بدون TP)
        # وقتی پوزیشن باز است entry loop رد می‌شود → اینجا تازه‌سازی می‌کنیم
        tick = None
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
            # همگام‌سازی قیمت لحظه‌ای خروج با بهترین تیک بازار (Bid برای خرید، Ask برای فروش)
            if tick and tick.bid > 0:
                real_cur = tick.bid if pos.is_buy else tick.ask
                pos = dataclasses.replace(pos, current_price=real_cur)

            # فقط پوزیشن‌های خودمان (magic comment hms-)
            if pos.comment and not pos.comment.startswith("hms"):
                continue

            # بازیابی استاپ‌لاس اولیه از دیتابیس در صورت لزوم (حفظ سلامت محاسبات پس از ریستارت)
            if pos.ticket not in self.exits._initial_sl:
                plan = self.led.get_plan_by_ticket(pos.ticket)
                if not plan and pos.comment:
                    plan_id = pos.comment.replace("hms-", "")
                    plan = self.led.get_plan(plan_id)
                if plan and plan.stop_loss > 0:
                    self.exits.register_initial_sl(pos.ticket, plan.stop_loss)

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
        try:
            ok = self.mt5.close_position(pos.ticket)
        except BridgeError as e:
            log.warning("close failed: ticket=%s error=%s", pos.ticket, e)
            return
        if not ok:
            log.warning("close failed: ticket=%s", pos.ticket)
            return

        # در صورت دسترسی در حالت زنده، استخراج اطلاعات دقیق دیل خروج از بروکر
        deal_exit = None
        if not self.dry_run:
            try:
                deals = self.mt5.get_history_deals(days=1, symbol=self.cfg.symbol)
                for d in deals:
                    if d.get("entry") == 1:
                        pos_id = d.get("position_id") or d.get("ticket") or d.get("order")
                        if pos_id and int(pos_id) == pos.ticket:
                            deal_exit = d
                            break
            except Exception as e:
                log.warning("عدم دسترسی به تاریخچه دیل‌های بروکر در close_position: %s", e)

        if deal_exit:
            exit_price = float(deal_exit.get("price") or exit_price)
            profit = float(deal_exit.get("profit", 0.0))
            swap = float(deal_exit.get("swap", 0.0))
            comm = float(deal_exit.get("commission", 0.0))
            pnl = round(profit + swap + comm, 2)
        elif exit_price > 0:
            if pos.is_buy:
                gross = (exit_price - pos.open_price) * pos.volume * 100.0
            else:
                gross = (pos.open_price - exit_price) * pos.volume * 100.0
            # کسر کمیسیون استاندارد و سواپ جهت احتساب سود خالص
            comm = pos.commission if pos.commission != 0.0 else -7.0 * pos.volume
            pnl = round(gross + comm + pos.swap, 2)
        else:
            pnl = pos.net_profit

        plan = self.led.get_plan_by_ticket(pos.ticket)
        if not plan and pos.comment:
            plan_id = pos.comment.replace("hms-", "")
            plan = self.led.get_plan(plan_id)

        grade = plan.grade if plan else SetupGrade.C
        source = plan.source if plan else ("analysis" if (pos.comment or "").startswith("hms-auto") else ("smc" if ((pos.comment or "").startswith("hms-smc") or (pos.comment or "").startswith("hms-rtm")) else "signal"))

        initial_sl = pos.initial_sl if pos.initial_sl > 0 else (self.exits._initial_sl.get(pos.ticket) or (plan.stop_loss if plan else pos.sl))
        risk_denom = abs(pos.open_price - initial_sl) if initial_sl > 0 else 0.0
        if risk_denom > 0:
            r_mult = round((exit_price - pos.open_price) / risk_denom if pos.is_buy else (pos.open_price - exit_price) / risk_denom, 2)
        else:
            r_mult = 0.0

        trade = Trade(
            trade_id=f"trade-{pos.ticket}",
            plan_id=plan.plan_id if plan else (pos.comment or ""),
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
            grade=grade,
            source=source,
            r_multiple=r_mult,
        )
        self.led.save_trade(trade)
        self.notify.trade_closed(pos.side.value, pos.symbol, pnl, reason.value)
        self.exits.cleanup_ticket(pos.ticket)
        self._tracked_positions.pop(pos.ticket, None)
        log.info("پوزیشن بسته شد: ticket=%s pnl=%.2f r_mult=%.2f reason=%s", pos.ticket, pnl, r_mult, reason.value)

    def _reconcile_broker_closed_positions(self, closed_tickets: list[int]) -> None:
        """تطبیق و ثبت معاملات بسته‌شده توسط بروکر (SL/TP) در ژورنال، اعلان و پاکسازی حافظه."""
        deals = []
        if not self.dry_run:
            try:
                deals = self.mt5.get_history_deals(days=1, symbol=self.cfg.symbol)
            except Exception as e:
                log.warning("عدم دسترسی به تاریخچه دیل‌های بروکر جهت تطبیق خروج: %s", e)

        deal_by_pos: dict[int, dict] = {}
        for d in deals:
            if d.get("entry") == 1:
                pos_id = d.get("position_id") or d.get("ticket") or d.get("order")
                if pos_id:
                    deal_by_pos[int(pos_id)] = d

        for ticket in closed_tickets:
            old_pos = self._tracked_positions.get(ticket)
            if not old_pos:
                continue

            # چک کردن اینکه آیا این معامله قبلاً با _close_position ثبت شده یا خیر
            try:
                row = self.led._con.execute(
                    "SELECT 1 FROM trades WHERE ticket = ? AND exit_reason != ?",
                    (ticket, ExitReason.PARTIAL_TP.value)
                ).fetchone()
                if row:
                    self.exits.cleanup_ticket(ticket)
                    continue
            except Exception:
                pass

            d = deal_by_pos.get(ticket)
            if d:
                exit_price = float(d.get("price") or old_pos.current_price)
                profit = float(d.get("profit", 0.0))
                swap = float(d.get("swap", 0.0))
                comm = float(d.get("commission", 0.0))
                pnl = round(profit + swap + comm, 2)
                comment = str(d.get("comment", "")).lower()
                if "[tp]" in comment or (old_pos.tp > 0 and ((old_pos.is_buy and exit_price >= old_pos.tp - 0.25) or (not old_pos.is_buy and exit_price <= old_pos.tp + 0.25))):
                    reason = ExitReason.TAKE_PROFIT
                elif "[sl]" in comment or (old_pos.sl > 0 and ((old_pos.is_buy and exit_price <= old_pos.sl + 0.25) or (not old_pos.is_buy and exit_price >= old_pos.sl - 0.25))):
                    if pnl > 0.0:
                        reason = ExitReason.TRAILING_STOP
                    elif pnl == 0.0 or abs(exit_price - old_pos.open_price) <= 0.20:
                        reason = ExitReason.BREAKEVEN
                    else:
                        reason = ExitReason.STOP_LOSS
                else:
                    reason = ExitReason.MANUAL
            else:
                exit_price = old_pos.current_price
                pnl = old_pos.net_profit
                reason = ExitReason.MANUAL

            plan = self.led.get_plan_by_ticket(ticket)
            if not plan and old_pos.comment:
                plan_id = old_pos.comment.replace("hms-", "")
                plan = self.led.get_plan(plan_id)

            grade = plan.grade if plan else SetupGrade.C
            source = plan.source if plan else ("analysis" if (old_pos.comment or "").startswith("hms-auto") else ("smc" if ((old_pos.comment or "").startswith("hms-smc") or (old_pos.comment or "").startswith("hms-rtm")) else "signal"))

            # R-Multiple بر مبنای استاپ اولیه
            init_sl = self.exits._initial_sl.get(ticket, old_pos.initial_sl if old_pos.initial_sl > 0 else (plan.stop_loss if plan else old_pos.sl))
            if init_sl > 0:
                if old_pos.is_buy:
                    risk = old_pos.open_price - init_sl
                    r_mult = round((exit_price - old_pos.open_price) / risk, 3) if risk > 0 else old_pos.r_multiple
                else:
                    risk = init_sl - old_pos.open_price
                    r_mult = round((old_pos.open_price - exit_price) / risk, 3) if risk > 0 else old_pos.r_multiple
            else:
                r_mult = old_pos.r_multiple

            trade = Trade(
                trade_id=f"trade-{ticket}",
                plan_id=plan.plan_id if plan else (old_pos.comment or ""),
                ticket=ticket,
                symbol=old_pos.symbol,
                side=old_pos.side,
                volume=old_pos.volume,
                entry_price=old_pos.open_price,
                exit_price=exit_price,
                sl=old_pos.sl,
                tp=old_pos.tp,
                pnl=pnl,
                exit_reason=reason,
                opened_at=old_pos.open_time,
                closed_at=time.time(),
                grade=grade,
                source=source,
                r_multiple=r_mult,
            )
            self.led.save_trade(trade)
            self.notify.trade_closed(old_pos.side.value, old_pos.symbol, pnl, reason.value)
            self.exits.cleanup_ticket(ticket)
            log.info("پوزیشن بسته شده توسط بروکر تطبیق و در ژورنال ثبت شد: ticket=%s pnl=%.2f reason=%s", ticket, pnl, reason.value)

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
        local_trades = self.led.get_today_trades()
        distinct_local_tickets = {t.ticket for t in local_trades}
        local_count = len(distinct_local_tickets)
        if not self.dry_run:
            try:
                deals = self.mt5.get_history_deals(days=1, symbol=self.cfg.symbol)
                today_start = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).timestamp()
                exit_deals = [d for d in deals if d.get("time", 0) >= today_start and d.get("entry") == 1]
                broker_tickets = {d.get("position_id") or d.get("ticket") for d in exit_deals if (d.get("position_id") or d.get("ticket"))}
                return max(local_count, len(broker_tickets))
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
