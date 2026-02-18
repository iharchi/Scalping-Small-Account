"""
Alpaca Broker Integration for the Small Account Scalping Pipeline.

Wraps the Alpaca API for:
  - Market data (bars, quotes)
  - Order execution (market buy, stop-limit sell, limit sell)
  - Position and account monitoring
"""

from datetime import datetime, timedelta

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopLimitOrderRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus

import config


class AlpacaBroker:
    """Wraps Alpaca REST API for data + trading."""

    def __init__(self):
        if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
            raise ValueError(
                "Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables."
            )

        self.trading_client = TradingClient(
            config.ALPACA_API_KEY,
            config.ALPACA_SECRET_KEY,
            paper=config.ALPACA_PAPER,
        )
        self.data_client = StockHistoricalDataClient(
            config.ALPACA_API_KEY,
            config.ALPACA_SECRET_KEY,
        )

    # ── Account ──────────────────────────────────────────────

    def get_account(self):
        """Return account info (cash, buying power, equity)."""
        acct = self.trading_client.get_account()
        return {
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "equity": float(acct.equity),
            "portfolio_value": float(acct.portfolio_value),
        }

    def get_positions(self):
        """Return all open positions."""
        positions = self.trading_client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": int(p.qty),
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pnl": float(p.unrealized_pl),
                "market_value": float(p.market_value),
            }
            for p in positions
        ]

    # ── Market Data ──────────────────────────────────────────

    def get_bars(self, symbol, timeframe="1min", limit=100):
        """
        Fetch historical bars for a symbol.

        Returns a pandas DataFrame with columns: Open, High, Low, Close, Volume.
        """
        tf = TimeFrame.Minute if timeframe == "1min" else TimeFrame.Day
        start = datetime.now() - timedelta(days=5 if tf == TimeFrame.Day else 1)

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start,
            limit=limit,
        )

        bars = self.data_client.get_stock_bars(request)

        if not bars or symbol not in bars:
            return None

        records = []
        for bar in bars[symbol]:
            records.append({
                "Open": bar.open,
                "High": bar.high,
                "Low": bar.low,
                "Close": bar.close,
                "Volume": bar.volume,
                "Timestamp": bar.timestamp,
            })

        if not records:
            return None

        df = pd.DataFrame(records)
        df.set_index("Timestamp", inplace=True)
        df.index = pd.to_datetime(df.index)
        return df

    def get_daily_bars(self, symbol, limit=30):
        """Fetch daily bars."""
        return self.get_bars(symbol, timeframe="1day", limit=limit)

    def get_latest_quote(self, symbol):
        """
        Get the latest bid/ask quote for a symbol.

        Returns dict with bid, ask, mid prices.
        """
        request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quotes = self.data_client.get_stock_latest_quote(request)

        if symbol not in quotes:
            return None

        q = quotes[symbol]
        bid = float(q.bid_price)
        ask = float(q.ask_price)
        return {
            "bid": bid,
            "ask": ask,
            "mid": (bid + ask) / 2,
            "bid_size": q.bid_size,
            "ask_size": q.ask_size,
        }

    def get_asset(self, symbol):
        """Check if a symbol is tradable on Alpaca."""
        try:
            asset = self.trading_client.get_asset(symbol)
            return {
                "symbol": asset.symbol,
                "tradable": asset.tradable,
                "shortable": asset.shortable,
                "fractionable": asset.fractionable,
            }
        except Exception:
            return None

    # ── Orders ───────────────────────────────────────────────

    def buy_market(self, symbol, qty):
        """
        Place a market buy order.

        Returns the order object.
        """
        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = self.trading_client.submit_order(request)
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": int(order.qty),
            "side": str(order.side),
            "type": str(order.type),
            "status": str(order.status),
            "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
            "filled_qty": int(order.filled_qty) if order.filled_qty else 0,
        }

    def sell_stop_limit(self, symbol, qty, stop_price, limit_price):
        """
        Place a stop-limit sell order (for stop loss).

        Triggers at stop_price, fills at limit_price or better.
        """
        request = StopLimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            stop_price=round(stop_price, 2),
            limit_price=round(limit_price, 2),
        )
        order = self.trading_client.submit_order(request)
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": int(order.qty),
            "side": str(order.side),
            "type": str(order.type),
            "status": str(order.status),
            "stop_price": float(order.stop_price) if order.stop_price else None,
            "limit_price": float(order.limit_price) if order.limit_price else None,
        }

    def sell_limit(self, symbol, qty, limit_price):
        """
        Place a limit sell order (for profit target).
        """
        request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            limit_price=round(limit_price, 2),
        )
        order = self.trading_client.submit_order(request)
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": int(order.qty),
            "side": str(order.side),
            "type": str(order.type),
            "status": str(order.status),
            "limit_price": float(order.limit_price) if order.limit_price else None,
        }

    def get_order(self, order_id):
        """Get current status of an order."""
        order = self.trading_client.get_order_by_id(order_id)
        return {
            "id": str(order.id),
            "status": str(order.status),
            "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
            "filled_qty": int(order.filled_qty) if order.filled_qty else 0,
        }

    def cancel_order(self, order_id):
        """Cancel an open order."""
        try:
            self.trading_client.cancel_order_by_id(order_id)
            return True
        except Exception:
            return False

    def is_order_filled(self, order_id):
        """Check if an order has been fully filled."""
        info = self.get_order(order_id)
        return info["status"] == str(OrderStatus.FILLED)

    def cancel_all_orders(self):
        """Cancel all open orders."""
        self.trading_client.cancel_orders()

    # ── Helpers ──────────────────────────────────────────────

    def is_market_open(self):
        """Check if the market is currently open."""
        clock = self.trading_client.get_clock()
        return clock.is_open
