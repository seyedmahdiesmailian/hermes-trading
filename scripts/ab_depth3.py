"""Is the live 120-bar window unstable? Walk the END bar forward.

ab_depth2 froze the end bar. Real trading slides it forward every 5 minutes,
so a depth that produces a stable verdict at one instant may flip constantly
in live operation. Re-measure as a ROLLING scan: at each bar, compute the
verdict at depth 120 vs 500, and count how often each CHANGES its mind
relative to the previous bar. A high flip rate is a depth that is too
shallow — the bias chases noise.
"""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import fetch_all_ohlc
from engines.smc import smc_analyse

bc = BridgeClient()
bars = fetch_all_ohlc(bc, symbol='XAUUSD', timeframe='M5', count=1500)
h1 = bc.get_rates('XAUUSD', 'H1', 80)['data']

for depth in [120, 250, 500]:
    prev = None
    flips = 0
    n = 0
    neutrals = 0
    for i in range(depth, len(bars), 6):   # every 30 min
        window = bars[i - depth:i]
        r = smc_analyse(window, h1_rows=h1)
        b = str(r.get('bias'))
        if b == 'neutral':
            neutrals += 1
        if prev is not None and b != prev:
            flips += 1
        prev = b
        n += 1
    print(f"  depth {depth:>4}: {n:>3} samples  bias flips {flips:>3} "
          f"({flips/max(1,n)*100:>4.0f}%)  neutral {neutrals} ({neutrals/max(1,n)*100:>3.0f}%)")
