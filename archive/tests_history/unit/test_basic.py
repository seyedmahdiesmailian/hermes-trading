"""Simple unit tests."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))

def test_imports():
    """Test that core modules can be imported."""
    from brain.domain.entities.account import AccountState
    from brain.domain.services.risk_manager import RiskManager
    assert AccountState is not None
    assert RiskManager is not None

def test_account_state():
    """Test AccountState creation."""
    from brain.domain.entities.account import AccountState
    
    account = AccountState(
        balance=5000.0,
        equity=5000.0,
        margin_free=5000.0
    )
    assert account.balance == 5000.0

def test_risk_manager():
    """Test RiskManager."""
    from brain.domain.services.risk_manager import RiskManager
    from brain.domain.entities.account import AccountState
    
    rm = RiskManager()
    account = AccountState(balance=5000.0, equity=5000.0, margin_free=5000.0)
    result = rm.check_risk(account)
    assert result is not None
