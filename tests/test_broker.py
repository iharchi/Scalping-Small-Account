"""Tests for broker.py — Alpaca API wrapper.

conftest.py stubs the alpaca.* modules, so broker.py can be imported
without the real SDK. We test AlpacaBroker by swapping its internal
trading_client / data_client with mocks after construction.
"""

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _make_broker(api_key="test-key", secret_key="test-secret"):
    """Create an AlpacaBroker with env vars set, then mock its clients."""
    with patch.dict("os.environ", {
        "ALPACA_API_KEY": api_key,
        "ALPACA_SECRET_KEY": secret_key,
    }):
        import config
        importlib.reload(config)
        from broker import AlpacaBroker
        broker = AlpacaBroker()

    broker.trading_client = MagicMock()
    broker.data_client = MagicMock()
    return broker


class TestAlpacaBrokerInit:

    def test_raises_without_credentials(self):
        with patch.dict("os.environ", {"ALPACA_API_KEY": "", "ALPACA_SECRET_KEY": ""}):
            import config
            importlib.reload(config)
            from broker import AlpacaBroker
            with pytest.raises(ValueError, match="ALPACA_API_KEY"):
                AlpacaBroker()

    def test_creates_with_valid_keys(self):
        broker = _make_broker()
        assert broker is not None


class TestGetAccount:

    def test_returns_correct_shape(self):
        broker = _make_broker()
        broker.trading_client.get_account.return_value = SimpleNamespace(
            cash="1000.00", buying_power="2000.00",
            equity="1500.00", portfolio_value="1500.00",
        )
        result = broker.get_account()
        assert result == {
            "cash": 1000.0,
            "buying_power": 2000.0,
            "equity": 1500.0,
            "portfolio_value": 1500.0,
        }


class TestGetBars:

    def test_returns_dataframe(self):
        broker = _make_broker()
        bar = SimpleNamespace(
            open=10.0, high=10.5, low=9.8, close=10.2,
            volume=100000, timestamp="2025-01-15T10:00:00Z",
        )
        broker.data_client.get_stock_bars.return_value = {"AAPL": [bar]}

        df = broker.get_bars("AAPL")
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert len(df) == 1
        assert df["Close"].iloc[0] == 10.2

    def test_returns_none_for_empty_response(self):
        broker = _make_broker()
        broker.data_client.get_stock_bars.return_value = {}
        assert broker.get_bars("AAPL") is None

    def test_returns_none_when_symbol_missing(self):
        broker = _make_broker()
        broker.data_client.get_stock_bars.return_value = {"OTHER": []}
        assert broker.get_bars("AAPL") is None

    def test_daily_bars_delegates(self):
        broker = _make_broker()
        bar = SimpleNamespace(
            open=10.0, high=10.5, low=9.8, close=10.2,
            volume=100000, timestamp="2025-01-15",
        )
        broker.data_client.get_stock_bars.return_value = {"AAPL": [bar]}

        df = broker.get_daily_bars("AAPL", limit=5)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1


class TestGetLatestQuote:

    def test_computes_mid_correctly(self):
        broker = _make_broker()
        quote = SimpleNamespace(bid_price=9.90, ask_price=10.10, bid_size=100, ask_size=200)
        broker.data_client.get_stock_latest_quote.return_value = {"AAPL": quote}

        result = broker.get_latest_quote("AAPL")
        assert result["bid"] == 9.90
        assert result["ask"] == 10.10
        assert result["mid"] == pytest.approx(10.00)

    def test_returns_none_when_missing(self):
        broker = _make_broker()
        broker.data_client.get_stock_latest_quote.return_value = {}
        assert broker.get_latest_quote("AAPL") is None


class TestGetAsset:

    def test_returns_asset_info(self):
        broker = _make_broker()
        asset = SimpleNamespace(symbol="AAPL", tradable=True, shortable=True, fractionable=True)
        broker.trading_client.get_asset.return_value = asset

        result = broker.get_asset("AAPL")
        assert result["symbol"] == "AAPL"
        assert result["tradable"] is True

    def test_returns_none_on_exception(self):
        broker = _make_broker()
        broker.trading_client.get_asset.side_effect = Exception("not found")
        assert broker.get_asset("FAKE") is None


class TestOrders:

    def test_buy_market(self):
        broker = _make_broker()
        order = SimpleNamespace(
            id="ord-123", symbol="AAPL", qty=10, side="buy",
            type="market", status="filled", filled_avg_price=10.05, filled_qty=10,
        )
        broker.trading_client.submit_order.return_value = order

        result = broker.buy_market("AAPL", 10)
        assert result["id"] == "ord-123"
        assert result["status"] == "filled"
        assert result["filled_avg_price"] == 10.05

    def test_sell_stop_limit(self):
        broker = _make_broker()
        order = SimpleNamespace(
            id="ord-456", symbol="AAPL", qty=10, side="sell",
            type="stop_limit", status="accepted", stop_price=9.50, limit_price=9.40,
        )
        broker.trading_client.submit_order.return_value = order

        result = broker.sell_stop_limit("AAPL", 10, 9.50, 9.40)
        assert result["id"] == "ord-456"
        assert result["stop_price"] == 9.50
        assert result["limit_price"] == 9.40

    def test_sell_limit(self):
        broker = _make_broker()
        order = SimpleNamespace(
            id="ord-789", symbol="AAPL", qty=10, side="sell",
            type="limit", status="accepted", limit_price=11.00,
        )
        broker.trading_client.submit_order.return_value = order

        result = broker.sell_limit("AAPL", 10, 11.00)
        assert result["id"] == "ord-789"
        assert result["limit_price"] == 11.00

    def test_get_order(self):
        broker = _make_broker()
        order = SimpleNamespace(
            id="ord-123", status="filled", filled_avg_price=10.05, filled_qty=10,
        )
        broker.trading_client.get_order_by_id.return_value = order

        result = broker.get_order("ord-123")
        assert result["status"] == "filled"
        assert result["filled_avg_price"] == 10.05

    def test_cancel_order_success(self):
        broker = _make_broker()
        assert broker.cancel_order("ord-123") is True

    def test_cancel_order_failure(self):
        broker = _make_broker()
        broker.trading_client.cancel_order_by_id.side_effect = Exception("not found")
        assert broker.cancel_order("ord-999") is False


class TestMarketStatus:

    def test_market_open(self):
        broker = _make_broker()
        broker.trading_client.get_clock.return_value = SimpleNamespace(is_open=True)
        assert broker.is_market_open() is True

    def test_market_closed(self):
        broker = _make_broker()
        broker.trading_client.get_clock.return_value = SimpleNamespace(is_open=False)
        assert broker.is_market_open() is False
