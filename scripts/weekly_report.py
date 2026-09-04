#!/usr/bin/env python3
"""Weekly management report for the trading system (Persian, Telegram-ready).

Collects: live balance, 7-day journal stats, lifetime stats, funnel
activity (plans vs trades), open positions, safety-gate skips,
and system changes (git) — prints a formatted report to stdout.
Cron-safe: never raises; on data failure prints what it has.
"""
import sys, os, csv, time, json, glob, subprocess, statistics

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

# Documented precedence (b52/b63): explicit HERMES_BRIDGE_URL > derived
# from HERMES_WIN_IP > last-known default. Resolved at module level so the
# b52 behavioural test can import and inspect it.
BRIDGE_URL = os.getenv("HERMES_BRIDGE_URL") or \
    f"http://{os.getenv('HERMES_WIN_IP', '192.168.10.51')}:5050"

DAYS = 7
WEEK_S = DAYS * 86400
FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')

def fa(x):
    return str(x).translate(FA_DIGITS)

def money(v):
    sign = '+' if v >= 0 else '−'
    return f"{sign}{fa(f'{abs(v):,.2f}')}$"

def pct(v):
    return fa(f"{v:.0f}") + '٪'

def main():
    now = time.time()
    lines = []

    # ── journal (closed trades) ────────────────────────────────────────
    # Journal rows are per CLOSING DEAL. A position closed in parts (partial
    # TPs) writes several rows, so counting rows overstates the trade count.
    # Group by position_id first — this reported "34 trades" for 23 positions
    # until 2026-09-04.
    rows = []
    try:
        with open(os.path.join(_ROOT, 'data/xau_plan/trade_journal.csv')) as f:
            rows = list(csv.DictReader(f))
    except Exception as e:
        lines.append(f"⚠️ ژورنال خوانده نشد: {e}")

    try:
        from engines.learning import group_positions
        positions = list(group_positions(rows).values())
    except Exception:
        positions = [{'net': r.get('profit'), 'close_time': r.get('close_time'),
                      'volume': r.get('volume')} for r in rows]

    def stats(subset):
        if not subset:
            return None
        # 'net' = gross profit + commission + swap (see learning.group_positions)
        p = [float(r['net']) for r in subset if r.get('net') is not None
             and str(r.get('net')) != '']
        w = [x for x in p if x > 0]
        l = [x for x in p if x <= 0]
        return dict(n=len(p), total=sum(p), wins=len(w), losses=len(l),
                    wr=(100.0*len(w)/len(p)) if p else 0,
                    avg_w=statistics.mean(w) if w else 0,
                    avg_l=statistics.mean(l) if l else 0,
                    best=max(p), worst=min(p))

    week = [r for r in positions if now - float(r['close_time'] or 0) <= WEEK_S]
    sw, sa = stats(week), stats(positions)

    # ── live bridge state ──────────────────────────────────────────────
    # Documented precedence (b52/b63): explicit HERMES_BRIDGE_URL >
    # derived from HERMES_WIN_IP > bridge_client default. Read by NAME.
    acct, open_pos = None, None
    try:
        from bridge_client import BridgeClient
        b = BridgeClient(url=BRIDGE_URL)
        acct = b.get_account()
        pos = b.get_positions()
        open_pos = pos.get('data', []) if isinstance(pos, dict) else []
    except Exception as e:
        lines.append(f"⚠️ بریج پاسخ نداد: {e}")

    # ── funnel activity ────────────────────────────────────────────────
    n_plans = len([p for p in glob.glob(os.path.join(
        _ROOT, 'data/xau_plan/plan_history/*.json'))
        if now - os.path.getmtime(p) <= WEEK_S])

    # ── safety-gate skips this week (from runtime log) ─────────────────
    skips = {}
    try:
        log = os.path.join(_ROOT, 'logs/master.log')
        cutoff = now - WEEK_S
        with open(log, errors='ignore') as f:
            for ln in f:
                if 'daily_trade_limit' in ln: skips['سقف ترید روزانه'] = skips.get('سقف ترید روزانه', 0) + 1
                if 'daily_loss_limit' in ln: skips['سقف ضرر روزانه'] = skips.get('سقف ضرر روزانه', 0) + 1
                if 'macro_blackout' in ln: skips['بلک‌اوت اخبار'] = skips.get('بلک‌اوت اخبار', 0) + 1
    except Exception:
        pass

    # ── system changes (git) ───────────────────────────────────────────
    commits = []
    try:
        out = subprocess.run(
            ['git', 'log', f'--since={DAYS} days', '--oneline', '--',
             'engines/', 'hermes_runtime.py', 'hermes_master.py', 'config.py'],
            cwd=_ROOT, capture_output=True, text=True, timeout=20).stdout
        commits = [l.split(' ', 1)[1][:90] for l in out.strip().splitlines()]
    except Exception:
        pass

    # ── render ─────────────────────────────────────────────────────────
    t = time.gmtime(now)
    lines.insert(0, f"📊 گزارش هفتگی هرمس — {fa(t.tm_year)}/{fa(t.tm_mon)}/{fa(t.tm_mday)}")
    lines.append("")
    if acct:
        bal = float(acct.get('balance', 0)); eq = float(acct.get('equity', 0))
        base = 5000.0
        lines.append(f"💰 بالانس: {fa(f'{bal:,.2f}')}$ | اکوئیتی: {fa(f'{eq:,.2f}')}$")
        lines.append(f"📈 کل بازده از شروع: {money(bal-base)} ({pct(100*(bal-base)/base)})")
    if open_pos is not None:
        if open_pos:
            lines.append(f"🔓 پوزیشن باز: {fa(len(open_pos))}")
            for p in open_pos[:5]:
                lines.append(f"   • {p.get('type','?')} {fa(p.get('volume','?'))} @ {fa(p.get('price_open','?'))} | شناور {money(float(p.get('profit',0)))}")
        else:
            lines.append("🔒 پوزیشن باز: صفر")
    lines.append("")
    lines.append(f"— ۷ روز گذشته ({fa(sw['n']) if sw else '۰'} معامله بسته) —")
    if sw:
        lines.append(f"✅ برد: {fa(sw['wins'])} | ❌ باخت: {fa(sw['losses'])} | وین‌ریت {pct(sw['wr'])}")
        lines.append(f"💵 سود هفته: {money(sw['total'])}")
        lines.append(f"میانگین برد {money(sw['avg_w'])} | میانگین باخت {money(sw['avg_l'])}")
        lines.append(f"بهترین {money(sw['best'])} | بدترین {money(sw['worst'])}")
    else:
        lines.append("معامله‌ای بسته نشد.")
    lines.append("")
    lines.append(f"— قیف سیستم (۷ روز) —")
    lines.append(f"🧠 پلن تحلیل‌شده: {fa(n_plans)} | تبدیل به معامله: {fa(sw['n']) if sw else '۰'} ({pct(100*(sw['n'])/n_plans) if sw and n_plans else '۰'})")
    if skips:
        lines.append("🛡 گیت‌های ایمنی فعال: " + " | ".join(f"{k} ×{fa(v)}" for k, v in skips.items()))
    lines.append("")
    lines.append(f"— کل از شروع ({fa(sa['n']) if sa else '۰'} معامله) —")
    if sa:
        lines.append(f"وین‌ریت {pct(sa['wr'])} | سود کل {money(sa['total'])} | میانگین هر معامله {money(sa['total']/sa['n'])}")
    if commits:
        lines.append("")
        lines.append(f"— تغییرات سیستم ({fa(len(commits))} کامیت) —")
        for c in commits[:6]:
            lines.append(f"• {c}")
    print("\n".join(lines))

if __name__ == '__main__':
    main()
