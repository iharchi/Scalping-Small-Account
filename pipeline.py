"""
Main Trading Pipeline for the Small Account Scalping Strategy.

Orchestrates the full workflow:
  1. Pre-trading checklist
  2. Stock scanning
  3. Pattern detection
  4. Risk-managed trade signals
  5. Trade tracking
"""

import datetime

import pandas as pd

import config
from checklist import run_checklist
from scanner import scan_watchlist, get_stock_data, get_daily_data, print_scan_results
from patterns import scan_all_patterns
from risk_manager import RiskManager


class TradingPipeline:
    """Main pipeline that ties all components together."""

    def __init__(self, account_size=None, auto_checklist=False):
        self.risk_manager = RiskManager(account_size)
        self.auto_checklist = auto_checklist
        self.trade_log = []
        self.checklist_passed = False

    def step_1_checklist(self):
        """Run the pre-trading checklist."""
        print("\n[STEP 1] Pre-Trading Checklist")
        self.checklist_passed = run_checklist(auto_mode=self.auto_checklist)
        return self.checklist_passed

    def step_2_scan(self, watchlist):
        """
        Scan the watchlist for stocks meeting criteria.

        Args:
            watchlist: List of ticker symbols.

        Returns:
            List of stocks that pass the scanner.
        """
        if not self.checklist_passed:
            print("[BLOCKED] Cannot scan — checklist not passed.")
            return []

        print("\n[STEP 2] Scanning Watchlist")
        print(f"  Checking {len(watchlist)} symbols...")

        results = scan_watchlist(watchlist)
        print_scan_results(results)
        return results

    def step_3_find_patterns(self, symbol):
        """
        Find trading patterns for a specific stock.

        Args:
            symbol: Ticker symbol to analyze.

        Returns:
            List of detected pattern signals.
        """
        if not self.checklist_passed:
            print("[BLOCKED] Cannot analyze — checklist not passed.")
            return []

        print(f"\n[STEP 3] Pattern Analysis for {symbol}")

        # Fetch intraday data
        intraday = get_stock_data(symbol, period="1d", interval=config.INTRADAY_INTERVAL)
        if intraday is None or len(intraday) < 10:
            print(f"  Insufficient intraday data for {symbol}.")
            return []

        # Fetch daily data for previous close
        daily = get_daily_data(symbol, period="5d")
        prev_close = daily["Close"].iloc[-2] if daily is not None and len(daily) >= 2 else None

        # Split pre-market and regular hours data
        premarket_df = None
        premarket_high = None
        if hasattr(intraday.index, 'hour'):
            premarket_mask = intraday.index.hour < 9
            regular_mask = ~premarket_mask
            if premarket_mask.any():
                premarket_df = intraday[premarket_mask]
                premarket_high = premarket_df["High"].max()
            intraday_regular = intraday[regular_mask] if regular_mask.any() else intraday
        else:
            intraday_regular = intraday

        # Run pattern detection
        signals = scan_all_patterns(
            intraday_regular,
            prev_close=prev_close,
            premarket_df=premarket_df,
            premarket_high=premarket_high,
        )

        if signals:
            print(f"  Found {len(signals)} pattern signal(s):")
            for s in signals:
                print(
                    f"    - {s['pattern']} | "
                    f"Entry: ${s['entry']:.2f} | "
                    f"Stop: ${s['stop_loss']:.2f} | "
                    f"Confidence: {s['confidence']:.0%}"
                )
        else:
            print("  No patterns detected.")

        return signals

    def step_4_evaluate_trade(self, signal):
        """
        Evaluate a signal and generate a sized trade if risk allows.

        Args:
            signal: A pattern signal dict.

        Returns:
            Trade dict if approved, None otherwise.
        """
        print(f"\n[STEP 4] Trade Evaluation — {signal['pattern']}")

        can_trade, reasons = self.risk_manager.can_trade()
        if not can_trade:
            print("  [BLOCKED] Cannot trade:")
            for r in reasons:
                print(f"    - {r}")
            return None

        entry = signal["entry"]
        stop = signal["stop_loss"]
        shares = self.risk_manager.calculate_position_size(entry, stop)
        target = self.risk_manager.calculate_profit_target(entry, stop)

        if shares == 0:
            print("  [SKIP] Position size is 0 — risk too large for account.")
            return None

        risk_dollars = abs(entry - stop) * shares
        reward_dollars = abs(target - entry) * shares

        trade = {
            "pattern": signal["pattern"],
            "entry": entry,
            "stop_loss": stop,
            "profit_target": target,
            "shares": shares,
            "risk": risk_dollars,
            "reward": reward_dollars,
            "rr_ratio": reward_dollars / risk_dollars if risk_dollars > 0 else 0,
            "confidence": signal["confidence"],
        }

        print(f"  Pattern:        {trade['pattern']}")
        print(f"  Entry:          ${trade['entry']:.2f}")
        print(f"  Stop Loss:      ${trade['stop_loss']:.2f}")
        print(f"  Profit Target:  ${trade['profit_target']:.2f}")
        print(f"  Shares:         {trade['shares']}")
        print(f"  Risk:           ${trade['risk']:.2f}")
        print(f"  Reward:         ${trade['reward']:.2f}")
        print(f"  R:R Ratio:      1:{trade['rr_ratio']:.1f}")
        print(f"  Confidence:     {trade['confidence']:.0%}")

        return trade

    def step_5_log_trade(self, trade_record):
        """Log a completed trade."""
        self.trade_log.append(trade_record)

    def run(self, watchlist):
        """
        Run the full pipeline.

        Args:
            watchlist: List of ticker symbols to scan.

        Returns:
            List of trade opportunities found.
        """
        print("\n" + "=" * 60)
        print("  SMALL ACCOUNT SCALPING PIPELINE")
        print(f"  Account: ${self.risk_manager.account_size:,.2f}")
        print(f"  Date: {datetime.date.today()}")
        print("=" * 60)

        # Step 1: Checklist
        if not self.step_1_checklist():
            print("\n[PIPELINE STOPPED] Checklist failed. No trading today.")
            return []

        # Step 2: Scan
        scan_results = self.step_2_scan(watchlist)
        if not scan_results:
            print("\n[PIPELINE COMPLETE] No stocks passed the scanner.")
            return []

        # Step 3 & 4: Patterns + Trade Evaluation
        opportunities = []

        for stock in scan_results:
            symbol = stock["symbol"]
            signals = self.step_3_find_patterns(symbol)

            for signal in signals:
                trade = self.step_4_evaluate_trade(signal)
                if trade:
                    trade["symbol"] = symbol
                    opportunities.append(trade)

                # Respect trade limits
                can_trade, _ = self.risk_manager.can_trade()
                if not can_trade:
                    break

            can_trade, _ = self.risk_manager.can_trade()
            if not can_trade:
                break

        # Summary
        print("\n" + "=" * 60)
        print("  PIPELINE SUMMARY")
        print("=" * 60)
        print(f"  Stocks scanned:      {len(watchlist)}")
        print(f"  Stocks passed:       {len(scan_results)}")
        print(f"  Opportunities found: {len(opportunities)}")
        self.risk_manager.print_status()

        if opportunities:
            print("  Top opportunity:")
            best = max(opportunities, key=lambda o: o["confidence"])
            print(f"    {best['symbol']} — {best['pattern']}")
            print(f"    Entry ${best['entry']:.2f} → Target ${best['profit_target']:.2f}")
            print(f"    Risk ${best['risk']:.2f} for ${best['reward']:.2f} reward")
        else:
            print("  No trade opportunities today. Patience is key.")

        return opportunities
