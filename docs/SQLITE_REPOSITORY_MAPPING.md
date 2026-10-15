# SQLite Repository Mapping — Domain Interfaces → `database/schema.sql`

> **Purpose:** exhaustive, literal reference for writing a faithful SQLite implementation of
> `ITradeRepository`, `ISignalRepository`, `IStateRepository` using the domain entities, against
> the canonical SQL schema.
>
> **Scope:** read-only analysis. No source file was modified to produce this document.
>
> **Sources read in full** (all under `/home/ai/hermes-trading/`):
> 1. `brain/domain/repositories/trade_repo.py` (144 lines)
> 2. `brain/domain/repositories/signal_repo.py` (74 lines)
> 3. `brain/domain/repositories/state_repo.py` (97 lines)
> 4. `brain/domain/entities/plan.py` (144 lines)
> 5. `brain/domain/entities/trade.py` (146 lines)
> 6. `brain/domain/entities/signal.py` (112 lines)
> 7. `brain/domain/entities/account.py` (84 lines)
> 8. `adapters/gateways/data/json_repository.py` (383 lines)
> 9. `database/schema.sql` (392 lines)

---

## 0. Headline findings (read these before writing code)

1. **All deserializers in `json_repository.py` are stubs.** `_dict_to_plan`, `_dict_to_order`,
   `_dict_to_position`, `_dict_to_signal`, `_dict_to_account_state` each consist of a comment
   ("Simplified conversion - would need full implementation" / "Placeholder") followed by
   `return None`. **Every read path in the JSON repo is therefore broken**
   (`get_plan`/`get_active_plan`/`get_plan_history` → `None` or empty;
   `get_order`/`get_position`/`get_open_positions` → `None`/`[]`;
   `get_signal`/`get_pending_signals`/`get_recent_signals` → `None`/`[]`;
   `get_account_state` → `None`).
   *Only the `*_to_dict` (serialization) half is real.* The SQLite implementation must
   implement deserialization from scratch — there is no reference logic to copy. See §6 for
   the exact reconstruction semantics.
2. **The SQL schema does not match the entities 1:1.** It was designed for a different
   (V2/SMC-analysis) shape. Below is the gap inventory — **16 entity fields have no column**
   and will need `ALTER TABLE` or a JSON sidecar column.
3. **`json_repository.save_order` / `get_order` use `data/orders/`, a directory that
   `_ensure_structure` never creates.** It works only because `_write_json` does
   `path.parent.mkdir(parents=True, exist_ok=True)`. Replicate the *intent* (orders persist),
   not the incidental directory-creation detail.
4. **Enums serialize as their `.value` string** (`setup_grade.value`, `stage.value`,
   `type.value`, `status.value`, `source.value`, `quality.value`) — never `name` and never
   `repr`. See §6.7 for the exact convention the SQLite layer must follow.
5. **Timestamps:** JSON layer uses `.isoformat()` strings (naive local `datetime.now()`).
   The schema uses **integer Unix epochs** (`INTEGER`, `strftime('%s','now')` defaults), and
   the existing draft `sqlite_repository.py` header comment says *"Timestamps are stored
   UTC ISO-8601"* — a direct contradiction with `schema.sql`. A decision must be made;
   see §7.2.
6. **`get_closed_trades` is a hardcoded placeholder** returning `[]` in both the interface
   contract and the JSON impl ("Placeholder - would read from closed_trades.json").
7. **`mark_signal_processed` writes two loose keys** — `data['processed'] = True` and
   `data['result'] = result` — that are *not produced by* `_signal_to_dict`. The SQLite
   schema models this as `signals.status` + `signals.processed_at` + `signals.decision_reasoning`.

---

## 1. `ITradeRepository` — every abstract method

Source: `brain/domain/repositories/trade_repo.py`. All methods are `@abstractmethod` on
`class ITradeRepository(ABC)`. 9 abstract methods.

| # | Exact signature | Semantics (inferred from `json_repository.py`) |
|---|---|---|
| 1 | `def save_plan(self, plan: TradingPlan) -> None` | **Upsert by `plan.id`.** Writes `plans/history/plan_{plan.id}.json` *always*. Additionally, **if `plan.stage in [PlanStage.READY, PlanStage.EXECUTED, PlanStage.MONITORING]`**, overwrites `plans/current_plan.json` with the same dict — i.e. the "active plan" is a single-slot pointer keyed on stage, so saving a new active plan *replaces* the previous one. |
| 2 | `def get_plan(self, plan_id: str) -> Optional[TradingPlan]` | Read `plans/history/plan_{plan_id}.json`; `None` if missing/corrupt. |
| 3 | `def get_active_plan(self) -> Optional[TradingPlan]` | Read `plans/current_plan.json`; `None` if missing. Whatever stage was last written by rule in #1. |
| 4 | `def get_plan_history(self, start: datetime, end: datetime, limit: int = 100) -> List[TradingPlan]` | Scan `plans/history/plan_*.json`, **`sorted()` by filename (≤ `limit` files)**, keep plans with `start <= plan.created_at <= end` (inclusive both ends). **No ordering guarantee** in the returned list beyond filename sort. |
| 5 | `def save_order(self, order: Order) -> None` | Write `orders/order_{order.id}.json` (full overwrite). |
| 6 | `def get_order(self, order_id: str) -> Optional[Order]` | Read `orders/order_{order_id}.json`; `None` if missing. |
| 7 | `def save_position(self, position: Position) -> None` | Write `positions/{position.ticket}.json` (full overwrite — used both for initial save and for frequent price/profit updates). |
| 8 | `def get_position(self, ticket: int) -> Optional[Position]` | Read `positions/{ticket}.json`; `None` if missing. |
| 9 | `def get_open_positions(self, symbol: str \| None = None) -> List[Position]` | Scan every `positions/*.json`; keep all whose `position.order.symbol == symbol` when `symbol` is truthy, else all. **"Open" is implicit:** every file in `positions/` is treated as open; there is no status test and no deletion on close. |
| 10 | `def get_closed_trades(self, start: datetime, end: datetime, limit: int = 100) -> List[dict]` | **Placeholder — returns `[]` unconditionally** ('would read from closed_trades.json'). Returns plain dicts, not entities. |

*(10 rows: the interface declares 10 abstract methods — `save_plan`, `get_plan`,
`get_active_plan`, `get_plan_history`, `save_order`, `get_order`, `save_position`,
`get_position`, `get_open_positions`, `get_closed_trades`.)*

> **Subtlety to preserve:** `save_plan`'s active-slot rule means the JSON store holds *at most
> one* active plan, and `get_active_plan` can return a plan already in history. The SQLite
> equivalent is a `status='active'` row (schema models this: `plans.status` +
> view `v_current_plan`), and `get_active_plan` should be `SELECT ... WHERE status='active'
> ORDER BY created_at DESC LIMIT 1`.

---

## 2. `ISignalRepository` — every abstract method

Source: `brain/domain/repositories/signal_repo.py`. 5 abstract methods.

| # | Exact signature | Semantics (inferred from `json_repository.py`) |
|---|---|---|
| 1 | `def save_signal(self, signal: Signal) -> None` | Write `signals/history/signal_{signal.id}.json` (full overwrite). |
| 2 | `def get_signal(self, signal_id: str) -> Optional[Signal]` | Read `signals/history/signal_{signal_id}.json`; `None` if missing. |
| 3 | `def get_pending_signals(self) -> List[Signal]` | Read `signals/pending.json` (default `[]`) and convert every truthy element. **`pending.json` is never written by any method in this class** — it is an inbound queue populated by some other component. |
| 4 | `def get_recent_signals(self, limit: int = 50, start: datetime \| None = None) -> List[Signal]` | Scan `signals/history/signal_*.json`, `sorted(..., reverse=True)[:limit]` (**reverse filename order ≈ newest UUID-first, NOT time-first**), keep those with `signal.timestamp >= start` when `start` is truthy. |
| 5 | `def mark_signal_processed(self, signal_id: str, result: dict) -> None` | Read `signals/history/signal_{signal_id}.json`; **if it exists**, set `data['processed'] = True` and `data['result'] = result` and rewrite. **No-op (silently) if the signal was never saved.** Note `processed`/`result` are ad-hoc keys outside `_signal_to_dict`'s output. |

---

## 3. `IStateRepository` — every abstract method

Source: `brain/domain/repositories/state_repo.py`. 7 abstract methods.

| # | Exact signature | Semantics (inferred from `json_repository.py`) |
|---|---|---|
| 1 | `def save_account_state(self, state: AccountState) -> None` | Overwrite `state/account.json` with the serialized snapshot (single latest snapshot, no history). |
| 2 | `def get_account_state(self) -> Optional[AccountState]` | Read `state/account.json`; `None` if missing/corrupt. |
| 3 | `def save_performance_state(self, state: Dict[str, Any]) -> None` | Overwrite `state/performance.json` with the dict **verbatim** — no conversion, opaque blob. |
| 4 | `def get_performance_state(self) -> Dict[str, Any]` | Read `state/performance.json`, default `{}`. |
| 5 | `def save_learning_state(self, state: Dict[str, Any]) -> None` | Overwrite `state/learning.json` with the dict verbatim. |
| 6 | `def get_learning_state(self) -> Dict[str, Any]` | Read `state/learning.json`, default `{}`. |
| 7 | `def save_system_state(self, key: str, value: Any) -> None` | Read-merge-write of `state/system.json`: load whole dict (default `{}`), set `data[key] = value`, rewrite. **Single-key granularity; other keys preserved.** |
| 8 | `def get_system_state(self, key: str, default: Any = None) -> Any` | `state/system.json` → `.get(key, default)`. |

*(8 rows: the interface declares 8 abstract methods — `save_account_state`,
`get_account_state`, `save_performance_state`, `get_performance_state`,
`save_learning_state`, `get_learning_state`, `save_system_state`, `get_system_state`.)*

> **Total abstract methods across the three interfaces: 23** (10 + 5 + 8).
> `JSONRepository(ITradeRepository, ISignalRepository, IStateRepository)` implements all 23.

---

## 4. Entities — every field, type, and default

### 4.1 `TradingPlan` — `brain/domain/entities/plan.py` (line 46)

`@dataclass` — **18 fields.** All 8 mandatory fields are declared first (no default); the
remaining 10 have defaults.

| Field | Declared type | Default | Notes |
|---|---|---|---|
| `symbol` | `str` | *(none — mandatory)* | core setup |
| `direction` | `str` | *(none — mandatory)* | `"buy"` or `"sell"` (free-form; only `is_buy`/`is_sell` normalize with `.lower()`) |
| `entry_price` | `float` | *(none — mandatory)* | `__post_init__`: `<= 0` raises `ValueError` |
| `stop_loss` | `float` | *(none — mandatory)* | `__post_init__`: `<= 0` raises |
| `take_profit` | `float` | *(none — mandatory)* | `__post_init__`: `<= 0` raises |
| `position_size` | `float` | *(none — mandatory)* | `__post_init__`: `<= 0` raises |
| `setup_grade` | `SetupGrade` | *(none — mandatory)* | enum |
| `reasoning` | `dict` | *(none — mandatory)* | free-form analysis blob |
| `created_at` | `datetime` | `field(default_factory=lambda: datetime.now())` | **naive local** time |
| `id` | `str` | `field(default_factory=lambda: str(uuid.uuid4()))` | UUID4 string; PK |
| `stage` | `PlanStage` | `PlanStage.ANALYSIS` | enum |
| `executed_at` | `Optional[datetime]` | `None` | lifecycle timestamp |
| `closed_at` | `Optional[datetime]` | `None` | lifecycle timestamp |
| `ticket` | `Optional[int]` | `None` | broker ticket after execution |
| `actual_entry_price` | `Optional[float]` | `None` | fill price |
| `exit_price` | `Optional[float]` | `None` | |
| `profit` | `Optional[float]` | `None` | realized P&L |

*(17 rows: 8 mandatory + 9 defaulted. `__post_init__` at lines 80–89 validates
`entry_price`, `stop_loss`, `take_profit`, `position_size` are all `> 0`.)*

Methods (not persisted): `is_executable()`, `risk_reward_ratio()`, `risk_amount()`,
`potential_profit()`, `is_buy()`, `is_sell()`, `age_seconds()`, `mark_executed(ticket, actual_entry)`,
`mark_closed(exit_price, profit)`, `__repr__`.

> **`mark_executed` / `mark_closed` mutate `stage` AND the timestamps AND the result fields
> together** — a SQLite `save_plan` must persist all of them atomically, or the round-trip
> loses lifecycle state.

### 4.2 `Order` — `brain/domain/entities/trade.py` (line 26)

`@dataclass` — **10 fields.** Docstring: *"Immutable once created (use `replace()` for
modifications)"* — but it is a plain (non-frozen) dataclass.

| Field | Declared type | Default | Notes |
|---|---|---|---|
| `symbol` | `str` | *(none — mandatory)* | |
| `type` | `OrderType` | *(none — mandatory)* | enum |
| `volume` | `float` | *(none — mandatory)* | `__post_init__`: `<= 0` raises |
| `entry_price` | `float` | *(none — mandatory)* | `__post_init__`: `<= 0` raises |
| `stop_loss` | `float` | *(none — mandatory)* | `__post_init__`: `<= 0` raises |
| `take_profit` | `float` | *(none — mandatory)* | `__post_init__`: `<= 0` raises |
| `comment` | `str` | `""` | |
| `timestamp` | `datetime` | `field(default_factory=lambda: datetime.now())` | naive local |
| `id` | `str` | `field(default_factory=lambda: str(uuid.uuid4()))` | UUID4 string; PK |
| `status` | `OrderStatus` | `OrderStatus.PENDING` | enum |

`__post_init__` (lines 44–53): `volume`, `entry_price`, `stop_loss`, `take_profit` all `> 0`.

Methods: `risk_reward_ratio()`, `risk_amount()`, `reward_amount()`, `is_buy()`, `is_sell()`,
`__repr__`.

### 4.3 `Position` — `brain/domain/entities/trade.py` (line 87)

`@dataclass` — **8 fields.** Mutable by design ("price/profit updates frequently").

| Field | Declared type | Default | Notes |
|---|---|---|---|
| `ticket` | `int` | *(none — mandatory)* | **broker ticket; PK.** Used as the JSON filename (`positions/{ticket}.json`) |
| `order` | `Order` | *(none — mandatory)* | **nested entity** — see §6.5 |
| `open_time` | `datetime` | *(none — mandatory)* | naive local |
| `open_price` | `float` | *(none — mandatory)* | |
| `current_price` | `float` | *(none — mandatory)* | live, mutates |
| `profit` | `float` | `0.0` | live P&L |
| `max_profit` | `float` | `0.0` | MFE — comment: *"MFE (Max Favorable Excursion)"* |
| `max_loss` | `float` | `0.0` | MAE — comment: *"MAE (Max Adverse Excursion)"* |

Methods: `update_price(new_price, new_profit)` (mutates `current_price`, `profit`, and
ratchets `max_profit` up / `max_loss` down), `profit_pct()`, `duration_seconds()`,
`is_profitable()`, `distance_to_sl()`, `distance_to_tp()`, `__repr__`.

> **`Position` has no `status`/`closed` flag at all.** Open-vs-closed is purely "does the file
> exist" in JSON land. `position_state` in the schema has no status column either; `trades`
> has `status` (`open`/`closed`). The SQLite layer must derive the Position-open predicate
> from `trades.status='open'` (or its own bookkeeping) since the entity cannot say.

### 4.4 `Signal` — `brain/domain/entities/signal.py` (line 25)

`@dataclass` — **13 fields.**

| Field | Declared type | Default | Notes |
|---|---|---|---|
| `symbol` | `str` | *(none — mandatory)* | |
| `direction` | `str` | *(none — mandatory)* | `__post_init__`: must be exactly `"buy"` or `"sell"` (case-sensitive) |
| `entry_price` | `float` | *(none — mandatory)* | `__post_init__`: `> 0` |
| `stop_loss` | `float` | *(none — mandatory)* | `__post_init__`: `> 0` |
| `take_profit` | `float` | *(none — mandatory)* | `__post_init__`: `> 0` |
| `source` | `SignalSource` | *(none — mandatory)* | enum |
| `timestamp` | `datetime` | `field(default_factory=lambda: datetime.now())` | naive local |
| `id` | `str` | `field(default_factory=lambda: str(uuid.uuid4()))` | UUID4 string; PK |
| `raw_message` | `str` | `""` | original message text |
| `source_id` | `str` | `""` | message ID or source identifier |
| `confidence_score` | `float` | `0.5` | `__post_init__`: `0.0 <= x <= 1.0` |
| `quality` | `SignalQuality` | `SignalQuality.ACCEPTABLE` | enum |
| `validation_result` | `dict` | `field(default_factory=dict)` | **populated after evaluation** |
| `cross_check_result` | `dict` | `field(default_factory=dict)` | **populated after evaluation** |

*(14 rows: 6 mandatory + 8 defaulted.)*

`__post_init__` (lines 54–65) raises `ValueError` on non-positive prices, bad `direction`,
or out-of-range `confidence_score`.

Methods: `risk_reward_ratio()`, `risk_points()`, `reward_points()`, `is_buy()`, `is_sell()`,
`is_from_telegram()`, `is_high_quality()`, `age_seconds()`, `__repr__`.

> **`validation_result` and `cross_check_result` are NOT serialized by `_signal_to_dict`**
> (nor by `mark_signal_processed`, which writes `result` instead). They are write-side-only
> in memory. A SQLite impl should decide deliberately whether to store them (JSON sidecar)
> or mirror the JSON behavior and drop them. See §5.5.

### 4.5 `AccountState` — `brain/domain/entities/account.py` (line 30)

`@dataclass` — **11 fields.**

| Field | Declared type | Default | Notes |
|---|---|---|---|
| `balance` | `float` | *(none — mandatory)* | |
| `equity` | `float` | *(none — mandatory)* | |
| `margin_free` | `float` | *(none — mandatory)* | |
| `margin_used` | `float` | `0.0` | |
| `open_positions` | `int` | `0` | |
| `open_positions_volume` | `float` | `0.0` | |
| `daily_pnl` | `float` | `0.0` | |
| `daily_trades` | `int` | `0` | |
| `daily_wins` | `int` | `0` | |
| `daily_losses` | `int` | `0` | |
| `timestamp` | `Optional[datetime]` | `None` | **defaults to `None`, unlike other entities** |

Methods: `profit_today()`, `profit_today_pct()`, `win_rate_today()`, `margin_level()`,
`is_profitable_today()`, `has_open_positions()`, `__repr__`.

### 4.6 `Account` — `brain/domain/entities/account.py` (line 8)

`@dataclass` — **4 fields.** Included for completeness; **no repository method references it.**

| Field | Declared type | Default | Notes |
|---|---|---|---|
| `account_number` | `int` | *(none — mandatory)* | |
| `broker` | `str` | *(none — mandatory)* | |
| `currency` | `str` | `"USD"` | |
| `account_type` | `str` | `"demo"` | `"demo"` or `"live"` |

Methods: `is_live()`, `is_demo()`, `__repr__`.

---

## 5. Enum members — exact name and value

All enums are `class X(Enum)` with string values. **Value is what gets persisted.**

### 5.1 `SetupGrade` (`plan.py:10`) — 5 members
| Member | Value | Comment in source |
|---|---|---|
| `A` | `"A"` | Excellent — all factors aligned |
| `B` | `"B"` | Good — most factors aligned |
| `C` | `"C"` | Acceptable — some concerns |
| `D` | `"D"` | Poor — significant concerns |
| `F` | `"F"` | Failed — should not trade |

Has helpers `is_tradable()` (`self in [A, B]`) and `__lt__` (order A=0 < B=1 < C=2 < D=3 < F=4).

### 5.2 `PlanStage` (`plan.py:34`) — 8 members
| Member | Value |
|---|---|
| `ANALYSIS` | `"analysis"` |
| `WAITING` | `"waiting"` |
| `READY` | `"ready"` |
| `EXECUTED` | `"executed"` |
| `MONITORING` | `"monitoring"` |
| `CLOSED` | `"closed"` |
| `EXPIRED` | `"expired"` |
| `REJECTED` | `"rejected"` |

**Used by `save_plan`'s active-slot rule:** `stage in [READY, EXECUTED, MONITORING]` → also
write `current_plan.json`.

### 5.3 `OrderType` (`trade.py:10`) — 2 members
| Member | Value |
|---|---|
| `BUY` | `"buy"` |
| `SELL` | `"sell"` |

### 5.4 `OrderStatus` (`trade.py:16`) — 6 members
| Member | Value | Comment in source |
|---|---|---|
| `PENDING` | `"pending"` | Created but not sent |
| `SUBMITTED` | `"submitted"` | Sent to broker |
| `OPEN` | `"open"` | Active position |
| `CLOSED` | `"closed"` | Position closed |
| `CANCELLED` | `"cancelled"` | Order cancelled |
| `REJECTED` | `"rejected"` | Order rejected by broker |

### 5.5 `SignalSource` (`signal.py:9`) — 3 members
| Member | Value | Comment in source |
|---|---|---|
| `TELEGRAM` | `"telegram"` | External Telegram channel |
| `INTERNAL` | `"internal"` | Generated by our own analysis |
| `HYBRID` | `"hybrid"` | Combination of both |

### 5.6 `SignalQuality` (`signal.py:16`) — 5 members
| Member | Value | Comment in source |
|---|---|---|
| `EXCELLENT` | `"excellent"` | High confidence, all checks passed |
| `GOOD` | `"good"` | Good quality, minor concerns |
| `ACCEPTABLE` | `"acceptable"` | Acceptable but not ideal |
| `POOR` | `"poor"` | Low quality, high risk |
| `REJECTED` | `"rejected"` | Failed validation |

> **Enum vocabularies vs. schema vocabularies collide.** `plans.status` is
> `'active' | 'executed' | 'expired'` — **not** the `PlanStage` vocabulary (no `ready`,
> `monitoring`, `analysis`, …). `signals.status` is
> `'pending' | 'accepted' | 'rejected' | 'executed'` — **not** `OrderStatus` nor
> `SignalQuality`, and it overlaps-but-differs with `SignalQuality` (`accepted` ≠ anything in
> `SignalQuality`). `trades.status` is `'open' | 'closed'` — a strict subset of `OrderStatus`.
> Any faithful impl needs a documented mapping layer; see §7.1.

---

## 6. Serialization / deserialization in `json_repository.py` — exact logic

### 6.1 `TradingPlan` ↔ dict — `_plan_to_dict` (lines 278–298)

Serializes **all 17 fields**. Enums → `.value`; `created_at` → `.isoformat()`;
Optional datetimes → `.isoformat() if x else None`; Optionals passed through raw.

```python
def _plan_to_dict(self, plan: TradingPlan) -> dict:
    return {
        'id': plan.id,
        'symbol': plan.symbol,
        'direction': plan.direction,
        'entry_price': plan.entry_price,
        'stop_loss': plan.stop_loss,
        'take_profit': plan.take_profit,
        'position_size': plan.position_size,
        'setup_grade': plan.setup_grade.value,
        'reasoning': plan.reasoning,
        'created_at': plan.created_at.isoformat(),
        'stage': plan.stage.value,
        'executed_at': plan.executed_at.isoformat() if plan.executed_at else None,
        'closed_at': plan.closed_at.isoformat() if plan.closed_at else None,
        'ticket': plan.ticket,
        'actual_entry_price': plan.actual_entry_price,
        'exit_price': plan.exit_price,
        'profit': plan.profit
    }
```

`_dict_to_plan` (lines 300–303) — **STUB:**
```python
    # Simplified conversion - would need full implementation
    return None  # Placeholder
```

**Reconstruction semantics the SQLite impl must implement**:
`TradingPlan(symbol=..., direction=..., entry_price=..., stop_loss=..., take_profit=...,
position_size=..., setup_grade=SetupGrade(d['setup_grade']), reasoning=d['reasoning'],
created_at=datetime.fromisoformat(d['created_at']), id=d['id'],
stage=PlanStage(d['stage']), executed_at=<fromisoformat or None>,
closed_at=<fromisoformat or None>, ticket=d['ticket'],
actual_entry_price=d['actual_entry_price'], exit_price=d['exit_price'],
profit=d['profit'])`. Note `__post_init__` re-validates prices on reconstruction — a stored
`profit` can legitimately be negative but `entry_price` etc. cannot round-trip if `<= 0`.

### 6.2 `Order` ↔ dict — `_order_to_dict` (lines 305–318)

Serializes **all 10 fields**.

```python
def _order_to_dict(self, order: Order) -> dict:
    return {
        'id': order.id,
        'symbol': order.symbol,
        'type': order.type.value,
        'volume': order.volume,
        'entry_price': order.entry_price,
        'stop_loss': order.stop_loss,
        'take_profit': order.take_profit,
        'comment': order.comment,
        'timestamp': order.timestamp.isoformat(),
        'status': order.status.value
    }
```

`_dict_to_order` (lines 320–322) — **STUB: `return None  # Placeholder`**.

Reconstruction: position-or-keyword args in the declaration order above,
`type=OrderType(d['type'])`, `status=OrderStatus(d['status'])`,
`timestamp=datetime.fromisoformat(d['timestamp'])`.

### 6.3 `Position` ↔ dict — `_position_to_dict` (lines 324–335)

Serializes **all 8 fields**, with the nested `Order` **inlined as a sub-dict under the key
`'order'`** via `_order_to_dict` (no `order_id` reference — full embedding).

```python
def _position_to_dict(self, position: Position) -> dict:
    return {
        'ticket': position.ticket,
        'order': self._order_to_dict(position.order),
        'open_time': position.open_time.isoformat(),
        'open_price': position.open_price,
        'current_price': position.current_price,
        'profit': position.profit,
        'max_profit': position.max_profit,
        'max_loss': position.max_loss
    }
```

`_dict_to_position` (lines 337–339) — **STUB: `return None  # Placeholder`**.

**Nested-object handling (the pattern to replicate in SQLite):** the position is stored with
its order *embedded*, and reconstructing a `Position` requires first reconstructing the
inner `Order` from the sub-dict, then passing it as the `order=` positional/keyword argument:

```python
Position(
    ticket=d['ticket'],
    order=Order(id=d['order']['id'], symbol=d['order']['symbol'],
                type=OrderType(d['order']['type']), volume=d['order']['volume'],
                entry_price=d['order']['entry_price'], stop_loss=d['order']['stop_loss'],
                take_profit=d['order']['take_profit'], comment=d['order']['comment'],
                timestamp=datetime.fromisoformat(d['order']['timestamp']),
                status=OrderStatus(d['order']['status'])),
    open_time=datetime.fromisoformat(d['open_time']),
    open_price=d['open_price'], current_price=d['current_price'],
    profit=d['profit'], max_profit=d['max_profit'], max_loss=d['max_loss'],
)
```

**SQL equivalent:** `Position` maps onto `trades` (its own row keyed by `ticket`) joined to
`position_state` (same `ticket`, holds `mfe`/`mae`/`last_price`). The embedded `Order` is
*reconstructed from the position's own `trades` row* (`symbol`, `side`←`type`, `volume`,
`entry_price`, `stop_loss`, `take_profit`, `comment`, `entry_time`←`timestamp`), **not from a
separate `orders` table** — the schema has no `orders` table at all (see §7.3).

### 6.4 `Signal` ↔ dict — `_signal_to_dict` (lines 341–356)

Serializes **11 of 14 fields**. **Omits `validation_result` and `cross_check_result`.**

```python
def _signal_to_dict(self, signal: Signal) -> dict:
    return {
        'id': signal.id,
        'symbol': signal.symbol,
        'direction': signal.direction,
        'entry_price': signal.entry_price,
        'stop_loss': signal.stop_loss,
        'take_profit': signal.take_profit,
        'source': signal.source.value,
        'timestamp': signal.timestamp.isoformat(),
        'raw_message': signal.raw_message,
        'source_id': signal.source_id,
        'confidence_score': signal.confidence_score,
        'quality': signal.quality.value
    }
```

`_dict_to_signal` (lines 358–360) — **STUB: `return None  # Placeholder`**.

Reconstruction: `Signal(symbol=..., direction=..., entry_price=..., stop_loss=...,
take_profit=..., source=SignalSource(d['source']),
timestamp=datetime.fromisoformat(d['timestamp']), id=d['id'],
raw_message=d['raw_message'], source_id=d['source_id'],
confidence_score=d['confidence_score'], quality=SignalQuality(d['quality']))` — and
`validation_result` / `cross_check_result` come back as `{}` via their `default_factory`
unless the impl hydrates them from a JSON column.

### 6.5 `AccountState` ↔ dict — `_account_state_to_dict` (lines 362–376)

Serializes **all 11 fields**. `timestamp` uses the same conditional isoformat.

```python
def _account_state_to_dict(self, state: AccountState) -> dict:
    return {
        'balance': state.balance,
        'equity': state.equity,
        'margin_free': state.margin_free,
        'margin_used': state.margin_used,
        'open_positions': state.open_positions,
        'open_positions_volume': state.open_positions_volume,
        'daily_pnl': state.daily_pnl,
        'daily_trades': state.daily_trades,
        'daily_wins': state.daily_wins,
        'daily_losses': state.daily_losses,
        'timestamp': state.timestamp.isoformat() if state.timestamp else None
    }
```

`_dict_to_account_state` (lines 378–380) — **STUB: `return None  # Placeholder`**.

### 6.6 `Account` — **no converter exists** in `json_repository.py`. Not stored by any method.

### 6.7 The serialization conventions (generalize these to SQLite)

| Concern | Exact JSON behavior | SQLite implication |
|---|---|---|
| **Enums** | always `enum.value` (a lowercase-or-grade string) on write; reconstruct with `Enum(value)`. Never `name`, never `repr`. | store `TEXT` holding the `.value`; `EnumClass(text)` on read. |
| **Datetimes (non-Optional)** | `dt.isoformat()` — from **naive `datetime.now()`** (no tz). | schema wants `INTEGER` epoch seconds; the draft sqlite repo wants ISO strings. Pick one and convert symmetrically (§7.2). |
| **Datetimes (Optional)** | `dt.isoformat() if dt else None` — stored as JSON `null`. | nullable column / `NULL`. |
| **Nested entity (`Position.order`)** | embedded in full as a sub-dict under key `'order'`; no FK/id reference. | denormalize the order into the position's `trades` row, or JSON-sidecar it. |
| **dict fields (`reasoning`, `validation_result`, …)** | written verbatim (`json.dump(..., default=str)` tolerates non-JSON values by stringifying them — lossy fallback). | `TEXT` column with `json.dumps`; `json.loads` on read. |
| **Floats / Optional floats** | passed through; `None` → JSON `null`. | `REAL` nullable columns. |
| **UUIDs / ids** | stored as `str`; `id` and `ticket` double as file-name keys: `plan_{id}.json`, `order_{id}.json`, `{ticket}.json`, `signal_{id}.json`. | `plan_id TEXT UNIQUE NOT NULL`, `signal_id TEXT UNIQUE NOT NULL`, `ticket INTEGER UNIQUE NOT NULL` — all present in schema. ✔ |
| **Lossy write fallback** | `_write_json` uses `json.dump(data, f, indent=2, default=str)` — any non-serializable value (e.g. a nested `datetime` inside `reasoning`) is silently stringified. | prefer explicit `json.dumps(..., default=str)` for parity, or reject early. |

### 6.8 Storage topology of the JSON store (for behavioral parity)

```
data/
├── plans/current_plan.json          ← single-slot active plan (save_plan, stage ∈ {READY,EXECUTED,MONITORING})
├── plans/history/plan_{id}.json     ← one file per plan (always written by save_plan)
├── signals/pending.json             ← inbound queue; NEVER written by JSONRepository itself
├── signals/history/signal_{id}.json ← one file per signal
├── state/account.json               ← AccountState (latest only)
├── state/performance.json           ← opaque dict
├── state/learning.json              ← opaque dict
├── state/system.json                ← key→value map
├── positions/{ticket}.json          ← one file per position (open by convention)
└── orders/order_{id}.json           ← NOT created by _ensure_structure (mkdir'd lazily by _write_json)
```
Concurrent access: `fcntl.flock` `LOCK_SH` on read, `LOCK_EX` on write. SQLite gets this for
free via transactions/WAL.

---

## 7. `database/schema.sql` — exact target table definitions

Engine: SQLite (→ PostgreSQL future). Conventions: `id INTEGER PRIMARY KEY AUTOINCREMENT`
surrogate; natural keys as `TEXT`/`INTEGER UNIQUE NOT NULL`; **all timestamps `INTEGER`
Unix epochs**, with `created_at INTEGER DEFAULT (strftime('%s', 'now'))`.

### 7.1 `plans`

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | `PRIMARY KEY AUTOINCREMENT` |
| `plan_id` | TEXT | `UNIQUE NOT NULL` (+ redundant trailing `UNIQUE(plan_id)`) |
| `symbol` | TEXT | `NOT NULL` |
| `timeframe` | TEXT | `NOT NULL` |
| `bias` | TEXT | `NOT NULL` — comment: bullish, bearish, neutral |
| `session` | TEXT | nullable — asia, london, newyork |
| `value_low` | REAL | nullable |
| `value_high` | REAL | nullable |
| `long_entry_low` | REAL | nullable |
| `long_entry_high` | REAL | nullable |
| `short_entry_low` | REAL | nullable |
| `short_entry_high` | REAL | nullable |
| `atr` | REAL | nullable |
| `grade` | TEXT | nullable — comment: A, B, C |
| `setup_score` | REAL | nullable |
| `created_at` | INTEGER | `NOT NULL` |
| `expires_at` | INTEGER | `NOT NULL` |
| `status` | TEXT | `DEFAULT 'active'` — active, executed, expired |
| `analysis_json` | TEXT | nullable — JSON blob |

Indexes: `idx_plans_symbol ON plans(symbol, created_at DESC)`;
`idx_plans_status ON plans(status, created_at DESC)`.

> **`grade` comment says "A, B, C"** — but `SetupGrade` has 5 values (A,B,C,D,F). Storing
> `D`/`F` is not forbidden by a CHECK, just undocumented.

### 7.2 `signals`

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | `PRIMARY KEY AUTOINCREMENT` |
| `signal_id` | TEXT | `UNIQUE NOT NULL` (+ trailing `UNIQUE(signal_id)`) |
| `symbol` | TEXT | `NOT NULL` |
| `direction` | TEXT | `NOT NULL` — buy, sell |
| `entry_price` | REAL | `NOT NULL` |
| `stop_loss` | REAL | `NOT NULL` |
| `take_profit` | REAL | `NOT NULL` |
| `source` | TEXT | `NOT NULL` — telegram, internal, hybrid |
| `source_id` | TEXT | nullable |
| `raw_message` | TEXT | nullable |
| `confidence_score` | REAL | nullable |
| `quality` | TEXT | nullable — excellent, good, acceptable, poor, rejected |
| `status` | TEXT | `DEFAULT 'pending'` — pending, accepted, rejected, executed |
| `processed_at` | INTEGER | nullable |
| `decision_reasoning` | TEXT | nullable |
| `received_at` | INTEGER | `NOT NULL` |
| `created_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |

Indexes: `idx_signals_status ON signals(status, received_at DESC)`;
`idx_signals_symbol ON signals(symbol, received_at DESC)`.

### 7.3 `trades`

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | `PRIMARY KEY AUTOINCREMENT` |
| `ticket` | INTEGER | `UNIQUE NOT NULL` |
| `position_id` | INTEGER | nullable |
| `symbol` | TEXT | `NOT NULL` |
| `side` | TEXT | `NOT NULL` — buy, sell |
| `volume` | REAL | `NOT NULL` |
| `entry_price` | REAL | `NOT NULL` |
| `stop_loss` | REAL | nullable |
| `take_profit` | REAL | nullable |
| `exit_price` | REAL | nullable |
| `profit` | REAL | nullable |
| `commission` | REAL | nullable |
| `swap` | REAL | nullable |
| `net_pnl` | REAL | nullable |
| `source` | TEXT | nullable — plan_id, signal_id, manual |
| `source_ref` | TEXT | nullable — reference to plan or signal |
| `entry_time` | INTEGER | `NOT NULL` |
| `exit_time` | INTEGER | nullable |
| `duration_seconds` | INTEGER | nullable |
| `status` | TEXT | `DEFAULT 'open'` — open, closed |
| `exit_reason` | TEXT | nullable — sl, tp, manual, managed, trail |
| `comment` | TEXT | nullable |
| `created_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |
| `updated_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |

Indexes: `idx_trades_status(status, entry_time DESC)`; `idx_trades_symbol(symbol, entry_time DESC)`;
`idx_trades_source(source, source_ref)`.

> ⚠ **There is no `orders` table.** `Order` has no dedicated destination; it must be folded
> into `trades` (Order↔Position share the row) or into an `analysis_json`-style blob.
> ⚠ `updated_at` has `DEFAULT (strftime('%s','now'))` but **no trigger** to refresh it —
> the repository must set it explicitly on every `save_position`.

### 7.4 `position_state`

| Column | Type | Constraints |
|---|---|---|
| `ticket` | INTEGER | `PRIMARY KEY` |
| `mfe` | REAL | nullable — Max Favorable Excursion |
| `mae` | REAL | nullable — Max Adverse Excursion |
| `breakeven_moved` | BOOLEAN | `DEFAULT 0` |
| `partial_tp_count` | INTEGER | `DEFAULT 0` |
| `trail_active` | BOOLEAN | `DEFAULT 0` |
| `last_check_at` | INTEGER | nullable |
| `last_price` | REAL | nullable |
| `updated_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |

`FOREIGN KEY (ticket) REFERENCES trades(ticket)`.

> Maps to `Position.max_profit` (→`mfe`), `max_loss` (→`mae`), `current_price` (→`last_price`).
> The remaining columns are management state with **no entity counterpart**.

### 7.5 `account_snapshots`

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | `PRIMARY KEY AUTOINCREMENT` |
| `balance` | REAL | `NOT NULL` |
| `equity` | REAL | `NOT NULL` |
| `margin` | REAL | nullable |
| `margin_free` | REAL | nullable |
| `open_positions` | INTEGER | `DEFAULT 0` |
| `daily_pnl` | REAL | nullable |
| `daily_trades` | INTEGER | nullable |
| `win_rate` | REAL | nullable |
| `snapshot_at` | INTEGER | `NOT NULL` |
| `created_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |

Index: `idx_account_snapshots_time ON account_snapshots(snapshot_at DESC)`.
**Append-only table** — `get_account_state` = latest row (`ORDER BY snapshot_at DESC LIMIT 1`,
or `MAX(id)`).

### 7.6 `daily_performance` (performance state)

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | `PRIMARY KEY AUTOINCREMENT` |
| `date` | TEXT | `UNIQUE NOT NULL` — YYYY-MM-DD |
| `gross_pnl` | REAL | nullable |
| `net_pnl` | REAL | nullable |
| `commission_total` | REAL | nullable |
| `swap_total` | REAL | nullable |
| `total_trades` | INTEGER | nullable |
| `winning_trades` | INTEGER | nullable |
| `losing_trades` | INTEGER | nullable |
| `win_rate` | REAL | nullable |
| `max_drawdown` | REAL | nullable |
| `avg_win` | REAL | nullable |
| `avg_loss` | REAL | nullable |
| `profit_factor` | REAL | nullable |
| `created_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |

### 7.7 `market_data` (no entity counterpart)

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | `PRIMARY KEY AUTOINCREMENT` |
| `symbol` | TEXT | `NOT NULL` |
| `timeframe` | TEXT | `NOT NULL` |
| `timestamp` | INTEGER | `NOT NULL` — Unix timestamp |
| `open` | REAL | `NOT NULL` |
| `high` | REAL | `NOT NULL` |
| `low` | REAL | `NOT NULL` |
| `close` | REAL | `NOT NULL` |
| `volume` | REAL | nullable |
| `created_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |

`UNIQUE(symbol, timeframe, timestamp)`; index `idx_market_data_symbol_tf(symbol, timeframe, timestamp DESC)`.

### 7.8 `risk_state`

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | `PRIMARY KEY AUTOINCREMENT` |
| `defcon_level` | TEXT | `NOT NULL` — GREEN, YELLOW, RED |
| `loss_streak` | INTEGER | `DEFAULT 0` |
| `daily_loss_pct` | REAL | nullable |
| `kill_switch_active` | BOOLEAN | `DEFAULT 0` |
| `cooldown_until` | INTEGER | nullable |
| `risk_multiplier` | REAL | `DEFAULT 1.0` |
| `min_grade` | TEXT | nullable |
| `effective_at` | INTEGER | `NOT NULL` |
| `created_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |

Index: `idx_risk_state_time(effective_at DESC)`. **No entity/class in the domain layer
models risk state** — reachable only via `save_system_state`/`get_system_state` or a
future interface.

### 7.9 `safety_events`

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | `PRIMARY KEY AUTOINCREMENT` |
| `event_type` | TEXT | `NOT NULL` — kill_switch, cooldown, defcon_change |
| `severity` | TEXT | `NOT NULL` — info, warning, critical |
| `message` | TEXT | `NOT NULL` |
| `data_json` | TEXT | nullable — additional context |
| `created_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |

Index: `idx_safety_events_time(created_at DESC)`.

### 7.10 `trade_journal`

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | `PRIMARY KEY AUTOINCREMENT` |
| `ticket` | INTEGER | `NOT NULL` |
| `setup_grade` | TEXT | nullable |
| `setup_style` | TEXT | nullable |
| `session` | TEXT | nullable |
| `net_pnl` | REAL | nullable |
| `rr_realized` | REAL | nullable |
| `exit_type` | TEXT | nullable — sl, tp, managed, trail |
| `plan_id` | TEXT | nullable |
| `signal_id` | TEXT | nullable |
| `mfe` | REAL | nullable |
| `mae` | REAL | nullable |
| `duration_minutes` | INTEGER | nullable |
| `notes` | TEXT | nullable |
| `close_time` | INTEGER | `NOT NULL` |
| `created_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |

`FOREIGN KEY (ticket) REFERENCES trades(ticket)`; indexes on `(setup_grade, close_time DESC)`
and `(session, close_time DESC)`.

### 7.11 `learning_adjustments`

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | `PRIMARY KEY AUTOINCREMENT` |
| `parameter` | TEXT | `NOT NULL` |
| `old_value` | REAL | nullable |
| `new_value` | REAL | `NOT NULL` |
| `reason` | TEXT | nullable |
| `sample_size` | INTEGER | nullable |
| `applied_at` | INTEGER | `NOT NULL` |
| `created_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |

### 7.12 `config`

| Column | Type | Constraints |
|---|---|---|
| `key` | TEXT | `PRIMARY KEY` |
| `value` | TEXT | `NOT NULL` |
| `data_type` | TEXT | `DEFAULT 'string'` — string, int, float, bool, json |
| `description` | TEXT | nullable |
| `updated_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |

Seeded by `INSERT OR IGNORE` with `max_risk_per_trade`, `min_risk_reward`, `max_daily_loss`,
`max_daily_trades`, `max_open_positions`, `min_setup_grade`.

### 7.13 `system_state`

| Column | Type | Constraints |
|---|---|---|
| `key` | TEXT | `PRIMARY KEY` |
| `value` | TEXT | `NOT NULL` |
| `updated_at` | INTEGER | `DEFAULT (strftime('%s', 'now'))` |

Seeded with `last_master_run`, `last_position_check`, `last_signal_check`,
`bridge_last_healthy`, `dry_run`.

> Natural target for `save_system_state`/`get_system_state`. **Caveat:** `value` is
> `TEXT NOT NULL` — arbitrary `Any` values must be JSON-encoded, and `get_system_state` must
> decode (or stringify) them; `NULL` values are impossible to store as-is.

### 7.14 Views (defined in schema.sql)

- `v_active_trades` — `trades.*` + `position_state.{mfe,mae,breakeven_moved,trail_active}`,
  `WHERE t.status = 'open'`.
- `v_recent_performance` — `daily_performance` last 30 days.
- `v_current_plan` — `SELECT * FROM plans WHERE status='active' AND expires_at >
  strftime('%s','now') ORDER BY created_at DESC LIMIT 1` — **this is the schema's
  `get_active_plan` implementation**, and it additionally enforces expiry.

---

## 8. Field-to-column mapping (the core deliverable)

Notation: ✔ direct fit · ◐ needs transform · ⚠ **NO COLUMN — needs `ALTER TABLE` or JSON sidecar.**

### 8.1 `TradingPlan` → `plans` table

| Entity field | → Column | Fit | Transform / note |
|---|---|---|---|
| `id` (`str`, UUID4) | `plans.plan_id` | ✔ | TEXT natural key |
| `symbol` | `plans.symbol` | ✔ | |
| `direction` (`"buy"`/`"sell"`) | `plans.bias` | ◐ | **vocabulary mismatch**: `buy`→`bullish`, `sell`→`bearish`; or store raw and treat `bias` as free TEXT |
| `entry_price` | `plans.long_entry_high` / `short_entry_high`? | ⚠ | **no unambiguous `entry_price` column.** Zone columns are ranges, not a single entry. Recommend storing in `analysis_json` (or `ALTER TABLE plans ADD COLUMN entry_price REAL`). |
| `stop_loss` | — | ⚠ | **no column.** → `analysis_json` or ALTER TABLE. |
| `take_profit` | — | ⚠ | **no column.** → `analysis_json` or ALTER TABLE. |
| `position_size` | — | ⚠ | **no column.** → `analysis_json` or ALTER TABLE. |
| `setup_grade` | `plans.grade` | ◐ | `.value` TEXT; schema comment documents only A/B/C but enum also has D/F |
| `reasoning` (`dict`) | `plans.analysis_json` | ◐ | `json.dumps`; schema's intended "detailed context" blob |
| `created_at` | `plans.created_at` | ◐ | `datetime` ↔ INTEGER epoch |
| `id` (dup of above) | `plans.id` | — | surrogate key only; never store the entity ID here |
| `stage` | `plans.status` | ◐ | **vocabulary mismatch**: `PlanStage` (8 values) → `status` ('active','executed','expired'). Recommended mapping: `ANALYSIS|WAITING|READY → 'active'`, `EXECUTED|MONITORING → 'executed'`, `CLOSED|EXPIRED → 'expired'`, `REJECTED → 'expired'`. **Lossy — full `stage` should also go into `analysis_json`.** |
| `executed_at` | — | ⚠ | **no column.** → `analysis_json` or ALTER TABLE. |
| `closed_at` | — | ⚠ | **no column.** → `analysis_json` or ALTER TABLE. |
| `ticket` | — | ⚠ | **no column** (could ride in `analysis_json`; the schema instead links via `trades.source='plan_id'`). |
| `actual_entry_price` | — | ⚠ | **no column.** → `analysis_json` / `trades.entry_price` (after execution). |
| `exit_price` | — | ⚠ | **no column.** → `analysis_json` / `trades.exit_price`. |
| `profit` | — | ⚠ | **no column.** → `analysis_json` / `trades.net_pnl`. |
| *(none)* | `plans.timeframe` | — | **no entity field** — mandatory `NOT NULL`! Must supply a default (e.g. `'H1'`/`'D1'`) or fail the INSERT. |
| *(none)* | `plans.expires_at` | — | **no entity field** — mandatory `NOT NULL`! Must synthesize (e.g. `created_at + N`, or equal to `created_at`); `v_current_plan` filters on it. |
| *(none)* | `plans.bias`, `session`, `value_low/high`, `long/short_entry_low/high`, `atr`, `setup_score` | — | **no entity fields** — leave NULL / derive from `reasoning` if present. |

**Unmapped TradingPlan fields (7):** `entry_price`, `stop_loss`, `take_profit`,
`position_size`, `executed_at`, `closed_at`, `ticket`, `actual_entry_price`, `exit_price`,
`profit` → **10 fields** require `analysis_json` (or `ALTER TABLE`).
*(Counted strictly as fields with no dedicated column: **10**.)*
**Plus 2 mandatory schema columns (`timeframe`, `expires_at`) with no entity source.**

> **Recommended plan-table strategy:** put the 10 unmapped fields into `analysis_json` as a
> JSON object keyed by field name (`{"entry_price": …, "stop_loss": …, "stage": "ready", …}`),
> keeping `plan_id`/`symbol`/`grade`/`created_at`/`status` as indexed columns. `v_current_plan`
> continues to work. Alternative: `ALTER TABLE plans ADD COLUMN entry_price REAL` etc. for
> queryability.

### 8.2 `Order` → `trades` table (schema has **no `orders` table**)

| Entity field | → Column | Fit | Transform / note |
|---|---|---|---|
| `id` (`str`, UUID4) | `trades.source_ref` (with `source='order'`) | ◐ | **no dedicated column.** Or store in `comment`; or ALTER TABLE. Best: `source='manual'`/`'order'`, `source_ref=order.id`. |
| `symbol` | `trades.symbol` | ✔ | |
| `type` | `trades.side` | ✔ | `OrderType.BUY.value == 'buy'` — **exact match** with `side` vocabulary |
| `volume` | `trades.volume` | ✔ | |
| `entry_price` | `trades.entry_price` | ✔ | |
| `stop_loss` | `trades.stop_loss` | ✔ | nullable in schema, but entity guarantees `> 0` |
| `take_profit` | `trades.take_profit` | ✔ | |
| `comment` | `trades.comment` | ✔ | |
| `timestamp` | `trades.entry_time` | ◐ | `datetime` ↔ INTEGER epoch |
| `status` | `trades.status` | ◐ | **vocabulary mismatch**: `OrderStatus` (6 values) → ('open','closed'). Map `PENDING|SUBMITTED → 'open'`, `OPEN → 'open'`, `CLOSED → 'closed'`, `CANCELLED|REJECTED → 'closed'`. Lossy — stash full `status` in `comment`/`analysis_json`-like column, or ALTER TABLE. |
| *(none)* | `trades.ticket` | — | `NOT NULL UNIQUE` — for a bare Order there is no ticket. **Saving a ticket-less Order is impossible** without synthesizing one (e.g. negative/uuid-derived) → strongly suggests Orders should only be persisted as part of a `Position`. |
| *(none)* | `trades.created_at`, `updated_at` | — | auto-defaults; set `updated_at` explicitly on update. |

**Unmapped Order fields:** `id` (no dedicated column — use `source_ref`) and,
functionally, `status` (lossy vocabulary). **2 fields.**

### 8.3 `Position` → `trades` + `position_state` (1:1 on `ticket`)

| Entity field | → Column | Fit | Transform / note |
|---|---|---|---|
| `ticket` (`int`) | `trades.ticket` | ✔ | natural key; also `position_state.ticket` (PK, FK) |
| `order` (`Order`) | *(embedded → `trades` row columns)* | ◐ | **denormalized**: the Order's fields populate `trades.symbol`/`side`/`volume`/`entry_price`/`stop_loss`/`take_profit`/`comment`/`entry_time`, and `Order.id` → `trades.source_ref`. Reconstruct by building an `Order` from those columns (§6.3). |
| `open_time` | `trades.entry_time` | ◐ | `datetime` ↔ INTEGER epoch |
| `open_price` | `trades.entry_price` | ✔ | semantically the fill price |
| `current_price` | `position_state.last_price` | ◐ | nullable in schema; entity guarantees a value |
| `profit` | `trades.profit` | ✔ | live P&L; also could mirror to `net_pnl` |
| `max_profit` | `position_state.mfe` | ✔ | MFE — exact intended target |
| `max_loss` | `position_state.mae` | ✔ | MAE — exact intended target |
| *(none)* | `trades.status` | — | **open/closed discriminator** the entity lacks (§4.3). `get_open_positions` → `WHERE status='open'` (+ optional `symbol`). |

**Unmapped Position fields: none.** (All 8 fields have a column; `order` is embedded.)
⚠ But **`position_state.mfe`/`mae`/`last_price` are nullable** while the entity fields default
to `0.0` and `current_price` is mandatory — treat SQL `NULL` on read as `0.0` / required.

### 8.4 `Signal` → `signals` table — **the cleanest fit**

| Entity field | → Column | Fit | Transform / note |
|---|---|---|---|
| `id` | `signals.signal_id` | ✔ | TEXT natural key |
| `symbol` | `signals.symbol` | ✔ | |
| `direction` | `signals.direction` | ✔ | both `"buy"`/`"sell"` — exact match |
| `entry_price` | `signals.entry_price` | ✔ | schema `NOT NULL`, entity guarantees `> 0` |
| `stop_loss` | `signals.stop_loss` | ✔ | |
| `take_profit` | `signals.take_profit` | ✔ | |
| `source` | `signals.source` | ✔ | `telegram`/`internal`/`hybrid` — **exact enum match** |
| `timestamp` | `signals.received_at` | ◐ | `datetime` ↔ INTEGER epoch |
| `raw_message` | `signals.raw_message` | ✔ | nullable in schema, defaults `""` in entity |
| `source_id` | `signals.source_id` | ✔ | |
| `confidence_score` | `signals.confidence_score` | ✔ | |
| `quality` | `signals.quality` | ✔ | all 5 enum values documented in the column comment — **exact match** |
| `validation_result` | — | ⚠ | **no column.** → `decision_reasoning` (TEXT, but semantically the reject reason) or JSON sidecar; JSON impl simply **drops it** |
| `cross_check_result` | — | ⚠ | **no column.** same options; JSON impl drops it |
| *(none)* | `signals.status` | — | no entity field; `DEFAULT 'pending'`. `get_pending_signals` → `WHERE status='pending'`; `mark_signal_processed` → set `status` + `processed_at` + `decision_reasoning`. |
| *(none)* | `signals.processed_at` | — | set by `mark_signal_processed` |
| *(none)* | `signals.decision_reasoning` | — | target for the `result` dict of `mark_signal_processed` |
| *(none)* | `signals.created_at` | — | auto-default |

**Unmapped Signal fields (2):** `validation_result`, `cross_check_result`.
JSON behavior is to drop them silently; the SQLite impl could persist them by extending
 `decision_reasoning` to hold `{"result": …, "validation": …, "cross_check": …}` or by adding
 a JSON column.

### 8.5 `AccountState` → `account_snapshots` table

| Entity field | → Column | Fit | Transform / note |
|---|---|---|---|
| `balance` | `account_snapshots.balance` | ✔ | `NOT NULL` ✔ |
| `equity` | `account_snapshots.equity` | ✔ | `NOT NULL` ✔ |
| `margin_free` | `account_snapshots.margin_free` | ✔ | |
| `margin_used` | `account_snapshots.margin` | ◐ | **renamed**: `margin_used` → `margin` |
| `open_positions` | `account_snapshots.open_positions` | ✔ | `DEFAULT 0` ✔ |
| `open_positions_volume` | — | ⚠ | **no column.** Could go in `daily_pnl`? No — recommend JSON sidecar or ALTER TABLE. |
| `daily_pnl` | `account_snapshots.daily_pnl` | ✔ | |
| `daily_trades` | `account_snapshots.daily_trades` | ✔ | |
| `daily_wins` | — | ⚠ | **no column.** schema has `win_rate` instead (derived). |
| `daily_losses` | — | ⚠ | **no column.** (same; `win_rate = wins/(wins+losses)`) |
| `timestamp` | `account_snapshots.snapshot_at` | ◐ | `datetime` ↔ INTEGER epoch. **Entity default is `None`** → must synthesize (`now`) when saving, or `snapshot_at` is `NOT NULL` and the INSERT fails. |
| *(none)* | `account_snapshots.win_rate` | — | derive from `daily_wins/(daily_wins+daily_losses)` if both present, else NULL |
| *(none)* | `account_snapshots.margin`, `created_at` | — | see above |

**Unmapped AccountState fields (3):** `open_positions_volume`, `daily_wins`, `daily_losses`.
**Plus `timestamp` may be `None` while `snapshot_at` is `NOT NULL`.**
Options: (a) `ALTER TABLE account_snapshots ADD COLUMN open_positions_volume REAL,
daily_wins INTEGER, daily_losses INTEGER`; (b) stash them in a JSON blob — no such column
exists on this table, so (a) is the practical route; (c) reconstruct `daily_wins`/
`daily_losses` as **0** and accept the loss of information.

### 8.6 `Account` → **no table, no repository method**

Not persisted by any interface method. Persist only if a future requirement adds it
(candidates: `config` table, or `ALTER TABLE account_snapshots ADD COLUMN account_number…`).

### 8.7 Free-form state → tables

| Interface method pair | → Table | Fit |
|---|---|---|
| `save_performance_state` / `get_performance_state` | `daily_performance` | ◐ — schema is a **structured** daily summary keyed by `date TEXT`; the interface passes an **arbitrary `Dict[str, Any]`**. Columns overlap on `net_pnl`, `total_trades`, `winning_trades`, `losing_trades`, `win_rate`. Unknown keys: **no JSON sidecar column** on this table → either map known keys and drop the rest, or JSON-encode the whole dict into one of the free TEXT columns (`date` is the natural key, so this is awkward). Recommend: map known keys; or `ALTER TABLE daily_performance ADD COLUMN extra_json TEXT`. |
| `save_learning_state` / `get_learning_state` | `learning_adjustments` | ◐ — schema is an **append-only adjustment log** (`parameter`, `old_value`, `new_value`, `applied_at`), not a state blob. The interface contract is load-whole-dict. Options: treat the latest row per `parameter` as the state (pivot), or add a `learning_state` JSON table. **No JSON column exists here either.** |
| `save_system_state` / `get_system_state` | `system_state` | ✔ — `key TEXT PRIMARY KEY, value TEXT NOT NULL`. **Must JSON-encode `Any` values** and decode on read. |
| *(any)* | `config` | — keyed like `system_state` but with `data_type` + `description`; seeded with defaults. Best left to app config, not general state. |
| *(any)* | `safety_events`, `trade_journal`, `market_data`, `risk_state` | — no interface method touches these; populated by other components. |

---

## 9. Consolidated unmapped-field inventory

Entity fields with **NO matching column in `schema.sql`** (require `ALTER TABLE` or a JSON
sidecar column):

| Entity | Unmapped fields | Count |
|---|---|---|
| `TradingPlan` | `entry_price`, `stop_loss`, `take_profit`, `position_size`, `executed_at`, `closed_at`, `ticket`, `actual_entry_price`, `exit_price`, `profit` | **10** |
| `Order` | `id` (no dedicated col → `source_ref`), `status` (lossy vocab) | **2** |
| `Position` | *(none — all 8 map)* | **0** |
| `Signal` | `validation_result`, `cross_check_result` | **2** |
| `AccountState` | `open_positions_volume`, `daily_wins`, `daily_losses` | **3** |
| `Account` | `account_number`, `broker`, `currency`, `account_type` (whole entity; no table) | **4** |
| **Total** | | **21** |

Inverse gaps — **schema columns with no entity source** (must be synthesized on write):
`plans.timeframe` (NOT NULL), `plans.expires_at` (NOT NULL), `plans.bias`/`session`/zones/
`atr`/`setup_score`, `trades.ticket` (NOT NULL when saving a bare Order), `trades.commission`/
`swap`/`net_pnl`/`exit_*`/`duration_seconds`/`exit_reason`/`position_id`, `signals.status`/
`processed_at`/`decision_reasoning`, `account_snapshots.win_rate` (+ `snapshot_at` NOT NULL
vs `timestamp` defaulting to `None`), and the whole of `market_data`, `risk_state`,
`safety_events`, `trade_journal`, `learning_adjustments`.

---

## 10. Semantics notes for a faithful SQLite implementation

1. **Upsert idempotency.** JSON `save_*` overwrites in place. SQLite equivalent: `INSERT
   INTO … ON CONFLICT(plan_id) DO UPDATE SET …` (or `INSERT OR REPLACE`, which preserves the
   surrogate `id` poorly — prefer the upsert). Natural keys are `plans.plan_id`,
   `signals.signal_id`, `trades.ticket`.
2. **`save_plan` dual-write.** Replicate "always history, also current if stage ∈
   {READY, EXECUTED, MONITORING}" as: upsert the `plans` row and set `status` appropriately
   (active ⟺ stage ∈ {ANALYSIS, WAITING, READY} by the §8.1 mapping — note the JSON rule's
   three stages are a *subset* of what the schema calls active; pick deliberately).
   `v_current_plan` then implements `get_active_plan` (and adds an expiry filter).
3. **`get_plan_history(start, end, limit)`:** `WHERE created_at BETWEEN <start_epoch> AND
   <end_epoch> ORDER BY created_at DESC LIMIT :limit`. (JSON impl sorts by filename and is
   effectively unordered — SQLite can only improve on this.)
4. **`get_recent_signals(limit, start)`:** `ORDER BY received_at DESC LIMIT :limit`, with
   `AND received_at >= :start` when `start` is not None. (JSON impl sorts by filename.)
5. **`get_pending_signals`:** `SELECT … FROM signals WHERE status='pending' ORDER BY
   received_at ASC`. The JSON `pending.json` queue is unmanaged by this class, so the SQLite
   impl must own the pending→processed transition via `mark_signal_processed`
   (`status ∈ {accepted, rejected, executed}`, `processed_at = now`, `decision_reasoning`
   ← `json.dumps(result)`).
6. **`mark_signal_processed` on a missing signal:** JSON impl is a **silent no-op**. SQLite
   equivalent: `UPDATE … WHERE signal_id = ?` and ignore `rowcount == 0` (do NOT insert).
7. **`get_open_positions(symbol)`:** `SELECT … FROM trades t LEFT JOIN position_state ps ON
   ps.ticket = t.ticket WHERE t.status='open'` (+ `AND t.symbol = ?` when truthy). Order is
   unspecified in JSON; order by `ticket` for determinism.
8. **`save_position` must be a two-table upsert** (`trades` + `position_state`) in one
   transaction, refresh `trades.updated_at` and `position_state.updated_at`, and keep
   `mfe`/`mae` monotonic (entity already ratchets them in `update_price` — just persist).
9. **`get_closed_trades(start, end, limit)`:** unimplemented in JSON (returns `[]`). A real
   SQLite version would `SELECT … FROM trades WHERE status='closed' AND exit_time BETWEEN
   …`, optionally joined to `trade_journal`, and return **dicts** (the signature says
   `List[dict]`, not entities).
10. **Atomicity & concurrency.** JSON uses `fcntl` flock per file; SQLite should use
    `BEGIN IMMEDIATE` transactions + `PRAGMA journal_mode=WAL` (the existing draft
    `sqlite_repository.py` already sets WAL and `row_factory = sqlite3.Row` — reuse that
    base class).
11. **Deserialization must be written from scratch** — every `_dict_to_*` in
    `json_repository.py` is `return None` (§0.1, §6). Use `Enum(value)` for enums and
    `datetime.fromisoformat()` (or `datetime.fromtimestamp(epoch, tz=utc)`) for times.
    Round-trip every entity in a test.
12. **Multi-method repository.** A single SQLite class should implement all three interfaces
    (`ITradeRepository, ISignalRepository, IStateRepository`) over one connection, exactly as
    `JSONRepository` does — that is the composition callers expect.

---

## 11. Known contradictions / decisions to make before coding

| # | Contradiction | Detail | Recommendation |
|---|---|---|---|
| 1 | **Timestamp format** | `schema.sql` uses `INTEGER` epoch seconds everywhere; the draft `sqlite_repository.py` docstring says "Timestamps are stored UTC ISO-8601"; entities produce naive local `datetime.now()`. | Follow `schema.sql` (INTEGER epochs, UTC) — it is the canonical schema named in the task. Add explicit `to_epoch()`/`from_epoch()` helpers and document that JSON's naive-local timestamps become UTC. |
| 2 | **Enum vocabularies** | `PlanStage` (8) vs `plans.status` (3); `OrderStatus` (6) vs `trades.status` (2); `SignalQuality` vs `signals.status` (overlap on `rejected` only). | Map on write per §8.1/§8.2, and *also* store the exact enum `.value` in a JSON sidecar (`analysis_json`) so round-trips are lossless. |
| 3 | **No `orders` table** | `Order` is an entity with its own `id`, but the schema has nowhere for standalone orders. | Fold `Order` into the `trades` row of its `Position` (order_id → `source_ref`); only persist standalone orders by synthesizing a `ticket`. |
| 4 | **`Position` has no close concept** | Entity has no status; JSON treats "file exists" as open. | Use `trades.status` as the source of truth; `save_position` when a position closes must set `status='closed'` (and `exit_time`/`exit_price`/`net_pnl`) — decide which layer owns that transition. |
| 5 | **`AccountState.timestamp` default `None` vs `snapshot_at NOT NULL`** | | Synthesize `snapshot_at = now` when `state.timestamp is None` (and never store `None`); record the entity's own timestamp in `created_at`-adjacent JSON if needed. |
| 6 | **` signals` pending semantics** | JSON keeps an external `pending.json` never written by the repo. | SQLite owns the lifecycle: `status='pending'` on save, transitions in `mark_signal_processed`. |
| 7 | **Opaque dict state** (`performance`, `learning`) | Interface passes arbitrary dicts; schema has structured tables (`daily_performance`, `learning_adjustments`) with no JSON column. | Decide between (a) map known keys & drop unknowns (lossy), (b) `ALTER TABLE … ADD COLUMN extra_json TEXT`, or (c) add small sidecar tables. Do not silently corrupt the dict. |
| 8 | **`json.dump(default=str)`** | JSON writes stringify unserializable values silently; `reasoning` dicts may contain anything. | For SQLite use `json.dumps(x, default=str)` for parity, or define explicit serialization for known shapes. |

---

**End of document.** — Produced by a read-only analysis pass over the nine files listed at
the top. No source file under `/home/ai/hermes-trading/` was modified; the only artifact
created is this file itself.
