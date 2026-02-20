"""Tests for risk_manager.py — position sizing, risk limits, order flow."""

import pytest

from risk_manager import RiskManager


class TestPositionSizing:
    """Test calculate_position_size()."""

    def test_basic_sizing(self):
        rm = RiskManager(account_size=500.0)
        # $500 account, 1% risk = $5 max risk
        # Entry $10, stop $9.50 = $0.50 risk per share
        # $5 / $0.50 = 10 shares
        shares = rm.calculate_position_size(10.0, 9.50)
        assert shares == 10

    def test_caps_at_affordable(self):
        rm = RiskManager(account_size=50.0)
        # $50 account, 1% risk = $0.50 max risk
        # Entry $10, stop $9.90 = $0.10 risk/share -> 5 shares
        # But max affordable = int(50 / 10) = 5
        shares = rm.calculate_position_size(10.0, 9.90)
        assert shares == 5

    def test_zero_risk_per_share(self):
        rm = RiskManager(account_size=500.0)
        assert rm.calculate_position_size(10.0, 10.0) == 0

    def test_negative_price(self):
        rm = RiskManager(account_size=500.0)
        assert rm.calculate_position_size(-1.0, 9.0) == 0
        assert rm.calculate_position_size(10.0, -1.0) == 0

    def test_zero_price(self):
        rm = RiskManager(account_size=500.0)
        assert rm.calculate_position_size(0.0, 9.0) == 0


class TestProfitTarget:
    """Test calculate_profit_target()."""

    def test_two_to_one_ratio(self):
        rm = RiskManager(account_size=500.0)
        # Entry $10, stop $9.50, risk = $0.50
        # Target = $10 + ($0.50 * 2) = $11.00
        target = rm.calculate_profit_target(10.0, 9.50)
        assert target == pytest.approx(11.00)

    def test_wide_stop(self):
        rm = RiskManager(account_size=500.0)
        # Entry $10, stop $8, risk = $2
        # Target = $10 + ($2 * 2) = $14
        target = rm.calculate_profit_target(10.0, 8.0)
        assert target == pytest.approx(14.0)


class TestCanTrade:
    """Test can_trade() gating logic."""

    def test_fresh_state_allows_trading(self):
        rm = RiskManager(account_size=500.0)
        can, reasons = rm.can_trade()
        assert can is True
        assert reasons == []

    def test_blocks_at_trade_limit(self):
        rm = RiskManager(account_size=500.0)
        rm.trades_today = rm.max_trades
        can, reasons = rm.can_trade()
        assert can is False
        assert any("Trade limit" in r for r in reasons)

    def test_blocks_at_daily_loss_limit(self):
        rm = RiskManager(account_size=500.0)
        # Max loss = 2% of $500 = $10
        rm.daily_pnl = -10.0
        can, reasons = rm.can_trade()
        assert can is False
        assert any("Daily loss" in r for r in reasons)

    def test_allows_positive_pnl(self):
        rm = RiskManager(account_size=500.0)
        rm.daily_pnl = 50.0  # Positive, should not block
        can, _ = rm.can_trade()
        assert can is True

    def test_blocks_with_open_position(self):
        rm = RiskManager(account_size=500.0)
        rm.open_position = {"symbol": "TEST"}
        can, reasons = rm.can_trade()
        assert can is False
        assert any("open position" in r for r in reasons)


class TestOpenTrade:
    """Test open_trade() with and without broker."""

    def test_without_broker(self):
        rm = RiskManager(account_size=500.0)
        pos = rm.open_trade("TEST", 10.0, 9.50, 10)

        assert pos["symbol"] == "TEST"
        assert pos["entry_price"] == 10.0
        assert pos["stop_loss"] == 9.50
        assert pos["shares"] == 10
        assert pos["buy_order_id"] is None
        assert rm.trades_today == 1

    def test_with_broker_places_orders(self, mock_broker):
        rm = RiskManager(broker=mock_broker, account_size=500.0)
        pos = rm.open_trade("TEST", 10.0, 9.50, 10)

        mock_broker.buy_market.assert_called_once_with("TEST", 10)
        mock_broker.sell_stop_limit.assert_called_once()
        mock_broker.sell_limit.assert_called_once()

        assert pos["buy_order_id"] == "buy-order-001"
        assert pos["stop_order_id"] == "stop-order-001"
        assert pos["target_order_id"] == "target-order-001"

    def test_uses_fill_price_from_broker(self, mock_broker):
        mock_broker.buy_market.return_value = {
            "id": "buy-001", "symbol": "TEST", "qty": 10,
            "side": "buy", "type": "market", "status": "filled",
            "filled_avg_price": 10.05, "filled_qty": 10,
        }
        rm = RiskManager(broker=mock_broker, account_size=500.0)
        pos = rm.open_trade("TEST", 10.0, 9.50, 10)

        # Entry should be updated to actual fill price
        assert pos["entry_price"] == 10.05


class TestCheckExitConditions:
    """Test exit detection — broker-based and price-based."""

    def test_no_position_returns_none(self):
        rm = RiskManager(account_size=500.0)
        assert rm.check_exit_conditions(10.0) is None

    def test_price_below_stop_triggers_exit(self):
        rm = RiskManager(account_size=500.0)
        rm.open_position = {
            "symbol": "TEST", "entry_price": 10.0,
            "stop_loss": 9.50, "profit_target": 11.0,
            "shares": 10, "risk": 5.0,
            "buy_order_id": None, "stop_order_id": None, "target_order_id": None,
        }
        result = rm.check_exit_conditions(9.40)
        assert result == ("stop_loss", 9.50)

    def test_price_above_target_triggers_exit(self):
        rm = RiskManager(account_size=500.0)
        rm.open_position = {
            "symbol": "TEST", "entry_price": 10.0,
            "stop_loss": 9.50, "profit_target": 11.0,
            "shares": 10, "risk": 5.0,
            "buy_order_id": None, "stop_order_id": None, "target_order_id": None,
        }
        result = rm.check_exit_conditions(11.50)
        assert result == ("profit_target", 11.0)

    def test_price_in_range_returns_none(self):
        rm = RiskManager(account_size=500.0)
        rm.open_position = {
            "symbol": "TEST", "entry_price": 10.0,
            "stop_loss": 9.50, "profit_target": 11.0,
            "shares": 10, "risk": 5.0,
            "buy_order_id": None, "stop_order_id": None, "target_order_id": None,
        }
        assert rm.check_exit_conditions(10.50) is None

    def test_broker_stop_filled_cancels_target(self, mock_broker):
        rm = RiskManager(broker=mock_broker, account_size=500.0)
        rm.open_position = {
            "symbol": "TEST", "entry_price": 10.0,
            "stop_loss": 9.50, "profit_target": 11.0,
            "shares": 10, "risk": 5.0,
            "buy_order_id": "buy-001",
            "stop_order_id": "stop-001",
            "target_order_id": "target-001",
        }
        mock_broker.get_order.return_value = {
            "id": "stop-001", "status": "filled",
            "filled_avg_price": 9.48, "filled_qty": 10,
        }

        result = rm.check_exit_conditions(9.40)

        assert result == ("stop_loss", 9.48)
        mock_broker.cancel_order.assert_called_once_with("target-001")

    def test_broker_target_filled_cancels_stop(self, mock_broker):
        rm = RiskManager(broker=mock_broker, account_size=500.0)
        rm.open_position = {
            "symbol": "TEST", "entry_price": 10.0,
            "stop_loss": 9.50, "profit_target": 11.0,
            "shares": 10, "risk": 5.0,
            "buy_order_id": "buy-001",
            "stop_order_id": "stop-001",
            "target_order_id": "target-001",
        }
        # Stop not filled, target filled
        def get_order_side_effect(order_id):
            if order_id == "stop-001":
                return {"id": "stop-001", "status": "accepted", "filled_avg_price": None, "filled_qty": 0}
            return {"id": "target-001", "status": "filled", "filled_avg_price": 11.02, "filled_qty": 10}

        mock_broker.get_order.side_effect = get_order_side_effect

        result = rm.check_exit_conditions(11.00)

        assert result == ("profit_target", 11.02)
        mock_broker.cancel_order.assert_called_once_with("stop-001")


class TestCloseTrade:
    """Test close_trade() P&L accounting."""

    def test_winning_trade(self):
        rm = RiskManager(account_size=500.0)
        rm.open_position = {
            "symbol": "TEST", "entry_price": 10.0,
            "stop_loss": 9.50, "profit_target": 11.0,
            "shares": 10, "risk": 5.0,
            "buy_order_id": None, "stop_order_id": None, "target_order_id": None,
        }
        record = rm.close_trade(11.0)

        assert record["pnl"] == pytest.approx(10.0)  # ($11 - $10) * 10
        assert record["exit_price"] == 11.0
        assert rm.daily_pnl == pytest.approx(10.0)
        assert rm.account_size == pytest.approx(510.0)
        assert rm.open_position is None

    def test_losing_trade(self):
        rm = RiskManager(account_size=500.0)
        rm.open_position = {
            "symbol": "TEST", "entry_price": 10.0,
            "stop_loss": 9.50, "profit_target": 11.0,
            "shares": 10, "risk": 5.0,
            "buy_order_id": None, "stop_order_id": None, "target_order_id": None,
        }
        record = rm.close_trade(9.50)

        assert record["pnl"] == pytest.approx(-5.0)  # ($9.50 - $10) * 10
        assert rm.account_size == pytest.approx(495.0)

    def test_no_position_returns_none(self):
        rm = RiskManager(account_size=500.0)
        assert rm.close_trade(10.0) is None

    def test_syncs_account_after_close(self, mock_broker):
        rm = RiskManager(broker=mock_broker, account_size=500.0)
        rm.open_position = {
            "symbol": "TEST", "entry_price": 10.0,
            "stop_loss": 9.50, "profit_target": 11.0,
            "shares": 10, "risk": 5.0,
            "buy_order_id": None, "stop_order_id": None, "target_order_id": None,
        }
        rm.close_trade(11.0)

        # get_account called once in __init__ and once in sync_account
        assert mock_broker.get_account.call_count == 2


class TestResetDaily:
    """Test daily reset."""

    def test_resets_all_counters(self):
        rm = RiskManager(account_size=500.0)
        rm.daily_pnl = -5.0
        rm.trades_today = 3
        rm.open_position = {"symbol": "TEST"}

        rm.reset_daily()

        assert rm.daily_pnl == 0.0
        assert rm.trades_today == 0
        assert rm.open_position is None


class TestInitWithBroker:
    """Test RiskManager init pulls equity from broker."""

    def test_syncs_equity_from_broker(self, mock_broker):
        mock_broker.get_account.return_value = {
            "cash": 750.0, "buying_power": 1500.0,
            "equity": 750.0, "portfolio_value": 750.0,
        }
        rm = RiskManager(broker=mock_broker)
        assert rm.account_size == 750.0

    def test_explicit_size_overrides_broker(self, mock_broker):
        rm = RiskManager(broker=mock_broker, account_size=300.0)
        assert rm.account_size == 300.0
