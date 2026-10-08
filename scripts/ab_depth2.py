"""Does the SMC verdict stablise only BEYOND the live 120-bar window?

ab_depth showed: at depth 120 (live config) bias=neutral/signal=wait; at
250+ a real verdict appeared. That was measured AFTER the b234 mitigation
fix, so the emptiness may have been the phantom bear book canceling the
bullish M5 call. Re-measure now with the fixed OB logic.

If the verdict is still empty at 120 but present at 250, the live scan is
running half-blind and the fetch depth should be raised.
"""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import fetch_all_ohlc
from engines.smc import smc_analyse

bc = BridgeClient()
bars = fetch_all_ohlc(bc, symbol='XAUUSD', timeframe='M5', count=3000)
h1 = bc.get_rates('XAUUSD', 'H1', 80)['data']

print(f"M5 {len(bars)} bars, H1 {len(h1)} bars\n")
print("=== SMC verdict vs M5 depth, FIXED OB logic ===")
print(f"{'depth':>6} {'bias':<9} {'conf':>5} {'sig':<9} {'obs':>4} {'act_ob':>6} {'pd_zone':<12}")
for depth in [20, 40, 60, 120, 250, 500, 1000]:
    window = bars[-depth:]
    r = smc_analyse(window, h1_rows=h1)
    print(f"{depth:>6} {str(r.get('bias')):<9} "
          f"{float(r.get('confidence') or 0):>5.2f} "
          f"{str(r.get('signal')):<9} "
          f"{len(r.get('order_blocks') or []):>4} "
          f"{len(r.get('active_order_blocks') or []):>6} "
          f"{str((r.get('premium_discount') or {}).get('zone')):<12}")
