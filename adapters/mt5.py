""" adapters/mt5 — bridge HTTP client

تمام دسترسی به MT5 از این یک نقطه می‌گذرد.
بروکر = حقیقت نهایی. هر خطا = fail-closed (ترید نمی‌کنیم).
"""
from __future__ import annotations

import dataclasses
import logging
import time
from typing import Optional

import requests

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


class Mt5Adapter:
    """یک کلاینت HTTP به bridge روی ویندوز.

    همه متدها یا داده برمی‌گردانند یا BridgeError می‌دهند.
    هیچ‌گاه None خام برمی‌گردانند (جلوگیری از NPE در مغز).
    """

    def __init__(self, url: str, token: str, timeout_s: int = 10, dry_run: bool = True):
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._timeout = timeout_s
        self._dry_run = dry_run
        # b240: دفتر پوزیشن‌های شبیه‌سازی‌شده در dry_run.
        # bridge واقعی در dry_run سفارشی نمی‌بیند → این دفتر جایگزین
        # حقیقت بروکر می‌شود تا حلقه ورود/خروج مثل حالت LIVE کار کند.
        self._sim_ticket = 0
        self._sim_book: dict[int, BrokerPosition] = {}

    # ── private ─────────────────────────────────────────

    def _get(self, path: str, **params) -> dict:
        try:
            r = requests.get(
                f"{self._url}{path}", headers=self._headers,
                params=params, timeout=self._timeout,
            )
        except requests.RequestException as e:
            raise BridgeError(f"GET {path}: {e}") from e
        if r.status_code != 200:
            raise BridgeError(f"GET {path} → {r.status_code}")
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        try:
            r = requests.post(
                f"{self._url}{path}", headers=self._headers,
                json=body, timeout=self._timeout,
            )
        except requests.RequestException as e:
            raise BridgeError(f"POST {path}: {e}") from e
        if r.status_code != 200:
            raise BridgeError(f"POST {path} → {r.status_code}")
        return r.json()

    @staticmethod
    def _requireOk(doc: dict, path: str):
        if not doc.get("ok", False):
            raise BridgeError(f"{path}: bridge ok=false err={doc.get('error')}")

    # ── حساب و قیمت ────────────────────────────────────

    def get_account(self) -> AccountState:
        d = self._get("/api/account")
        self._requireOk(d, "/api/account")
        # bridge ممکن است margin/currency را نفرستد → پیش‌فرض امن
        return AccountState(
            balance=float(d["balance"]),
            equity=float(d["equity"]),
            margin=float(d.get("margin", d.get("margin_free", 0.0)) or 0.0),
            margin_free=float(d.get("margin_free", d["balance"])),
            currency=d.get("currency", "USD"),
            login=int(d.get("login", 0)),
        )

    def get_tick(self, symbol: str) -> Tick:
        d = self._get(f"/api/tick/{symbol}")
        self._requireOk(d, "/api/tick")
        return Tick(
            symbol=d.get("symbol", symbol),
            bid=float(d["bid"]),
            ask=float(d["ask"]),
            time=int(d["time"]),
        )

    def get_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        d = self._get(f"/api/ohlc/{symbol}", timeframe=timeframe, count=count)
        self._requireOk(d, "/api/ohlc")
        return [
            Candle(
                time=int(r["time"]),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=int(r["tick_volume"]),
            )
            for r in d["data"]
        ]

    def get_open_positions(self, symbol: Optional[str] = None) -> list[BrokerPosition]:
        """پوزیشن‌های باز — حقیقت نهایی، همیشه زنده."""
        # b240: در dry_run دفتر شبیه‌سازی حقیقت بروکر است
        if self._dry_run:
            out = list(self._sim_book.values())
            if symbol:
                out = [p for p in out if p.symbol == symbol]
            # به‌روزرسانی قیمت جاری و سود برای همه پوزیشن‌های شبیه‌سازی‌شده
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
            # بازنویسی دفتر با قیمت تازه (حقیقت زنده)
            for p in upd:
                self._sim_book[p.ticket] = p
            return upd
        d = self._get("/api/positions", symbol=symbol) if symbol else self._get("/api/positions")
        self._requireOk(d, "/api/positions")
        out = []
        for p in d["data"]:
            t = p.get("type")
            if isinstance(t, str):
                side = Side.BUY if t.upper() == "BUY" else Side.SELL
            else:
                side = Side.BUY if int(t) == 0 else Side.SELL
            out.append(
                BrokerPosition(
                    ticket=int(p["ticket"]),
                    symbol=p["symbol"],
                    side=side,
                    volume=float(p["volume"]),
                    open_price=float(p["price_open"]),
                    current_price=float(p.get("price_current", p["price_open"])),
                    sl=float(p.get("sl") or 0.0),
                    tp=float(p.get("tp") or 0.0),
                    profit=float(p.get("profit", 0.0)),
                    swap=float(p.get("swap", 0.0)),
                    open_time=int(p["time"]),
                    comment=p.get("comment", "") or "",
                )
            )
        return out

    # ── اجرا ───────────────────────────────────────────

    def place_order(
        self,
        order_id: str,
        symbol: str,
        side: Side,
        volume: float,
        sl: float,
        tp: float,
    ) -> Order:
        """ثبت سفارش — comment = order_id (کلید idempotency bridge).

        در dry_run=False سفارش واقعی ارسال می‌شود.
        """
        body = {
            "symbol": symbol,
            "type": side.value,
            "volume": volume,
            "comment": order_id,   # کلید Idempotency bridge (شروع با hms)
            "magic": 20260901,
        }
        if sl > 0:
            body["sl"] = sl
        if tp > 0:
            body["tp"] = tp

        # b240: قیمت ورود مرجع — در dry_run از tick زنده خوانده می‌شود
        price_ref = self.get_tick(symbol).mid

        if self._dry_run:
            # b240: ثبت در دفتر شبیه‌سازی — حقیقت بروکر در dry_run.
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
            )
            self._sim_book[ticket] = pos
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
            raise BridgeError(f"/api/order: ticket=0 retcode={d.get('retcode')}")

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
        """بستن پوزیشن با ticket."""
        if self._dry_run:
            # b240: حذف از دفتر شبیه‌سازی
            self._sim_book.pop(ticket, None)
            log.info("DRY_RUN close_position ticket=%s", ticket)
            return True
        d = self._post("/api/close", {"ticket": ticket})
        self._requireOk(d, "/api/close")
        return True

    def modify_position(self, ticket: int, sl: float, tp: float) -> bool:
        """اصلاح SL/TP پوزیشن (trailing / breakeven)."""
        if self._dry_run:
            # b240: اعمال SL جدید روی پوزیشن شبیه‌سازی‌شده
            pos = self._sim_book.get(ticket)
            if pos is not None:
                self._sim_book[ticket] = dataclasses.replace(pos, sl=sl, tp=tp or pos.tp)
            log.info("DRY_RUN modify ticket=%s sl=%.2f tp=%.2f", ticket, sl, tp)
            return True
        d = self._post("/api/modify", {"ticket": ticket, "sl": sl, "tp": tp})
        self._requireOk(d, "/api/modify")
        return True

    # ─ـ سلامت ──────────────────────────────────────────

    def health(self) -> bool:
        """بررسی زنده بودن bridge."""
        try:
            self.get_account()
            return True
        except BridgeError:
            return False
