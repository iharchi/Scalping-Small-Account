"""Shared fixtures for all tests."""

import sys
import os
from unittest.mock import MagicMock

# Ensure project root is on sys.path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub out libraries that may not build cleanly in CI.
# Both 'ta' (technical analysis) and 'alpaca' (broker SDK) are imported at
# module level. We mock them so tests run without network or native deps.

def _stub_modules(prefix, submodules):
    """Insert MagicMock stubs for a package and its submodules."""
    if prefix not in sys.modules:
        root = MagicMock()
        sys.modules[prefix] = root
        for sub in submodules:
            full = f"{prefix}.{sub}"
            sys.modules[full] = MagicMock()

_stub_modules("ta", ["volatility", "trend", "momentum"])
_stub_modules("alpaca", [
    "data", "data.historical", "data.requests", "data.timeframe",
    "trading", "trading.client", "trading.requests", "trading.enums",
])

import pandas as pd
import pytest


@pytest.fixture
def mock_broker():
    """A fully mocked AlpacaBroker with sane defaults."""
    broker = MagicMock()

    broker.get_account.return_value = {
        "cash": 500.0,
        "buying_power": 1000.0,
        "equity": 500.0,
        "portfolio_value": 500.0,
    }

    broker.get_latest_quote.return_value = {
        "bid": 9.95,
        "ask": 10.05,
        "mid": 10.00,
        "bid_size": 100,
        "ask_size": 200,
    }

    broker.get_asset.return_value = {
        "symbol": "TEST",
        "tradable": True,
        "shortable": True,
        "fractionable": False,
    }

    broker.is_market_open.return_value = True

    broker.buy_market.return_value = {
        "id": "buy-order-001",
        "symbol": "TEST",
        "qty": 10,
        "side": "buy",
        "type": "market",
        "status": "filled",
        "filled_avg_price": 10.00,
        "filled_qty": 10,
    }

    broker.sell_stop_limit.return_value = {
        "id": "stop-order-001",
        "symbol": "TEST",
        "qty": 10,
        "side": "sell",
        "type": "stop_limit",
        "status": "accepted",
        "stop_price": 9.50,
        "limit_price": 9.41,
    }

    broker.sell_limit.return_value = {
        "id": "target-order-001",
        "symbol": "TEST",
        "qty": 10,
        "side": "sell",
        "type": "limit",
        "status": "accepted",
        "limit_price": 11.00,
    }

    broker.get_order.return_value = {
        "id": "order-001",
        "status": "accepted",
        "filled_avg_price": None,
        "filled_qty": 0,
    }

    broker.cancel_order.return_value = True

    return broker


@pytest.fixture
def sample_daily_df():
    """10 days of daily bars — stock trading around $10 with a gap up."""
    dates = pd.date_range("2025-01-06", periods=10, freq="B")
    data = {
        "Open":   [9.0, 9.2, 9.5, 9.3, 9.8, 10.0, 10.2, 10.1, 10.5, 11.5],
        "High":   [9.3, 9.6, 9.8, 9.7, 10.1, 10.4, 10.5, 10.6, 11.0, 12.0],
        "Low":    [8.8, 9.0, 9.3, 9.1, 9.6, 9.8, 10.0, 9.9, 10.3, 11.2],
        "Close":  [9.1, 9.4, 9.6, 9.5, 9.9, 10.2, 10.3, 10.4, 10.8, 11.8],
        "Volume": [100_000, 120_000, 150_000, 130_000, 200_000,
                   180_000, 160_000, 170_000, 250_000, 2_000_000],
    }
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def sample_intraday_df():
    """100 one-minute bars during regular hours."""
    times = pd.date_range("2025-01-15 09:30", periods=100, freq="min")
    base = 10.0
    closes = [base + i * 0.02 for i in range(100)]
    data = {
        "Open":   [c - 0.01 for c in closes],
        "High":   [c + 0.03 for c in closes],
        "Low":    [c - 0.03 for c in closes],
        "Close":  closes,
        "Volume": [50_000 + i * 100 for i in range(100)],
    }
    return pd.DataFrame(data, index=times)
