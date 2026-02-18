"""
Risk Manager for the Small Account Scalping Pipeline.

Enforces strict risk management rules:
  - Max risk per trade (% of account)
  - Max daily loss limit
  - Position sizing based on stop distance
  - Trade count limits
"""

import config


class RiskManager:
    """Manages risk for a small trading account."""

    def __init__(self, account_size=None):
        self.account_size = account_size or config.ACCOUNT_SIZE
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.max_trades = config.MAX_TRADES_PER_DAY
        self.open_position = None

    @property
    def max_risk_per_trade(self):
        """Maximum dollar risk per trade."""
        return self.account_size * (config.MAX_RISK_PER_TRADE_PCT / 100)

    @property
    def max_daily_loss(self):
        """Maximum daily loss in dollars."""
        return self.account_size * (config.MAX_LOSS_PER_DAY_PCT / 100)

    def can_trade(self):
        """Check if we are allowed to take another trade."""
        reasons = []

        if self.trades_today >= self.max_trades:
            reasons.append(f"Trade limit reached ({self.trades_today}/{self.max_trades})")

        if abs(self.daily_pnl) >= self.max_daily_loss and self.daily_pnl < 0:
            reasons.append(f"Daily loss limit reached (${self.daily_pnl:.2f})")

        if self.open_position is not None:
            reasons.append("Already have an open position")

        if reasons:
            return False, reasons
        return True, []

    def calculate_position_size(self, entry_price, stop_loss_price):
        """
        Calculate the number of shares based on risk.

        Position size = Max Risk / (Entry - Stop Loss)
        This ensures we never risk more than our max per trade.
        """
        if entry_price <= 0 or stop_loss_price <= 0:
            return 0

        risk_per_share = abs(entry_price - stop_loss_price)

        if risk_per_share == 0:
            return 0

        shares = int(self.max_risk_per_trade / risk_per_share)

        # Make sure we can afford the position
        max_affordable = int(self.account_size / entry_price)
        shares = min(shares, max_affordable)

        return max(shares, 0)

    def calculate_profit_target(self, entry_price, stop_loss_price):
        """
        Calculate profit target based on risk/reward ratio.

        Default is 2:1 reward to risk.
        """
        risk = abs(entry_price - stop_loss_price)
        target = entry_price + (risk * config.PROFIT_TARGET_RATIO)
        return target

    def open_trade(self, symbol, entry_price, stop_loss_price, shares):
        """Record a new open position."""
        self.open_position = {
            "symbol": symbol,
            "entry_price": entry_price,
            "stop_loss": stop_loss_price,
            "profit_target": self.calculate_profit_target(entry_price, stop_loss_price),
            "shares": shares,
            "risk": abs(entry_price - stop_loss_price) * shares,
        }
        self.trades_today += 1
        return self.open_position

    def close_trade(self, exit_price):
        """Close the current position and record P&L."""
        if self.open_position is None:
            return None

        pnl = (exit_price - self.open_position["entry_price"]) * self.open_position["shares"]
        self.daily_pnl += pnl

        trade_record = {
            **self.open_position,
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_pct": (pnl / self.account_size) * 100,
        }

        self.account_size += pnl
        self.open_position = None

        return trade_record

    def check_exit_conditions(self, current_price):
        """
        Check if the current price hits stop loss or profit target.

        Returns:
            ("stop_loss", price), ("profit_target", price), or None.
        """
        if self.open_position is None:
            return None

        if current_price <= self.open_position["stop_loss"]:
            return "stop_loss", self.open_position["stop_loss"]

        if current_price >= self.open_position["profit_target"]:
            return "profit_target", self.open_position["profit_target"]

        return None

    def get_status(self):
        """Return current risk manager status."""
        return {
            "account_size": self.account_size,
            "daily_pnl": self.daily_pnl,
            "trades_today": self.trades_today,
            "max_trades": self.max_trades,
            "has_open_position": self.open_position is not None,
            "can_trade": self.can_trade()[0],
        }

    def print_status(self):
        """Pretty-print the current status."""
        status = self.get_status()
        print(f"\n{'='*40}")
        print(f"  Account Size:   ${status['account_size']:,.2f}")
        print(f"  Daily P&L:      ${status['daily_pnl']:+,.2f}")
        print(f"  Trades Today:   {status['trades_today']}/{status['max_trades']}")
        print(f"  Open Position:  {'Yes' if status['has_open_position'] else 'No'}")
        print(f"  Can Trade:      {'Yes' if status['can_trade'] else 'No'}")
        print(f"{'='*40}\n")

    def reset_daily(self):
        """Reset daily counters (call at start of each trading day)."""
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.open_position = None
