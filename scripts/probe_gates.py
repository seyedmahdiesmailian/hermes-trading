#!/usr/bin/env python3
"""b2: replay the executor gates on the CURRENT live plan — which gate kills entries?"""
import sys, json
sys.path.insert(0, '/home/ai/hermes-trading')
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv('/home/ai/hermes-trading/.env')

from datetime import datetime, timezone
from bridge_client import BridgeClient
from engines.storage import load_current_plan, load_runtime_state
from engines.auto_executor import evaluate_proposal
from hermes_runtime import _performance_and_policy, _infer_setup_grade, _tick_price, PLAN_DIR

now = datetime.now(timezone.utc)
b = BridgeClient()
plan = load_current_plan(PLAN_DIR)
pp = _performance_and_policy(b, b.get_account(), now)
policy, perf = pp['account_policy'], pp['performance_state']
price = _tick_price(b.get_tick('XAUUSD'))

print(f"price={price} bias={plan.get('bias')} grade={_infer_setup_grade(plan)}")
print(f"policy: regime={policy.get('regime')} allowed={policy.get('trade_allowed')} open={policy.get('open_positions')}")
print(f"perf: daily_pnl={perf.get('daily_pnl')} trades_today={perf.get('trades_today')} loss_streak={perf.get('loss_streak')}")

# force a proposal from the plan blueprint regardless of zone proximity
bp = {
    'symbol': 'XAUUSD',
    'side': 'BUY' if plan.get('bias') == 'bullish' else 'SELL',
    'entry_price': price,
    'sl': plan.get('invalidation'),
    'tp': (plan.get('targets') or [price])[0],
    'tp_levels': plan.get('targets') or [],
    'trigger_ok': True,
}
proposal = {'blueprint': bp, 'monitor_action': 'market_entry_now', 'zone': 'probe', 'price': price, 'at': now.isoformat()}
res = evaluate_proposal(proposal, policy, perf, plan, b)
print(f"\nGATE RESULT: execute={res.get('execute')} reason={res.get('reason')}")
print(f"ALL REASONS: {res.get('reasons')}")
