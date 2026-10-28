#!/usr/bin/env python3
"""Hermes Signal Processor Service.

Monitors forwarded Telegram signals and processes them through V2 pipeline:
1. Read forwarded messages
2. Parse with SignalParser
3. Analyze with ML Heuristic
4. Cross-validate with DecisionEngine
5. Execute if approved
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Set, Optional

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from brain.domain.services.signal_parser import SignalParser
from brain.domain.services.market_analyzer import MarketAnalyzer
from brain.domain.services.decision_engine import DecisionEngine
from brain.domain.services.risk_manager import RiskManager, RiskParameters
from brain.domain.services.learning_engine import LearningEngine
from brain.domain.entities.market import MarketState
from brain.domain.entities.account import AccountState
from brain.domain.value_objects.timeframe import TimeFrame, TimeFrameUnit
from brain.ml_heuristic_strategy import MLHeuristicStrategy
from adapters.gateways.mt5.mt5_gateway import MT5Gateway
from env_loader import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('logs/signal_processor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('SignalProcessor')


class SignalProcessorService:
    """Service that monitors and processes Telegram signals."""
    
    def __init__(self):
        """Initialize signal processor."""
        logger.info("🚀 Initializing Hermes Signal Processor...")
        
        # Load config
        env_file = PROJECT_ROOT / '.env'
        if env_file.exists():
            load_dotenv(env_file)
        
        # Forwarder storage path
        self.forwarder_storage = Path(
            "/home/ai/projects/forwarder-telegram-dockerized/forwarded_messages.json"
        )
        
        # Processed messages tracking
        self.processed_ids: Set[str] = set()
        self.processed_file = PROJECT_ROOT / 'data' / 'processed_signals.json'
        self._load_processed()
        
        # V2 Components
        self.parser = SignalParser()
        
        self.market_analyzer = MarketAnalyzer()
        self.market_analyzer.add_strategy(MLHeuristicStrategy(), weight=1.0)
        
        risk_params = RiskParameters(
            max_risk_per_trade_pct=0.02,
            max_daily_loss_pct=0.05,
            min_risk_reward=1.5
        )
        self.risk_manager = RiskManager(risk_params)
        self.learning_engine = LearningEngine()
        self.decision_engine = DecisionEngine(self.risk_manager, self.learning_engine)
        
        # MT5 Gateway
        mt5_url = os.getenv('MT5_BRIDGE_URL', 'http://192.168.10.51:5050')
        mt5_token = os.getenv('MT5_BRIDGE_TOKEN', '')
        self.mt5 = MT5Gateway(mt5_url, mt5_token)
        
        logger.info("✅ Signal Processor initialized")
        logger.info(f"   Forwarder storage: {self.forwarder_storage}")
        logger.info(f"   MT5 Bridge: {mt5_url}")
        logger.info(f"   Risk: {risk_params.max_risk_per_trade_pct*100}% per trade")
        logger.info(f"   Min R:R: {risk_params.min_risk_reward}")
    
    def _load_processed(self):
        """Load processed signal IDs."""
        if self.processed_file.exists():
            try:
                with open(self.processed_file, 'r') as f:
                    data = json.load(f)
                    self.processed_ids = set(data.get('processed_ids', []))
                logger.info(f"📂 Loaded {len(self.processed_ids)} processed signals")
            except Exception as e:
                logger.warning(f"⚠️ Could not load processed signals: {e}")
    
    def _save_processed(self):
        """Save processed signal IDs."""
        try:
            self.processed_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.processed_file, 'w') as f:
                json.dump({
                    'processed_ids': list(self.processed_ids),
                    'last_updated': datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.error(f"⛔ Could not save processed signals: {e}")
    
    def _read_forwarded_messages(self) -> Dict:
        """Read forwarded messages from forwarder storage."""
        if not self.forwarder_storage.exists():
            return {}
        
        try:
            with open(self.forwarder_storage, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"⛔ Could not read forwarded messages: {e}")
            return {}
    
    def _get_market_state(self, symbol: str) -> Optional[MarketState]:
        """Fetch current market state from MT5."""
        try:
            # Get current price
            tick_data = self.mt5.get_tick(symbol)
            if not tick_data:
                logger.error(f"Could not fetch tick for {symbol}")
                return None
            
            current_price = tick_data.get('bid', 0)
            
            # Get recent candles (get_candles returns 500 max from _fetch_candles)
            candles_data = self.mt5.get_candles(
                symbol=symbol,
                timeframe=TimeFrame(15, TimeFrameUnit.MINUTE),
                start=datetime.now(),  # Not used, gateway uses _fetch_candles
                end=datetime.now()
            )
            if not candles_data:
                logger.error(f"Could not fetch candles for {symbol}")
                return None
            
            # candles_data is already List[Candle] from gateway
            candles = candles_data
            
            return MarketState(
                symbol=symbol,
                timeframe='M15',
                timestamp=datetime.now(),
                current_price=current_price,
                bid=tick_data.get('bid', current_price),
                ask=tick_data.get('ask', current_price),
                candles=candles
            )
        
        except Exception as e:
            logger.error(f"⛔ Error fetching market state: {e}")
            return None
    
    def _get_account_state(self) -> Optional[AccountState]:
        """Fetch current account state from MT5."""
        try:
            return self.mt5.get_account_state()
        except Exception as e:
            logger.error(f"⛔ Error fetching account state: {e}")
            return None
    
    def process_signal(self, message_text: str, message_id: str) -> bool:
        """Process a single signal through V2 pipeline.
        
        Returns:
            True if trade executed, False otherwise
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"📨 Processing Signal ID: {message_id}")
        logger.info(f"   Text: {message_text[:100]}...")
        
        # Step 1: Parse
        parse_result = self.parser.parse(message_text)
        
        if not parse_result.success:
            logger.warning(f"❌ Parse failed: {parse_result.error}")
            return False
        
        signal = parse_result.signal
        logger.info(f"✅ Parsed: {signal.symbol} {signal.direction.upper()} @ {signal.entry_price:.2f}")
        logger.info(f"   SL: {signal.stop_loss:.2f} | TP: {signal.take_profit:.2f}")
        logger.info(f"   R:R: {signal.risk_reward_ratio():.2f} | Quality: {signal.quality.value}")
        
        # Step 2: Fetch market data
        market_state = self._get_market_state(signal.symbol)
        if not market_state:
            logger.error("❌ Could not fetch market data")
            return False
        
        logger.info(f"📊 Market: ${market_state.current_price:.2f}")
        
        # Step 3: Our analysis
        our_analysis = self.market_analyzer.analyze(market_state)
        logger.info(f"📈 Analysis: trend={our_analysis.trend}, confidence={our_analysis.confidence:.2f}")
        
        # Step 4: Get account state
        account_state = self._get_account_state()
        if not account_state:
            logger.error("❌ Could not fetch account state")
            return False
        
        logger.info(f"💰 Account: ${account_state.balance:,.2f} balance, {account_state.open_positions} positions")
        
        # Step 5: Cross-validate & decide
        decision_result = self.decision_engine.evaluate_signal_entry(
            signal=signal,
            our_analysis=our_analysis,
            market_state=market_state,
            account_state=account_state
        )
        
        logger.info(f"🤖 Decision: {decision_result.decision.value} (confidence: {decision_result.confidence:.0%})")
        logger.info(f"   Reasoning: {decision_result.reasoning}")
        
        # Step 6: Execute if approved
        if decision_result.should_execute():
            logger.info("✅ SIGNAL ACCEPTED - Executing trade...")
            
            # TODO: Execute via MT5
            # For now, just log
            logger.info(f"   📤 Would execute: {signal.direction} {signal.symbol}")
            logger.info(f"      Entry: {signal.entry_price}")
            logger.info(f"      SL: {signal.stop_loss} | TP: {signal.take_profit}")
            logger.info(f"      Size: {decision_result.action_params.get('position_size', 'N/A')}")
            
            # TODO: Uncomment when ready for live trading
            # self.mt5.place_order(...)
            
            return True
        else:
            logger.info(f"❌ SIGNAL REJECTED: {decision_result.decision.value}")
            return False
    
    def run(self, poll_interval: int = 10):
        """Run signal processor loop.
        
        Args:
            poll_interval: Seconds between checks
        """
        logger.info(f"\n🔄 Signal Processor running (polling every {poll_interval}s)...")
        logger.info(f"   Press Ctrl+C to stop\n")
        
        try:
            while True:
                messages = self._read_forwarded_messages()
                
                # Process new messages
                new_count = 0
                for msg_key, msg_data in messages.items():
                    msg_id = f"{msg_key}_{msg_data.get('message_id', '')}"  
                    
                    if msg_id in self.processed_ids:
                        continue
                    
                    message_text = msg_data.get('text', '')
                    if not message_text:
                        continue
                    
                    # Process
                    try:
                        executed = self.process_signal(message_text, msg_id)
                        
                        # Mark as processed
                        self.processed_ids.add(msg_id)
                        new_count += 1
                        
                        if executed:
                            logger.info("✅ Trade executed!")
                        
                    except Exception as e:
                        logger.error(f"⛔ Error processing signal {msg_id}: {e}")
                        import traceback
                        traceback.print_exc()
                
                if new_count > 0:
                    logger.info(f"\n✅ Processed {new_count} new signals")
                    self._save_processed()
                
                # Wait
                time.sleep(poll_interval)
        
        except KeyboardInterrupt:
            logger.info("\n⏹️  Signal Processor stopped by user")
            self._save_processed()
        
        except Exception as e:
            logger.error(f"⛔ Fatal error: {e}")
            import traceback
            traceback.print_exc()
            self._save_processed()


if __name__ == '__main__':
    service = SignalProcessorService()
    service.run(poll_interval=10)
