#!/usr/bin/env python3
"""Telegram Signal Listener - Direct channel monitoring.

Reads signals directly from Telegram channels and processes them.
No dependency on forwarder.
"""

import os
import sys
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Set

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from telethon import TelegramClient, events
from env_loader import load_dotenv

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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('logs/telegram_listener.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('TelegramListener')


class TelegramSignalListener:
    """Listens to Telegram channels and processes trading signals."""
    
    def __init__(self):
        """Initialize Telegram listener."""
        logger.info("🚀 Initializing Telegram Signal Listener...")
        
        # Load env
        env_file = PROJECT_ROOT / '.env'
        if env_file.exists():
            load_dotenv(env_file)
        
        # Telegram credentials from .env
        self.api_id = int(os.getenv('TELEGRAM_API_ID', '0'))
        self.api_hash = os.getenv('TELEGRAM_API_HASH', '')
        
        if not self.api_id or not self.api_hash:
            raise ValueError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env")
        
        # Signal channels to monitor (from .env or hardcoded)
        self.signal_channels = os.getenv('SIGNAL_CHANNELS', '').split(',')
        self.signal_channels = [ch.strip() for ch in self.signal_channels if ch.strip()]
        
        if not self.signal_channels:
            logger.warning("⚠️ No SIGNAL_CHANNELS configured in .env")
        
        # Telegram client
        self.client = TelegramClient(
            'hermes_signal_session',
            self.api_id,
            self.api_hash
        )
        
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
        
        # Processed message tracking
        self.processed_ids: Set[int] = set()
        
        logger.info("✅ Telegram Listener initialized")
        logger.info(f"   Channels: {self.signal_channels}")
        logger.info(f"   MT5 Bridge: {mt5_url}")
        logger.info(f"   Risk: {risk_params.max_risk_per_trade_pct*100}% per trade")
    
    def _get_market_state(self, symbol: str) -> MarketState | None:
        """Fetch current market state from MT5."""
        try:
            tick_data = self.mt5.get_tick(symbol)
            if not tick_data:
                logger.error(f"Could not fetch tick for {symbol}")
                return None
            
            current_price = tick_data.get('bid', 0)
            
            candles = self.mt5.get_candles(
                symbol=symbol,
                timeframe=TimeFrame(15, TimeFrameUnit.MINUTE),
                start=datetime.now(),
                end=datetime.now()
            )
            
            if not candles:
                logger.error(f"Could not fetch candles for {symbol}")
                return None
            
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
    
    def _get_account_state(self) -> AccountState | None:
        """Fetch current account state from MT5."""
        try:
            return self.mt5.get_account_state()
        except Exception as e:
            logger.error(f"⛔ Error fetching account state: {e}")
            return None
    
    async def process_signal(self, message_text: str, message_id: int, channel_name: str):
        """Process incoming signal."""
        if message_id in self.processed_ids:
            return
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📨 New Signal from {channel_name}")
        logger.info(f"   ID: {message_id}")
        logger.info(f"   Text: {message_text[:150]}...")
        
        try:
            # Parse
            parse_result = self.parser.parse(message_text)
            
            if not parse_result.success:
                logger.warning(f"❌ Parse failed: {parse_result.error}")
                self.processed_ids.add(message_id)
                return
            
            signal = parse_result.signal
            logger.info(f"✅ Parsed: {signal.symbol} {signal.direction.upper()} @ {signal.entry_price:.2f}")
            logger.info(f"   SL: {signal.stop_loss:.2f} | TP: {signal.take_profit:.2f}")
            logger.info(f"   R:R: {signal.risk_reward_ratio():.2f} | Quality: {signal.quality.value}")
            
            # Fetch market data
            market_state = self._get_market_state(signal.symbol)
            if not market_state:
                logger.error("❌ Could not fetch market data")
                self.processed_ids.add(message_id)
                return
            
            logger.info(f"📊 Market: ${market_state.current_price:.2f}")
            
            # Analysis
            our_analysis = self.market_analyzer.analyze(market_state)
            logger.info(f"📈 Analysis: trend={our_analysis.trend}, confidence={our_analysis.confidence:.2f}")
            
            # Account state
            account_state = self._get_account_state()
            if not account_state:
                logger.error("❌ Could not fetch account state")
                self.processed_ids.add(message_id)
                return
            
            logger.info(f"💰 Account: ${account_state.balance:,.2f}, {account_state.open_positions} positions")
            
            # Decision
            decision_result = self.decision_engine.evaluate_signal_entry(
                signal=signal,
                our_analysis=our_analysis,
                market_state=market_state,
                account_state=account_state
            )
            
            logger.info(f"🤖 Decision: {decision_result.decision.value} (confidence: {decision_result.confidence:.0%})")
            logger.info(f"   Reasoning: {decision_result.reasoning}")
            
            # Execute if approved
            if decision_result.should_execute():
                logger.info("✅ SIGNAL ACCEPTED - Would execute trade")
                logger.info(f"   Direction: {signal.direction}")
                logger.info(f"   Entry: {signal.entry_price}, SL: {signal.stop_loss}, TP: {signal.take_profit}")
                logger.info(f"   Size: {decision_result.action_params.get('position_size', 'N/A')}")
                
                # TODO: Execute via MT5
                # self.mt5.place_order(...)
            else:
                logger.info(f"❌ SIGNAL REJECTED: {decision_result.decision.value}")
            
            # Mark processed
            self.processed_ids.add(message_id)
        
        except Exception as e:
            logger.error(f"⛔ Error processing signal: {e}")
            import traceback
            traceback.print_exc()
            self.processed_ids.add(message_id)
    
    async def run(self):
        """Start listening to Telegram channels."""
        logger.info("\n🔄 Starting Telegram Signal Listener...")
        logger.info("   Press Ctrl+C to stop\n")
        
        await self.client.start()
        logger.info("✅ Connected to Telegram")
        
        # Register message handler
        @self.client.on(events.NewMessage(chats=self.signal_channels))
        async def handle_message(event):
            try:
                message_text = event.message.message
                message_id = event.message.id
                
                # Get channel name
                chat = await event.get_chat()
                channel_name = getattr(chat, 'title', str(chat.id))
                
                await self.process_signal(message_text, message_id, channel_name)
            
            except Exception as e:
                logger.error(f"⛔ Handler error: {e}")
        
        logger.info("📡 Listening for signals...")
        
        try:
            await self.client.run_until_disconnected()
        except KeyboardInterrupt:
            logger.info("\n⏹️  Listener stopped by user")
        finally:
            await self.client.disconnect()


if __name__ == '__main__':
    listener = TelegramSignalListener()
    asyncio.run(listener.run())
