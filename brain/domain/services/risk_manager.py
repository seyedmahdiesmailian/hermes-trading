"""Risk Manager — Risk management service.

Handles all risk-related decisions and calculations.
"""

from brain.domain.value_objects.risk import RiskParameters
from brain.domain.entities.account import AccountState


class RiskManager:
    """Risk management service.
    
    Enforces risk rules and calculates position sizes.
    Acts as a gatekeeper for all trading decisions.
    
    Usage:
        params = RiskParameters(max_risk_per_trade_pct=0.02)
        risk_manager = RiskManager(params)
        
        if risk_manager.check_risk(account_state):
            size = risk_manager.calculate_position_size(...)
    """
    
    def __init__(self, params: RiskParameters):
        self.params = params
    
    def check_risk(self, account: AccountState) -> bool:
        """Check if new trade is allowed under risk rules.
        
        Checks:
        1. Daily loss limit
        2. Max open positions
        3. Max daily trades
        
        Args:
            account: Current account state
            
        Returns:
            True if trade is allowed, False otherwise
        """
        # 1. Daily loss limit
        max_daily_loss = account.balance * self.params.max_daily_loss_pct
        if account.daily_pnl < -max_daily_loss:
            return False
        
        # 2. Max positions
        if account.open_positions >= self.params.max_open_positions:
            return False
        
        # 3. Max daily trades
        if account.daily_trades >= self.params.max_daily_trades:
            return False
        
        return True
    
    def calculate_position_size(
        self,
        account: AccountState,
        entry_price: float,
        stop_loss: float
    ) -> float:
        """Calculate position size based on risk.
        
        Uses fixed percentage risk per trade.
        
        Args:
            account: Account state
            entry_price: Planned entry price
            stop_loss: Planned stop loss
            
        Returns:
            Position size in lots
        """
        # Risk amount in currency
        risk_amount = account.balance * self.params.max_risk_per_trade_pct
        
        # Risk per lot (in points)
        risk_per_lot = abs(entry_price - stop_loss)
        
        if risk_per_lot <= 0:
            return 0.0
        
        # Calculate size
        position_size = risk_amount / risk_per_lot
        
        # Clamp to limits
        position_size = max(0.01, position_size)  # Min 0.01 lots
        position_size = min(self.params.max_position_size_lots, position_size)
        
        # Round to 2 decimals
        return round(position_size, 2)
    
    def validate_trade_params(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float
    ) -> tuple[bool, str]:
        """Validate trade parameters against risk rules.
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss
            take_profit: Take profit
            
        Returns:
            (is_valid, error_message)
        """
        # Check SL distance
        sl_distance = abs(entry_price - stop_loss)
        
        if sl_distance < self.params.min_stop_loss_points:
            return False, f"SL too close: {sl_distance:.1f} < {self.params.min_stop_loss_points}"
        
        if sl_distance > self.params.max_stop_loss_points:
            return False, f"SL too far: {sl_distance:.1f} > {self.params.max_stop_loss_points}"
        
        # Check RR ratio
        tp_distance = abs(take_profit - entry_price)
        rr_ratio = tp_distance / sl_distance if sl_distance > 0 else 0
        
        if rr_ratio < self.params.min_risk_reward:
            return False, f"RR too low: {rr_ratio:.1f} < {self.params.min_risk_reward}"
        
        return True, "OK"
    
    def get_daily_risk_used(self, account: AccountState) -> float:
        """Calculate how much of daily risk budget is used.
        
        Returns:
            Percentage (0.0 to 1.0)
        """
        max_loss = account.balance * self.params.max_daily_loss_pct
        if max_loss == 0:
            return 0.0
        
        # If profitable, no risk used
        if account.daily_pnl >= 0:
            return 0.0
        
        return abs(account.daily_pnl) / max_loss
    
    def should_reduce_risk(self, account: AccountState) -> bool:
        """Check if risk should be reduced (losing streak).
        
        Returns:
            True if risk should be reduced
        """
        # Reduce risk if:
        # 1. More than 50% of daily risk used
        # 2. Win rate below 40%
        
        risk_used = self.get_daily_risk_used(account)
        if risk_used > 0.5:
            return True
        
        win_rate = account.win_rate_today()
        if win_rate < 0.4 and (account.daily_wins + account.daily_losses) >= 3:
            return True
        
        return False
    
    def __repr__(self) -> str:
        return f"RiskManager({self.params})"
