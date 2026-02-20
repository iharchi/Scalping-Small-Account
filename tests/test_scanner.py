"""Tests for scanner.py — stock screening and data helpers."""

import pandas as pd
import pytest

from scanner import check_criteria, scan_watchlist, get_stock_data, get_daily_data, get_latest_price


class TestGetStockData:
    """Test get_stock_data wrapper."""

    def test_delegates_to_broker(self, mock_broker, sample_intraday_df):
        mock_broker.get_bars.return_value = sample_intraday_df
        result = get_stock_data(mock_broker, "TEST")
        mock_broker.get_bars.assert_called_once_with("TEST", timeframe="1min", limit=100)
        assert len(result) == 100

    def test_returns_none_on_exception(self, mock_broker):
        mock_broker.get_bars.side_effect = Exception("API error")
        assert get_stock_data(mock_broker, "TEST") is None


class TestGetDailyData:
    """Test get_daily_data wrapper."""

    def test_delegates_to_broker(self, mock_broker, sample_daily_df):
        mock_broker.get_daily_bars.return_value = sample_daily_df
        result = get_daily_data(mock_broker, "TEST", limit=10)
        mock_broker.get_daily_bars.assert_called_once_with("TEST", limit=10)
        assert len(result) == 10

    def test_returns_none_on_exception(self, mock_broker):
        mock_broker.get_daily_bars.side_effect = Exception("timeout")
        assert get_daily_data(mock_broker, "TEST") is None


class TestGetLatestPrice:
    """Test get_latest_price helper."""

    def test_returns_mid_price(self, mock_broker):
        result = get_latest_price(mock_broker, "TEST")
        assert result == 10.00

    def test_returns_none_on_no_quote(self, mock_broker):
        mock_broker.get_latest_quote.return_value = None
        assert get_latest_price(mock_broker, "TEST") is None

    def test_returns_none_on_exception(self, mock_broker):
        mock_broker.get_latest_quote.side_effect = Exception("error")
        assert get_latest_price(mock_broker, "TEST") is None


class TestCheckCriteria:
    """Test check_criteria() filtering logic."""

    def _make_daily(self, prev_close, today_close, today_volume, avg_volume):
        """Helper to build a minimal daily DataFrame."""
        dates = pd.date_range("2025-01-14", periods=5, freq="B")
        data = {
            "Open":   [prev_close] * 4 + [today_close],
            "High":   [prev_close + 0.5] * 4 + [today_close + 0.5],
            "Low":    [prev_close - 0.5] * 4 + [today_close - 0.5],
            "Close":  [prev_close] * 4 + [today_close],
            "Volume": [avg_volume] * 4 + [today_volume],
        }
        return pd.DataFrame(data, index=dates)

    def test_stock_passes_all_criteria(self, mock_broker):
        # Price $10, gap 10%, rvol 5x, tradable
        daily = self._make_daily(
            prev_close=9.09, today_close=10.0,
            today_volume=2_000_000, avg_volume=400_000,
        )
        mock_broker.get_daily_bars.return_value = daily

        result = check_criteria(mock_broker, "TEST")

        assert result is not None
        assert result["passes"] is True
        assert result["reasons"] == []

    def test_fails_price_too_high(self, mock_broker):
        daily = self._make_daily(
            prev_close=22.73, today_close=25.0,
            today_volume=2_000_000, avg_volume=400_000,
        )
        mock_broker.get_daily_bars.return_value = daily

        result = check_criteria(mock_broker, "TEST")
        assert result["passes"] is False
        assert any("Price" in r for r in result["reasons"])

    def test_fails_volume_too_low(self, mock_broker):
        daily = self._make_daily(
            prev_close=9.09, today_close=10.0,
            today_volume=100_000, avg_volume=50_000,
        )
        mock_broker.get_daily_bars.return_value = daily

        result = check_criteria(mock_broker, "TEST")
        assert result["passes"] is False
        assert any("Volume" in r for r in result["reasons"])

    def test_fails_gap_too_small(self, mock_broker):
        daily = self._make_daily(
            prev_close=9.95, today_close=10.0,
            today_volume=2_000_000, avg_volume=400_000,
        )
        mock_broker.get_daily_bars.return_value = daily

        result = check_criteria(mock_broker, "TEST")
        assert result["passes"] is False
        assert any("Gap" in r for r in result["reasons"])

    def test_fails_not_tradable(self, mock_broker):
        daily = self._make_daily(
            prev_close=9.09, today_close=10.0,
            today_volume=2_000_000, avg_volume=400_000,
        )
        mock_broker.get_daily_bars.return_value = daily
        mock_broker.get_asset.return_value = {"symbol": "TEST", "tradable": False, "shortable": False, "fractionable": False}

        result = check_criteria(mock_broker, "TEST")
        assert result["passes"] is False
        assert any("Not tradable" in r for r in result["reasons"])

    def test_returns_none_on_insufficient_data(self, mock_broker):
        # Only 1 row — need at least 2
        dates = pd.date_range("2025-01-15", periods=1, freq="B")
        daily = pd.DataFrame({
            "Open": [10.0], "High": [10.5], "Low": [9.5],
            "Close": [10.2], "Volume": [1_000_000],
        }, index=dates)
        mock_broker.get_daily_bars.return_value = daily

        assert check_criteria(mock_broker, "TEST") is None

    def test_returns_none_on_no_data(self, mock_broker):
        mock_broker.get_daily_bars.return_value = None
        assert check_criteria(mock_broker, "TEST") is None


class TestScanWatchlist:
    """Test scan_watchlist() filtering and sorting."""

    def _make_daily_passing(self, prev_close, today_close, today_volume, avg_volume):
        dates = pd.date_range("2025-01-14", periods=5, freq="B")
        data = {
            "Open":   [prev_close] * 4 + [today_close],
            "High":   [prev_close + 0.5] * 4 + [today_close + 0.5],
            "Low":    [prev_close - 0.5] * 4 + [today_close - 0.5],
            "Close":  [prev_close] * 4 + [today_close],
            "Volume": [avg_volume] * 4 + [today_volume],
        }
        return pd.DataFrame(data, index=dates)

    def test_filters_and_sorts_by_rvol(self, mock_broker):
        # Stock A: rvol 5x, Stock B: rvol 10x
        daily_a = self._make_daily_passing(9.09, 10.0, 2_000_000, 400_000)
        daily_b = self._make_daily_passing(9.09, 10.0, 4_000_000, 400_000)

        def get_daily(symbol, limit=30):
            return daily_a if symbol == "A" else daily_b

        mock_broker.get_daily_bars.side_effect = get_daily

        results = scan_watchlist(mock_broker, ["A", "B"])

        assert len(results) == 2
        # B has higher rvol, should come first
        assert results[0]["symbol"] == "B"
        assert results[1]["symbol"] == "A"

    def test_excludes_failing_stocks(self, mock_broker):
        mock_broker.get_daily_bars.return_value = None  # No data
        results = scan_watchlist(mock_broker, ["FAKE"])
        assert results == []
