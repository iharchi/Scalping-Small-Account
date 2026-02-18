"""
Stock Scanner for the Small Account Scalping Pipeline.

Scans for stocks that meet the criteria for small account scalping:
  - Price range ($1-$20)
  - High relative volume
  - Low float
  - Pre-market gap
  - News catalyst (manual check)
"""

import datetime

import pandas as pd
import yfinance as yf

import config


def get_stock_data(symbol, period="5d", interval="1m"):
    """Fetch historical data for a single stock."""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            return None
        return df
    except Exception:
        return None


def get_daily_data(symbol, period="30d"):
    """Fetch daily data for swing context."""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=config.DAILY_INTERVAL)
        if df.empty:
            return None
        return df
    except Exception:
        return None


def get_stock_info(symbol):
    """Fetch stock info (float, market cap, etc.)."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        return info
    except Exception:
        return {}


def check_criteria(symbol):
    """
    Check if a stock meets the small account criteria.

    Returns:
        dict with criteria results, or None if data unavailable.
    """
    info = get_stock_info(symbol)
    daily = get_daily_data(symbol, period="5d")

    if daily is None or len(daily) < 2:
        return None

    current_price = daily["Close"].iloc[-1]
    prev_close = daily["Close"].iloc[-2]
    gap_pct = ((current_price - prev_close) / prev_close) * 100

    # Volume check
    today_volume = daily["Volume"].iloc[-1]
    avg_volume = daily["Volume"].iloc[:-1].mean() if len(daily) > 1 else 0
    relative_volume = today_volume / avg_volume if avg_volume > 0 else 0

    # Float check
    shares_float = info.get("floatShares", None)

    result = {
        "symbol": symbol,
        "price": current_price,
        "prev_close": prev_close,
        "gap_pct": gap_pct,
        "volume": today_volume,
        "avg_volume": avg_volume,
        "relative_volume": relative_volume,
        "float": shares_float,
        "passes": True,
        "reasons": [],
    }

    # Apply filters
    if current_price < config.MIN_PRICE or current_price > config.MAX_PRICE:
        result["passes"] = False
        result["reasons"].append(f"Price ${current_price:.2f} outside range ${config.MIN_PRICE}-${config.MAX_PRICE}")

    if today_volume < config.MIN_VOLUME:
        result["passes"] = False
        result["reasons"].append(f"Volume {today_volume:,.0f} below minimum {config.MIN_VOLUME:,.0f}")

    if relative_volume < config.MIN_RELATIVE_VOLUME:
        result["passes"] = False
        result["reasons"].append(f"Relative volume {relative_volume:.1f}x below minimum {config.MIN_RELATIVE_VOLUME}x")

    if shares_float is not None:
        if shares_float < config.MIN_FLOAT or shares_float > config.MAX_FLOAT:
            result["passes"] = False
            result["reasons"].append(f"Float {shares_float:,.0f} outside range")

    if abs(gap_pct) < config.MIN_GAP_PCT:
        result["passes"] = False
        result["reasons"].append(f"Gap {gap_pct:.1f}% below minimum {config.MIN_GAP_PCT}%")

    return result


def scan_watchlist(symbols):
    """
    Scan a list of symbols and return those that pass criteria.

    Args:
        symbols: List of ticker symbols to scan.

    Returns:
        List of dicts for stocks that pass, sorted by relative volume.
    """
    results = []

    for symbol in symbols:
        result = check_criteria(symbol)
        if result is not None and result["passes"]:
            results.append(result)

    results.sort(key=lambda r: r["relative_volume"], reverse=True)
    return results


def print_scan_results(results):
    """Pretty-print scan results."""
    if not results:
        print("\nNo stocks passed the scanner criteria.")
        return

    print(f"\n{'='*70}")
    print(f"{'Symbol':<8} {'Price':>8} {'Gap%':>8} {'RVol':>8} {'Volume':>12}")
    print(f"{'='*70}")

    for r in results:
        print(
            f"{r['symbol']:<8} "
            f"${r['price']:>7.2f} "
            f"{r['gap_pct']:>7.1f}% "
            f"{r['relative_volume']:>7.1f}x "
            f"{r['volume']:>11,.0f}"
        )

    print(f"{'='*70}")
    print(f"  {len(results)} stock(s) passed the scanner.\n")
