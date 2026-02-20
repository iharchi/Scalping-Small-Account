"""Tests for pipeline.py — TradingPipeline orchestration."""

import time
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from pipeline import TradingPipeline


@pytest.fixture
def pipeline(mock_broker):
    """A pipeline with mocked broker and auto-checklist."""
    return TradingPipeline(broker=mock_broker, account_size=500.0, auto_checklist=True)


class TestInit:
    """Test pipeline initialization."""

    def test_creates_risk_manager(self, pipeline):
        assert pipeline.risk_manager is not None
        assert pipeline.risk_manager.account_size == 500.0

    def test_initial_state(self, pipeline):
        assert pipeline.running is False
        assert pipeline.trade_log == []
        assert pipeline._cycle_count == 0


class TestRefreshScan:
    """Test scan caching logic."""

    @patch("pipeline.scan_watchlist", return_value=[])
    @patch("pipeline.print_scan_results")
    def test_calls_scanner(self, mock_print, mock_scan, pipeline):
        pipeline._refresh_scan(["AAPL"])
        mock_scan.assert_called_once_with(pipeline.broker, ["AAPL"])

    @patch("pipeline.scan_watchlist", return_value=[{"symbol": "AAPL", "relative_volume": 5.0}])
    @patch("pipeline.print_scan_results")
    @patch("pipeline.get_daily_data")
    def test_caches_within_interval(self, mock_daily, mock_print, mock_scan, pipeline):
        mock_daily.return_value = None

        # First call should hit scanner
        pipeline._refresh_scan(["AAPL"])
        assert mock_scan.call_count == 1

        # Second call within interval should use cache
        pipeline._refresh_scan(["AAPL"])
        assert mock_scan.call_count == 1  # Not called again


class TestRunCycle:
    """Test _run_cycle() behavior."""

    def test_monitors_open_position(self, pipeline, mock_broker):
        pipeline.risk_manager.open_position = {
            "symbol": "TEST", "entry_price": 10.0,
            "stop_loss": 9.50, "profit_target": 11.0,
            "shares": 10, "risk": 5.0,
            "buy_order_id": "b1", "stop_order_id": "s1", "target_order_id": "t1",
        }
        # Order not filled yet
        mock_broker.get_order.return_value = {
            "id": "s1", "status": "accepted",
            "filled_avg_price": None, "filled_qty": 0,
        }
        mock_broker.get_latest_quote.return_value = {
            "bid": 9.95, "ask": 10.05, "mid": 10.00,
            "bid_size": 100, "ask_size": 200,
        }

        signals = pipeline._run_cycle(["TEST"])

        assert signals == []
        assert pipeline._cycle_count == 1

    @patch("pipeline.scan_watchlist", return_value=[])
    @patch("pipeline.print_scan_results")
    def test_respects_can_trade_gating(self, mock_print, mock_scan, pipeline):
        pipeline.risk_manager.trades_today = pipeline.risk_manager.max_trades

        signals = pipeline._run_cycle(["AAPL"])
        assert signals == []
        mock_scan.assert_not_called()

    @patch("pipeline.scan_watchlist", return_value=[])
    @patch("pipeline.print_scan_results")
    def test_no_signals_when_no_scan_results(self, mock_print, mock_scan, pipeline):
        signals = pipeline._run_cycle(["AAPL"])
        assert signals == []


class TestCheckOpenPosition:
    """Test _check_open_position() exit handling."""

    def test_stop_loss_exit(self, pipeline, mock_broker):
        pipeline.risk_manager.open_position = {
            "symbol": "TEST", "entry_price": 10.0,
            "stop_loss": 9.50, "profit_target": 11.0,
            "shares": 10, "risk": 5.0,
            "buy_order_id": "b1", "stop_order_id": "s1", "target_order_id": "t1",
        }
        mock_broker.get_order.return_value = {
            "id": "s1", "status": "filled",
            "filled_avg_price": 9.48, "filled_qty": 10,
        }
        mock_broker.get_latest_quote.return_value = {
            "bid": 9.45, "ask": 9.55, "mid": 9.50,
            "bid_size": 100, "ask_size": 200,
        }

        record = pipeline._check_open_position()

        assert record is not None
        assert record["pnl"] < 0
        assert len(pipeline.trade_log) == 1

    def test_no_position_returns_none(self, pipeline):
        assert pipeline._check_open_position() is None


class TestRun:
    """Test one-shot run() method."""

    @patch("pipeline.run_checklist", return_value=False)
    def test_stops_on_failed_checklist(self, mock_checklist, pipeline):
        result = pipeline.run(["AAPL"])
        assert result == []

    @patch("pipeline.run_checklist", return_value=True)
    @patch("pipeline.scan_watchlist", return_value=[])
    @patch("pipeline.print_scan_results")
    def test_returns_empty_on_no_stocks(self, mock_print, mock_scan, mock_checklist, pipeline):
        result = pipeline.run(["AAPL"])
        assert result == []
