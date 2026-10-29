""" adapters/mt5 — Enterprise MT5 HTTP Client & Bridge Adapter

ارتباط با سرور ویندوز و نرم‌افزار MetaTrader 5:
- استفاده از requests.Session و Connection Pooling جهت کاهش تاخیر (Latency)
- استراتژی Retry خودکار روی درخواست‌های خواندنی (Idempotent GET) در زمان نوسان شبکه
- مدیریت دقیق کدهای خطای متاتریدر (Retcodes) و ترجمه به پیام‌های تجاری معنادار
- پشتیبانی کامل از ثبت سفارش، اصلاح، بستن کامل، بستن پله‌ای (Partial Close)، و تاریخچه معاملات (Deals)
- پشتیبانی کامل از حالت شبیه‌سازی پایدار (dry_run: true) بر مبنای دیسک (sim_book.json)
"""
from __future__ import annotations

import dataclasses
import json
import logging
import time
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.entities import (
    AccountState,
    BrokerPosition,
    Candle,
    Order,
    OrderStatus,
    Side,
    Tick,
)

log = logging.getLogger(__name__)


class BridgeError(Exception):
    """خطای ارتباط با bridge — fail-closed."""
    def __init__(self, message: str, retcode: int | None = None):
        super().__init__(message)
        self.retcode = retcode


# نگاشت کدهای خطای رایج متاتریدر ۵ به مفاهیم تجاری
RETCODE_DESCRIPTIONS: dict[int, str] = {
    10004: "REQUOTE — تغییر مظنه قیمت",
    10006: "REJECTED — درخواست توسط بروکر رد شد",
    10007: "CANCELLED — سفارش لغو شد",
    10008: "PLACED — سفارش ثبت شد",
    10009: "DONE — معامله با موفقیت انجام شد",
    10010: "DONE_PARTIAL — سفارش به صورت جزئی انجام شد",
    10011: "ERROR — خطای عمومی پردازش سفارش",
    10012: "TIMEOUT — مهلت زمانی پردازش سپری شد",
    10013: "INVALID_REQUEST — ساختار درخواست نامعتبر است",
    10014: "INVALID_VOLUME — حجم سفارش نامعتبر است",
    10015: "INVALID_PRICE — قیمت سفارش نامعتبر است",
    10016: "INVALID_STOPS — استاپ‌لاس یا تیک‌پرافیت نامعتبر است",
    10017: "TRADE_DISABLED — معاملات برای این حساب یا نماد غیرفعال است",
    10018: "MARKET_CLOSED — بازار در حال حاضر بسته است",
    10019: "NO_MONEY — موجودی مارجین برای باز کردن این حجم کافی نیست",
    10020: "PRICE_CHANGED — قیمت تغییر کرده است",
    10021: "PRICE_OFF — مظنه قیمتی از سمت بروکر وجود ندارد",
    10022: "INVALID_EXPIRATION — تاریخ انقضای سفارش نامعتبر است",
    10023: "ORDER_CHANGED — وضعیت سفارش تغییر کرده است",
    10024: "TOO_MANY_REQUESTS — تعداد درخواست‌ها بیش از حد مجاز است",
    10025: "NO_CHANGES — هیچ تغییری در سطوح استاپ یا قیمت داده نشد",
    10026: "AUTOTRADING_DISABLED_SERVER — اتوتریدینگ در سرور بروکر غیرفعال است",
    10027: "AUTOTRADING_DISABLED_CLIENT — دکمه اتوتریدینگ در متاتریدر خاموش است",
    10028: "CONNECTION_LOST — اتصال ترمینال به سرور بروکر قطع است",
}


class Mt5Adapter:
    """کلاینت HTTP پرسرعت و پایدار برای ارتباط با پل متاتریدر ۵ در ویندوز."""

    def __init__(
        self,
        url: str,
        token: str,
        timeout_s: int = 10,
        dry_run: bool = True,
        sim_state_path: str | None = None,
    ):
        self._url = url.rstrip("/")
        self._token = token
        self._timeout = timeout_s
        self._dry_run = dry_run

        # پیکربندی Session با Connection Pooling و Keep-Alive
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "User-Agent": "Hermes-Trading-Core/3.0",
            "Content-Type": "application/json",
        })
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=Retry(total=0))
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        # دفتر پوزیشن‌های شبیه‌سازی‌شده در dry_run
        self._sim_state_path = Path(sim_state_path) if sim_state_path else None
        self._sim_ticket = 0
        self._sim_book: dict[int, BrokerPosition] = {}
        if self._dry_run:
            self._sim_load()

    # ── مدیریت دفتر شبیه‌سازی (Dry Run) ───────────────────

    def _sim_load(self) -> None:
        """بارگذاری دفتر شبیه‌سازی از دیسک — بازیابی پوزیشن‌ها پس از ری‌استارت."""
        if self._sim_state_path is None or not self._sim_state_path.exists():
            return
        try:
            doc = json.loads(self._sim_state_path.read_text(encoding="utf-8"))
            self._sim_ticket = int(doc.get("next_ticket", 1))
            for row in doc.get("positions", []):
                p = BrokerPosition(
                    ticket=int(row["ticket"]),
                    symbol=str(row["symbol"]),
                    side=Side(row["side"]),
                    volume=float(row["volume"]),
                    open_price=float(row["open_price"]),
                    current_price=float(row.get("current_price", row["open_price"])),
                    sl=float(row.get("sl", 0.0)),
                    tp=float(row.get("tp", 0.0)),
                    profit=float(row.get("profit", 0.0)),
                    swap=float(row.get("swap", 0.0)),
                    open_time=int(row["open_time"]),
                    comment=str(row.get("comment", "")),
                )
                self._sim_book[p.ticket] = p
            if self._sim_book:
                log.info("sim book: %d position(s) loaded from disk", len(self._sim_book))
        except Exception as e:
            log.warning("sim book load failed: %s — starting empty", e)
            self._sim_book = {}
            self._sim_ticket = 0

    def _sim_save(self) -> None:
        """ذخیره اتمیک دفتر شبیه‌سازی روی دیسک."""
        if self._sim_state_path is None:
            return
        try:
            doc = {
                "next_ticket": self._sim_ticket + 1,
                "positions": [dataclasses.asdict(p) for p in self._sim_book.values()],
            }
            tmp = self._sim_state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._sim_state_path)
        except Exception as e:
            log.warning("sim book save failed: %s", e)

    # ── شبکه و درخواست‌ها ────────────────────────────────

    def _get(self, path: str, params: Optional[dict] = None, retries: int = 2) -> dict:
        """ارسال درخواست GET همراه با Retry هوشمند برای داده‌های خواندنی."""
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = self._session.get(
                    f"{self._url}{path}",
                    params=params,
                    timeout=self._timeout,
                )
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (401, 403):
                    raise BridgeError(f"GET {path} Auth failed: HTTP {r.status_code}")
                raise BridgeError(f"GET {path} HTTP error: {r.status_code}")
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < retries:
                    sleep_s = 0.2 * (attempt + 1)
                    log.warning("GET %s connection blip (%s), retrying in %.1fs...", path, e, sleep_s)
                    time.sleep(sleep_s)
            except Exception as e:
                raise BridgeError(f"GET {path}: {e}") from e

        raise BridgeError(f"GET {path} failed after {retries+1} attempts: {last_exc}") from last_exc

    def _post(self, path: str, body: dict) -> dict:
        """ارسال درخواست POST به بریج بدون بازتکرار کورکورانه (Fail-Closed)."""
        try:
            r = self._session.post(
                f"{self._url}{path}",
                json=body,
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            raise BridgeError(f"POST {path}: {e}") from e

        if r.status_code == 200:
            return r.json()

        try:
            data = r.json()
            retcode_val = data.get("retcode")
            retcode = int(retcode_val) if retcode_val is not None else None
            desc = RETCODE_DESCRIPTIONS.get(retcode, "") if retcode is not None else ""
            msg = f"POST {path} HTTP {r.status_code}: retcode={retcode} ({desc}) err={data.get('error')}"
            raise BridgeError(msg, retcode=retcode)
        except Exception:
            raise BridgeError(f"POST {path} HTTP {r.status_code}")

    @staticmethod
    def _requireOk(doc: dict, path: str) -> None:
        if not doc.get("ok", False):
            retcode_val = doc.get("retcode")
            retcode = int(retcode_val) if retcode_val is not None else None
            desc = RETCODE_DESCRIPTIONS.get(retcode, "") if retcode is not None else ""
            err = doc.get("error")
            msg = f"{path} bridge ok=false: retcode={retcode} ({desc}) error={err}"
            raise BridgeError(msg, retcode=retcode)

    # ── حساب و بازار ────────────────────────────────────

    def get_account(self) -> AccountState:
        """استعلام وضعیت لحظه‌ای حساب از بروکر."""
        d = self._get("/api/account")
        self._requireOk(d, "/api/account")
        return AccountState(
            balance=float(d["balance"]),
            equity=float(d["equity"]),
            margin=float(d.get("margin", d.get("margin_free", 0.0)) or 0.0),
            margin_free=float(d.get("margin_free", d["balance"])),
            currency=str(d.get("currency", "USD")),
            login=int(d.get("login", 0)),
        )

    def get_tick(self, symbol: str) -> Tick:
        """استعلام تیک زنده (Bid/Ask) برای نماد معاملاتی."""
        d = self._get(f"/api/tick/{symbol}")
        self._requireOk(d, f"/api/tick/{symbol}")
        return Tick(
            symbol=d.get("symbol", symbol),
            bid=float(d["bid"]),
            ask=float(d["ask"]),
            time=int(d.get("time", time.time())),
        )

    def get_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        """دریافت کندل‌های تاریخی OHLCV."""
        d = self._get(f"/api/ohlc/{symbol}", params={"timeframe": timeframe, "count": count})
        self._requireOk(d, f"/api/ohlc/{symbol}")
        candles = []
        for r in d.get("data", []):
            candles.append(
                Candle(
                    time=int(r["time"]),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=int(r.get("tick_volume", r.get("volume", 0))),
                )
            )
        return candles

    def get_open_positions(self, symbol: Optional[str] = None) -> list[BrokerPosition]:
        """دریافت پوزیشن‌های باز — حقیقت قطعی از خود بروکر."""
        if self._dry_run:
            out = list(self._sim_book.values())
            if symbol:
                out = [p for p in out if p.symbol == symbol]
            # تازه‌سازی قیمت لحظه‌ای و شناوری سود
            upd = []
            for p in out:
                try:
                    mid = self.get_tick(p.symbol).mid
                except BridgeError:
                    upd.append(p)
                    continue
                profit = (mid - p.open_price) * p.volume * 100.0 if p.is_buy \
                    else (p.open_price - mid) * p.volume * 100.0
                upd.append(dataclasses.replace(
                    p, current_price=mid,
                    profit=round(profit, 2),
                ))
            for p in upd:
                self._sim_book[p.ticket] = p
            return upd

        params = {"symbol": symbol} if symbol else None
        d = self._get("/api/positions", params=params)
        self._requireOk(d, "/api/positions")
        out = []
        for p in d.get("data", []):
            t = p.get("type")
            if isinstance(t, str):
                side = Side.BUY if t.upper() == "BUY" else Side.SELL
            else:
                side = Side.BUY if int(t) == 0 else Side.SELL
            op = float(p.get("price_open", p.get("open_price", 0.0)))
            cur_p = float(p.get("price_current") or p.get("current_price") or 0.0)
            if cur_p <= 0.0:
                prof = float(p.get("profit", 0.0))
                vol = float(p.get("volume", 0.0))
                if vol > 0.0:
                    diff = prof / (vol * 100.0)
                    cur_p = round(op + diff if side == Side.BUY else op - diff, 2)
                else:
                    cur_p = op

            out.append(
                BrokerPosition(
                    ticket=int(p["ticket"]),
                    symbol=str(p.get("symbol") or symbol or "XAUUSD"),
                    side=side,
                    volume=float(p["volume"]),
                    open_price=op,
                    current_price=cur_p,
                    sl=float(p.get("sl") or 0.0),
                    tp=float(p.get("tp") or 0.0),
                    profit=float(p.get("profit", 0.0)),
                    swap=float(p.get("swap", 0.0)),
                    commission=float(p.get("commission", 0.0)),
                    open_time=int(p.get("time") or time.time()),
                    comment=str(p.get("comment", "") or ""),
                )
            )
        return out

    def get_history_deals(self, days: int = 7, symbol: Optional[str] = None) -> list[dict]:
        """دریافت معاملات انجام‌شده گذشته جهت یادگیری و ممیزی ژورنال."""
        params: dict = {"days": days}
        if symbol:
            params["symbol"] = symbol
        d = self._get("/api/history/deals", params=params)
        self._requireOk(d, "/api/history/deals")
        return d.get("data", [])

    # ── اجرای سفارشات و مدیریت پوزیشن ───────────────────

    def place_order(
        self,
        order_id: str,
        symbol: str,
        side: Side,
        volume: float,
        sl: float,
        tp: float,
    ) -> Order:
        """ارسال سفارش به بازار همراه با Idempotency Key."""
        body = {
            "symbol": symbol,
            "type": side.value,
            "volume": volume,
            "comment": order_id,
            "magic": 20260901,
        }
        if sl > 0:
            body["sl"] = sl
        if tp > 0:
            body["tp"] = tp

        price_ref = self.get_tick(symbol).mid

        if self._dry_run:
            self._sim_ticket += 1
            ticket = self._sim_ticket
            pos = BrokerPosition(
                ticket=ticket,
                symbol=symbol,
                side=side,
                volume=volume,
                open_price=price_ref,
                current_price=price_ref,
                sl=sl,
                tp=tp,
                profit=0.0,
                swap=0.0,
                open_time=int(time.time()),
                comment=order_id,
                initial_sl=sl,
            )
            self._sim_book[ticket] = pos
            self._sim_save()
            log.info("DRY_RUN place_order %s %s %.2f lot sl=%.2f tp=%.2f → sim ticket=%d",
                     side.value, symbol, volume, sl, tp, ticket)
            return Order(
                order_id=order_id,
                plan_id="",
                ticket=ticket,
                symbol=symbol,
                side=side,
                volume=volume,
                price=price_ref,
                sl=sl,
                tp=tp,
                status=OrderStatus.FILLED,
            )

        d = self._post("/api/order", body)
        self._requireOk(d, "/api/order")
        ticket = int(d.get("ticket", 0))
        if ticket == 0:
            raise BridgeError(f"/api/order: ticket=0 retcode={d.get('retcode')}", retcode=d.get("retcode"))

        return Order(
            order_id=order_id,
            plan_id="",
            ticket=ticket,
            symbol=symbol,
            side=side,
            volume=float(d.get("volume", volume)),
            price=float(d.get("price", 0.0)),
            sl=sl,
            tp=tp,
            status=OrderStatus.FILLED,
        )

    def close_position(self, ticket: int) -> bool:
        """بستن کامل پوزیشن بر اساس شماره تیکت."""
        if self._dry_run:
            self._sim_book.pop(ticket, None)
            self._sim_save()
            log.info("DRY_RUN close_position ticket=%s", ticket)
            return True

        d = self._post("/api/close", {"ticket": ticket})
        self._requireOk(d, "/api/close")
        return True

    def partial_close(self, ticket: int, percent: float = 50.0) -> bool:
        """بستن پله‌ای (Partial Close) پوزیشن — مثلاً ۵۰٪ حجم در تارگت اول."""
        if self._dry_run:
            pos = self._sim_book.get(ticket)
            if pos is not None:
                new_vol = round(pos.volume * (1.0 - percent / 100.0), 2)
                if new_vol < 0.01:
                    self._sim_book.pop(ticket, None)
                else:
                    self._sim_book[ticket] = dataclasses.replace(pos, volume=new_vol)
                self._sim_save()
            log.info("DRY_RUN partial_close ticket=%s percent=%.1f%%", ticket, percent)
            return True

        d = self._post("/api/partial", {"ticket": ticket, "percent": percent})
        self._requireOk(d, "/api/partial")
        return True

    def modify_position(self, ticket: int, sl: float, tp: float) -> bool:
        """اصلاح سطوح Stop Loss یا Take Profit پوزیشن."""
        if self._dry_run:
            pos = self._sim_book.get(ticket)
            if pos is not None:
                self._sim_book[ticket] = dataclasses.replace(pos, sl=sl, tp=tp or pos.tp)
                self._sim_save()
            log.info("DRY_RUN modify ticket=%s sl=%.2f tp=%.2f", ticket, sl, tp)
            return True

        d = self._post("/api/modify", {"ticket": ticket, "sl": sl, "tp": tp})
        self._requireOk(d, "/api/modify")
        return True

    # ── پایش سلامت و اتصالات ──────────────────────────

    def health(self) -> bool:
        """بررسی سریع زنده بودن ترمینال و اتصال بروکر."""
        try:
            self.get_account()
            return True
        except BridgeError:
            return False

    def ping(self) -> dict:
        """سنجش تاخیر رفت و برگشت پکت‌ها (RTT Latency) به میلی‌ثانیه."""
        t0 = time.time()
        try:
            acc = self.get_account()
            dt_ms = round((time.time() - t0) * 1000, 2)
            return {
                "ok": True,
                "latency_ms": dt_ms,
                "login": acc.login,
                "balance": acc.balance,
                "equity": acc.equity,
            }
        except Exception as e:
            dt_ms = round((time.time() - t0) * 1000, 2)
            return {
                "ok": False,
                "latency_ms": dt_ms,
                "error": str(e),
            }

    def close(self) -> None:
        """بستن ایمن کانکشن پول Session."""
        try:
            self._session.close()
        except Exception:
            pass
