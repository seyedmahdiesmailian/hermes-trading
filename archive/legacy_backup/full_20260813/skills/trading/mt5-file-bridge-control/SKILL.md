---
name: mt5-file-bridge-control
description: "Use when MT5 is controlled by file-bridge EA commands."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
---

# MT5 File-Bridge Control

Use this skill when Hermes is driving **MetaTrader 5 through a file-based Expert Advisor bridge** instead of a native MT5 API. This covers the class of setups where Hermes writes command files, the EA polls them on a timer, and MT5 writes back status files.

This skill exists for one core reason: these bridges often *look* flexible but still hide dangerous static behavior inside the EA (hardcoded lot size, fixed symbol, fixed SL/TP). Always verify the full chain end-to-end instead of trusting the cron job, prompt, or script layer.

## Trigger

Load this when:
- Hermes controls MT5 by writing `HermesCommand.txt` / reading `HermesStatus.txt`
- The user wants dynamic lot sizing, multi-symbol trading, or broader MT5 control
- A cron job appears to be using the wrong lot size and you need to find where it is actually defined
- You need to re-verify command/control after EA edits or MetaTrader changes

## Core lesson

**If trade size keeps acting like `0.1`, the problem may be inside the EA, not the cron job or shell script.**

The monitoring layer can be completely innocent while the EA still executes:
- `trade.Buy(0.1, ...)`
- `trade.Sell(0.1, ...)`

So the debugging order should be:
1. Inspect the cron/script layer
2. Inspect the EA source
3. Compile the EA
4. Verify with a real test command and a real status readback

## Preferred architecture

Hermes should be able to send structured commands like:

```text
ACTION=BUY;SYMBOL=XAUUSD;LOT=0.05;SL_POINTS=500;TP_POINTS=1000
ACTION=SELL;SYMBOL=EURUSD;LOT=0.03;SL_POINTS=200;TP_POINTS=400
ACTION=CLOSE;SYMBOL=XAUUSD
ACTION=CLOSEALL
```

The EA should:
- parse `ACTION`
- parse `SYMBOL`
- parse `LOT`
- parse `SL_POINTS`
- parse `TP_POINTS`
- normalize volume against broker min/max/step
- `SymbolSelect(symbol, true)` before execution
- keep legacy `BUY/SELL/CLOSE` support only as fallback, not as the main path

## Practical workflow

### 1) Check the shell/script layer first
Read the monitoring or cron script and confirm whether it actually sends trade size or only monitors status. Do not blame the scheduler before reading the script.

### 2) Inspect the EA for hidden static behavior
Look for patterns like:
- `trade.Buy(0.1, ... )`
- `trade.Sell(0.1, ... )`
- fixed `_Symbol` assumptions
- unused `RiskPerTrade` inputs that are declared but never applied

### 3) Replace fixed execution with structured execution
The EA should route all new trades through one function that:
- receives `action, symbol, lot, sl, tp`
- validates symbol
- normalizes lot size
- computes SL/TP using symbol point size and digits

### 4) Compile with MetaEditor CLI
On Windows MT5 installs, compile with MetaEditor directly instead of asking the user to do it manually.

Typical pattern:

```bash
"/c/Program Files/MetaTrader 5/MetaEditor64.exe" /compile:"C:\path\to\HermesTrade.mq5" /log:"C:\path\to\compile.log"
```

Then decode/read the compile log and verify:
- `0 errors`
- `0 warnings`
- `.ex5` artifact exists

### 5) Verify by real execution, not assumption
After compiling, send a **real structured command** and confirm behavior by reading `HermesStatus.txt` after the EA timer fires.

Verification pattern:
1. Send structured BUY with explicit symbol and lot
2. Wait for timer
3. Read `HermesStatus.txt`
4. Confirm `POSITIONS:1`
5. Send structured CLOSE
6. Read status again
7. Confirm `POSITIONS:0`

If you do not read back the real status file, you have not actually verified the bridge.

## Pitfalls

### Pitfall: blaming cron for static lot size
A cron job may simply call a monitor script while the EA is still hardcoded to `0.1`. Inspect the EA before changing scheduler logic.

### Pitfall: assuming `RiskPerTrade` means dynamic sizing exists
Many EAs declare a risk input but never use it. Confirm that volume is actually computed from it. If not, treat sizing as static.

### Pitfall: only supporting `BUY/SELL/CLOSE`
That blocks multi-symbol operation and dynamic risk management. Use key-value structured commands.

### Pitfall: compiling without verifying the runtime path
The `.mq5` can compile successfully while MT5 is still using an old or different attached EA. Confirm the compiled `.ex5` is in the active terminal's data folder and then verify runtime behavior through the file bridge.

### Pitfall: claiming success before a live readback
Compilation success is not enough. A real command plus a real status readback is required.

## User-workflow preferences this skill should honor

For users who delegate MT5 operations to Hermes end-to-end:
- do not make them inspect MT5 manually for routine verification
- keep the explanation concise
- prioritize real tool output over theory
- when changing execution logic, verify the bridge yourself

## Scope note

This skill is about the **file-bridge control plane**, not trade strategy. Strategy selection, signal quality, and market selection belong in separate trading skills.
