"""
Main Trading Pipeline for the Small Account Scalping Strategy.

Runs a continuous loop with a max cycle time of 1 second:
  1. Pre-trading checklist (once at startup)
  2. Stock scanning (periodically refreshed)
  3. Pattern detection (every cycle)
  4. Exit monitoring for open positions (every cycle)
  5. Risk-managed trade signals

All data and orders flow through the Alpaca broker.
"""

import datetime
import time

import pandas as pd

import config
from checklist import run_checklist
from scanner import scan_watchlist, get_stock_data, get_daily_data, get_latest_price, print_scan_results
from patterns import scan_all_patterns
from risk_manager import RiskManager


class TradingPipeline:
    """Main pipeline that ties all components together."""

    def __init__(self, broker, account_size=None, auto_checklist=False):
        self.broker = broker
        self.risk_manager = RiskManager(broker=broker, account_size=account_size)
        self.auto_checklist = auto_checklist
        self.trade_log = []
        self.checklist_passed = False
        self.running = False

        # Cached state to keep cycles fast
        self._scan_results = []
        self._last_scan_time = 0
        self._daily_cache = {}  # symbol -> (daily_df, prev_close)
        self._premarket_cache = {}  # symbol -> (premarket_df, premarket_high)
        self._cycle_count = 0

    def step_1_checklist(self):
        """Run the pre-trading checklist."""
        print("\n[STEP 1] Pre-Trading Checklist")
        self.checklist_passed = run_checklist(auto_mode=self.auto_checklist)
        return self.checklist_passed

    def _refresh_scan(self, watchlist):
        """Re-run the scanner if enough time has passed."""
        now = time.monotonic()
        if now - self._last_scan_time < config.SCAN_REFRESH_INTERVAL and self._scan_results:
            return self._scan_results

        print(f"\n[SCAN] Refreshing watchlist ({len(watchlist)} symbols)...")
        self._scan_results = scan_watchlist(self.broker, watchlist)
        self._last_scan_time = now
        print_scan_results(self._scan_results)

        # Pre-fetch daily data for passing stocks
        for stock in self._scan_results:
            sym = stock["symbol"]
            if sym not in self._daily_cache:
                daily = get_daily_data(self.broker, sym, limit=10)
                prev_close = daily["Close"].iloc[-2] if daily is not None and len(daily) >= 2 else None
                self._daily_cache[sym] = (daily, prev_close)

        return self._scan_results

    def _fetch_intraday(self, symbol):
        """Fetch latest intraday bars for a symbol."""
        return get_stock_data(self.broker, symbol, timeframe="1min", limit=100)

    def _split_premarket(self, symbol, intraday):
        """Split intraday data into pre-market and regular hours."""
        if symbol in self._premarket_cache:
            return self._premarket_cache[symbol]

        premarket_df = None
        premarket_high = None

        if hasattr(intraday.index, "hour"):
            premarket_mask = intraday.index.hour < 9
            if premarket_mask.any():
                premarket_df = intraday[premarket_mask]
                premarket_high = premarket_df["High"].max()

        self._premarket_cache[symbol] = (premarket_df, premarket_high)
        return premarket_df, premarket_high

    def _check_open_position(self):
        """
        Check stop loss / profit target on an open position.

        Uses Alpaca order status polling (broker handles OCO cancellation).
        Falls back to quote-based price check if no broker orders.
        """
        pos = self.risk_manager.open_position
        if pos is None:
            return None

        # Get current price for logging (and fallback exit check)
        current_price = get_latest_price(self.broker, pos["symbol"])

        result = self.risk_manager.check_exit_conditions(current_price)
        if result is None:
            return None

        exit_type, exit_price = result
        trade_record = self.risk_manager.close_trade(exit_price)

        if trade_record:
            tag = "STOP LOSS" if exit_type == "stop_loss" else "TARGET HIT"
            print(
                f"\n  [{tag}] {trade_record['symbol']} "
                f"exit ${exit_price:.2f} | "
                f"P&L ${trade_record['pnl']:+.2f} "
                f"({trade_record['pnl_pct']:+.1f}%)"
            )
            self.trade_log.append(trade_record)

        return trade_record

    def _run_cycle(self, watchlist):
        """
        Execute one pipeline cycle. Must complete within CYCLE_INTERVAL.

        Returns list of new signals found this cycle.
        """
        self._cycle_count += 1
        signals_this_cycle = []

        # If we have an open position, just monitor it
        if self.risk_manager.open_position is not None:
            self._check_open_position()
            return signals_this_cycle

        # Check if we can still trade
        can_trade, reasons = self.risk_manager.can_trade()
        if not can_trade:
            return signals_this_cycle

        # Refresh scan periodically
        scan_results = self._refresh_scan(watchlist)
        if not scan_results:
            return signals_this_cycle

        # Scan each passing stock for patterns
        for stock in scan_results:
            symbol = stock["symbol"]

            intraday = self._fetch_intraday(symbol)
            if intraday is None or len(intraday) < 10:
                continue

            # Get cached daily / premarket context
            _, prev_close = self._daily_cache.get(symbol, (None, None))
            premarket_df, premarket_high = self._split_premarket(symbol, intraday)

            # Regular hours only for pattern detection
            if hasattr(intraday.index, "hour"):
                regular_mask = intraday.index.hour >= 9
                intraday_regular = intraday[regular_mask] if regular_mask.any() else intraday
            else:
                intraday_regular = intraday

            signals = scan_all_patterns(
                intraday_regular,
                prev_close=prev_close,
                premarket_df=premarket_df,
                premarket_high=premarket_high,
            )

            for signal in signals:
                signal["symbol"] = symbol
                signals_this_cycle.append(signal)

        # Evaluate the best signal
        if signals_this_cycle:
            best = max(signals_this_cycle, key=lambda s: s["confidence"])
            entry = best["entry"]
            stop = best["stop_loss"]
            shares = self.risk_manager.calculate_position_size(entry, stop)
            target = self.risk_manager.calculate_profit_target(entry, stop)

            if shares > 0:
                risk_dollars = abs(entry - stop) * shares
                reward_dollars = abs(target - entry) * shares

                print(
                    f"\n  [SIGNAL] {best['symbol']} — {best['pattern']} | "
                    f"Entry ${entry:.2f} | Stop ${stop:.2f} | "
                    f"Target ${target:.2f} | {shares} shares | "
                    f"Risk ${risk_dollars:.2f} -> Reward ${reward_dollars:.2f} | "
                    f"Confidence {best['confidence']:.0%}"
                )

                self.risk_manager.open_trade(best["symbol"], entry, stop, shares)

        return signals_this_cycle

    def run(self, watchlist):
        """
        Run the pipeline as a one-shot execution.
        """
        print("\n" + "=" * 60)
        print("  SMALL ACCOUNT SCALPING PIPELINE")
        print(f"  Account: ${self.risk_manager.account_size:,.2f}")
        print(f"  Mode:    {'Paper' if config.ALPACA_PAPER else 'LIVE'}")
        print(f"  Date:    {datetime.date.today()}")
        print("=" * 60)

        if not self.step_1_checklist():
            print("\n[PIPELINE STOPPED] Checklist failed. No trading today.")
            return []

        scan_results = self._refresh_scan(watchlist)
        if not scan_results:
            print("\n[PIPELINE COMPLETE] No stocks passed the scanner.")
            return []

        opportunities = []
        for stock in scan_results:
            symbol = stock["symbol"]
            intraday = self._fetch_intraday(symbol)
            if intraday is None or len(intraday) < 10:
                continue

            _, prev_close = self._daily_cache.get(symbol, (None, None))
            premarket_df, premarket_high = self._split_premarket(symbol, intraday)

            if hasattr(intraday.index, "hour"):
                regular_mask = intraday.index.hour >= 9
                intraday_regular = intraday[regular_mask] if regular_mask.any() else intraday
            else:
                intraday_regular = intraday

            signals = scan_all_patterns(
                intraday_regular,
                prev_close=prev_close,
                premarket_df=premarket_df,
                premarket_high=premarket_high,
            )

            for signal in signals:
                entry = signal["entry"]
                stop = signal["stop_loss"]
                shares = self.risk_manager.calculate_position_size(entry, stop)
                if shares > 0:
                    target = self.risk_manager.calculate_profit_target(entry, stop)
                    signal["symbol"] = symbol
                    signal["shares"] = shares
                    signal["profit_target"] = target
                    opportunities.append(signal)

        if opportunities:
            best = max(opportunities, key=lambda o: o["confidence"])
            print(f"\n  Top opportunity: {best['symbol']} — {best['pattern']}")
            print(f"    Entry ${best['entry']:.2f} -> Target ${best['profit_target']:.2f}")
        else:
            print("  No trade opportunities. Patience is key.")

        return opportunities

    def run_loop(self, watchlist):
        """
        Run the pipeline in a continuous loop with cycles <= 1 second.

        Each cycle:
          - Polls Alpaca for latest quotes / order status
          - Detects patterns or monitors open position
          - Enforces risk limits
          - Sleeps for the remainder of the cycle interval
        """
        print("\n" + "=" * 60)
        print("  SMALL ACCOUNT SCALPING PIPELINE — LIVE LOOP")
        print(f"  Account: ${self.risk_manager.account_size:,.2f}")
        print(f"  Mode:    {'Paper' if config.ALPACA_PAPER else 'LIVE'}")
        print(f"  Cycle:   {config.CYCLE_INTERVAL}s max")
        print(f"  Date:    {datetime.date.today()}")
        print("=" * 60)

        # Check market hours
        if not self.broker.is_market_open():
            print("\n[WARNING] Market is currently closed.")
            print("  Orders will queue until market opens.")

        if not self.step_1_checklist():
            print("\n[PIPELINE STOPPED] Checklist failed. No trading today.")
            return

        self.running = True
        print("\n[LIVE] Pipeline running. Press Ctrl+C to stop.\n")

        try:
            while self.running:
                cycle_start = time.monotonic()

                self._run_cycle(watchlist)

                # Check if we're done for the day
                can_trade, _ = self.risk_manager.can_trade()
                if not can_trade and self.risk_manager.open_position is None:
                    print("\n[DONE] Trade limits reached for today.")
                    break

                # Sleep for the remainder of the cycle
                elapsed = time.monotonic() - cycle_start
                sleep_time = max(0, config.CYCLE_INTERVAL - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

                # Log cycle timing periodically
                if self._cycle_count % 60 == 0:
                    total_elapsed = time.monotonic() - cycle_start
                    pos_status = "MONITORING" if self.risk_manager.open_position else "SCANNING"
                    print(
                        f"  [CYCLE {self._cycle_count}] "
                        f"{pos_status} | "
                        f"Account ${self.risk_manager.account_size:,.2f} | "
                        f"P&L ${self.risk_manager.daily_pnl:+,.2f} | "
                        f"Cycle {total_elapsed:.3f}s"
                    )

        except KeyboardInterrupt:
            print("\n\n[STOPPED] Pipeline stopped by user.")

        # Final summary
        self._print_summary()

    def _print_summary(self):
        """Print end-of-session summary."""
        print("\n" + "=" * 60)
        print("  SESSION SUMMARY")
        print("=" * 60)
        print(f"  Cycles run:     {self._cycle_count}")
        print(f"  Trades taken:   {self.risk_manager.trades_today}")
        print(f"  Daily P&L:      ${self.risk_manager.daily_pnl:+,.2f}")
        print(f"  Account size:   ${self.risk_manager.account_size:,.2f}")

        if self.trade_log:
            print(f"\n  {'Symbol':<8} {'Pattern':<28} {'Entry':>8} {'Exit':>8} {'P&L':>10}")
            print(f"  {'-'*62}")
            for t in self.trade_log:
                print(
                    f"  {t['symbol']:<8} "
                    f"{t.get('pattern', 'N/A'):<28} "
                    f"${t['entry_price']:>7.2f} "
                    f"${t['exit_price']:>7.2f} "
                    f"${t['pnl']:>+9.2f}"
                )

        print("=" * 60)

    def stop(self):
        """Signal the loop to stop after the current cycle."""
        self.running = False
