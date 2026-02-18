#!/usr/bin/env python3
"""
Small Account Scalping Pipeline — Entry Point.

Usage:
    python main.py --loop --auto            # Live loop, skip checklist
    python main.py                          # One-shot scan
    python main.py --symbols AAPL TSLA      # Custom watchlist
    python main.py --account-size 1000      # Custom account size

Requires ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.

Disclaimer: Trading is risky. Most traders lose money.
This tool is for educational purposes only.
"""

import argparse
import sys

from broker import AlpacaBroker
from pipeline import TradingPipeline


# Default watchlist of commonly traded small-cap / momentum stocks
# Replace with your own scanner results or pre-market movers
DEFAULT_WATCHLIST = [
    "AAPL", "AMD", "TSLA", "NVDA", "SOFI",
    "PLTR", "NIO", "MARA", "RIOT", "LCID",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Small Account Scalping Pipeline"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=DEFAULT_WATCHLIST,
        help="Ticker symbols to scan (default: built-in watchlist)",
    )
    parser.add_argument(
        "--account-size",
        type=float,
        default=None,
        help="Starting account size in dollars (default: synced from Alpaca)",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto mode: skip interactive checklist (for backtesting)",
    )
    parser.add_argument(
        "--max-trades",
        type=int,
        default=None,
        help="Override max trades per day",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run in continuous loop mode with 1-second cycles",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print("\n" + "*" * 60)
    print("  DISCLAIMER: Trading is risky. Most traders lose money.")
    print("  This tool is for EDUCATIONAL PURPOSES only.")
    print("  Read the full disclaimer before trading real money.")
    print("*" * 60)

    # Initialize Alpaca broker
    try:
        broker = AlpacaBroker()
    except ValueError as e:
        print(f"\n[ERROR] {e}")
        print("  Export your keys:")
        print("    export ALPACA_API_KEY='your-key'")
        print("    export ALPACA_SECRET_KEY='your-secret'")
        return 1

    acct = broker.get_account()
    import config as cfg
    print(f"\n  Connected to Alpaca ({'Paper' if cfg.ALPACA_PAPER else 'LIVE'})")
    print(f"  Equity: ${acct['equity']:,.2f}  |  Buying Power: ${acct['buying_power']:,.2f}")

    pipeline = TradingPipeline(
        broker=broker,
        account_size=args.account_size,
        auto_checklist=args.auto,
    )

    if args.max_trades is not None:
        pipeline.risk_manager.max_trades = args.max_trades

    if args.loop:
        pipeline.run_loop(args.symbols)
        return 0
    else:
        opportunities = pipeline.run(args.symbols)

        if opportunities:
            print("\nRemember:")
            print("  - Trading in a small account is about PROOF OF CONCEPT")
            print("  - Be disciplined — take ONE good trade")
            print("  - Cut losses quickly, let winners run to target")
            print("  - Trading is a marathon, not a sprint")

        return 0 if opportunities else 1


if __name__ == "__main__":
    sys.exit(main())
