"""tests/conftest.py — Global fixtures for Hermes Trading test suite.

Guarantees 100% isolation so running tests never emits network calls,
Telegram messages, or modifies live databases.
"""
import pytest
from unittest.mock import patch

@pytest.fixture(autouse=True)
def prevent_real_telegram_in_tests():
    """قفل قطعی ارسال پیام تلگرام در حین اجرای تست‌های pytest."""
    with patch("adapters.notify.NotifyAdapter.send", return_value=True):
        yield
