"""
Pattern detection for the Small Account Scalping Pipeline.

Implements the quality setups from the Warrior Trading strategy:
  - Bull Flag Breakout
  - Flat Top Breakout
  - ABCD Pattern
  - Micro Pullbacks
  - Whole Dollar & Half Dollar Entries
  - 1-Minute Opening Range Breakout
  - Red to Green Move
  - Break of Pre-Market Pivot
  - Break of Pre-Market Highs
"""

import numpy as np
import pandas as pd
from ta.volatility import AverageTrueRange

import config


def detect_bull_flag(df):
    """
    Detect bull flag breakout pattern.

    A bull flag forms after a strong move up (the pole), followed by a
    short consolidation with lower highs (the flag), then a breakout
    above the flag's high.

    Returns list of dicts with signal info.
    """
    signals = []
    n = config.BULL_FLAG_CONSOLIDATION_BARS

    if len(df) < n + 5:
        return signals

    for i in range(n + 5, len(df)):
        # Check for a strong upward move (pole) before consolidation
        pole_start = i - n - 5
        pole_end = i - n
        pole_gain = (df["Close"].iloc[pole_end] - df["Close"].iloc[pole_start]) / df["Close"].iloc[pole_start]

        if pole_gain < 0.03:  # At least 3% move for the pole
            continue

        # Check for consolidation (flag): lower highs or tight range
        flag_section = df.iloc[pole_end:i]
        flag_range = (flag_section["High"].max() - flag_section["Low"].min()) / flag_section["Low"].min()

        if flag_range > 0.03:  # Flag should be tight (< 3% range)
            continue

        # Check for breakout: current bar closes above flag high
        flag_high = flag_section["High"].max()
        if df["Close"].iloc[i] > flag_high and df["Volume"].iloc[i] > df["Volume"].iloc[i - n:i].mean():
            signals.append({
                "pattern": "Bull Flag Breakout",
                "index": i,
                "timestamp": df.index[i],
                "entry": df["Close"].iloc[i],
                "stop_loss": flag_section["Low"].min(),
                "confidence": min(pole_gain * 10, 1.0),
            })

    return signals


def detect_flat_top_breakout(df):
    """
    Detect flat top breakout pattern.

    Multiple touches of a resistance level with a tight range, followed
    by a breakout above resistance on volume.
    """
    signals = []
    lookback = 10
    tolerance = config.FLAT_TOP_TOLERANCE_PCT / 100

    if len(df) < lookback + 1:
        return signals

    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        resistance = window["High"].max()

        # Count touches near resistance
        touches = ((window["High"] >= resistance * (1 - tolerance)) &
                   (window["High"] <= resistance * (1 + tolerance))).sum()

        if touches < 3:
            continue

        # Breakout bar
        if (df["Close"].iloc[i] > resistance and
                df["Volume"].iloc[i] > window["Volume"].mean() * 1.5):
            signals.append({
                "pattern": "Flat Top Breakout",
                "index": i,
                "timestamp": df.index[i],
                "entry": df["Close"].iloc[i],
                "stop_loss": window["Low"].min(),
                "confidence": min(touches / 5, 1.0),
            })

    return signals


def detect_abcd(df):
    """
    Detect ABCD pattern.

    A = swing low, B = swing high, C = higher low retracement,
    D = breakout above B. Retracement should be between 38.2% and 78.6%.
    """
    signals = []

    if len(df) < 20:
        return signals

    for i in range(20, len(df)):
        window = df.iloc[i - 20:i + 1]

        # Find swing points (simplified)
        lows = window["Low"].values
        highs = window["High"].values

        a_idx = np.argmin(lows[:10])
        b_idx = np.argmax(highs[a_idx:a_idx + 10]) + a_idx

        if b_idx <= a_idx:
            continue

        a_price = lows[a_idx]
        b_price = highs[b_idx]
        ab_range = b_price - a_price

        if ab_range <= 0:
            continue

        # Find C (pullback from B)
        c_section = lows[b_idx:b_idx + 8] if b_idx + 8 <= len(lows) else lows[b_idx:]
        if len(c_section) == 0:
            continue

        c_idx = np.argmin(c_section) + b_idx
        c_price = lows[c_idx]

        retracement = (b_price - c_price) / ab_range

        if not (config.ABCD_RETRACEMENT_MIN <= retracement <= config.ABCD_RETRACEMENT_MAX):
            continue

        # D = breakout above B
        if df["Close"].iloc[i] > b_price:
            signals.append({
                "pattern": "ABCD",
                "index": i,
                "timestamp": df.index[i],
                "entry": df["Close"].iloc[i],
                "stop_loss": c_price,
                "confidence": 1.0 - abs(retracement - 0.618),
            })

    return signals


def detect_micro_pullback(df):
    """
    Detect micro pullback entries.

    After a strong move, a 1-3 bar pullback into the moving average
    provides an entry for continuation.
    """
    signals = []
    n = config.MICRO_PULLBACK_BARS

    if len(df) < 20:
        return signals

    df = df.copy()
    df["EMA9"] = df["Close"].ewm(span=9).mean()

    for i in range(10, len(df)):
        # Check for prior uptrend (close above EMA9 for several bars)
        prior = df.iloc[i - 6:i - n]
        if len(prior) == 0:
            continue

        if not (prior["Close"] > prior["EMA9"]).all():
            continue

        # Check for pullback into EMA9
        pullback = df.iloc[i - n:i]
        touched_ema = (pullback["Low"] <= pullback["EMA9"]).any()

        if not touched_ema:
            continue

        # Check for bounce: current bar closes above EMA9 with strength
        if (df["Close"].iloc[i] > df["EMA9"].iloc[i] and
                df["Close"].iloc[i] > df["Open"].iloc[i]):
            signals.append({
                "pattern": "Micro Pullback",
                "index": i,
                "timestamp": df.index[i],
                "entry": df["Close"].iloc[i],
                "stop_loss": pullback["Low"].min(),
                "confidence": 0.7,
            })

    return signals


def detect_whole_half_dollar(df):
    """
    Detect entries near whole dollar and half dollar levels.

    These psychological levels often act as support/resistance.
    A bounce off these levels with volume is a potential entry.
    """
    signals = []

    if len(df) < 5:
        return signals

    for i in range(5, len(df)):
        price = df["Close"].iloc[i]
        low = df["Low"].iloc[i]

        # Check if price is near a whole or half dollar
        nearest_whole = round(price)
        nearest_half = round(price * 2) / 2

        near_whole = abs(low - nearest_whole) / price < 0.005
        near_half = abs(low - nearest_half) / price < 0.005

        if not (near_whole or near_half):
            continue

        # Bounce confirmation: close above the level
        level = nearest_whole if near_whole else nearest_half
        if (df["Close"].iloc[i] > level and
                df["Close"].iloc[i] > df["Open"].iloc[i] and
                df["Volume"].iloc[i] > df["Volume"].iloc[i - 5:i].mean()):
            signals.append({
                "pattern": "Whole/Half Dollar Entry",
                "index": i,
                "timestamp": df.index[i],
                "entry": df["Close"].iloc[i],
                "stop_loss": level - 0.10,
                "confidence": 0.6,
            })

    return signals


def detect_opening_range_breakout(df):
    """
    Detect 1-minute opening range breakout.

    The high and low of the first 1-minute candle after market open
    define the range. A breakout above the high is a buy signal.
    """
    signals = []

    if len(df) < 2:
        return signals

    # Assume first bar is the opening range
    opening_high = df["High"].iloc[0]
    opening_low = df["Low"].iloc[0]

    for i in range(1, len(df)):
        if (df["Close"].iloc[i] > opening_high and
                df["Volume"].iloc[i] > df["Volume"].iloc[0] * 0.5):
            signals.append({
                "pattern": "1min Opening Range Breakout",
                "index": i,
                "timestamp": df.index[i],
                "entry": df["Close"].iloc[i],
                "stop_loss": opening_low,
                "confidence": 0.75,
            })
            break  # Only trigger once

    return signals


def detect_red_to_green(df, prev_close=None):
    """
    Detect red to green move.

    Stock opens below prior close (red), then crosses above it (green).
    This momentum shift can signal a strong move higher.
    """
    signals = []

    if prev_close is None or len(df) < 2:
        return signals

    # Stock must open red (below prior close)
    if df["Open"].iloc[0] >= prev_close:
        return signals

    for i in range(1, len(df)):
        if (df["Close"].iloc[i] > prev_close and
                df["Close"].iloc[i - 1] <= prev_close):
            signals.append({
                "pattern": "Red to Green Move",
                "index": i,
                "timestamp": df.index[i],
                "entry": df["Close"].iloc[i],
                "stop_loss": df["Low"].iloc[:i + 1].min(),
                "confidence": 0.7,
            })
            break

    return signals


def detect_premarket_pivot_break(df, premarket_df=None):
    """
    Detect break of pre-market pivot.

    The pivot is the price level with the most volume in pre-market.
    A break above this level during regular hours signals strength.
    """
    signals = []

    if premarket_df is None or len(premarket_df) == 0 or len(df) < 2:
        return signals

    # Find pivot: VWAP-like level from pre-market
    total_volume = premarket_df["Volume"].sum()
    if total_volume == 0:
        return signals

    pivot = (premarket_df["Close"] * premarket_df["Volume"]).sum() / total_volume

    for i in range(1, len(df)):
        if (df["Close"].iloc[i] > pivot and
                df["Close"].iloc[i - 1] <= pivot and
                df["Volume"].iloc[i] > df["Volume"].iloc[max(0, i - 5):i].mean() if i > 0 else True):
            signals.append({
                "pattern": "Break of Pre-Market Pivot",
                "index": i,
                "timestamp": df.index[i],
                "entry": df["Close"].iloc[i],
                "stop_loss": pivot - (df["Close"].iloc[i] - pivot) * 0.5,
                "confidence": 0.65,
            })
            break

    return signals


def detect_premarket_high_break(df, premarket_high=None):
    """
    Detect break of pre-market highs.

    A breakout above the pre-market high with volume during regular
    trading hours is a strong momentum signal.
    """
    signals = []

    if premarket_high is None or len(df) < 2:
        return signals

    for i in range(1, len(df)):
        if (df["Close"].iloc[i] > premarket_high and
                df["Close"].iloc[i - 1] <= premarket_high):
            signals.append({
                "pattern": "Break of Pre-Market Highs",
                "index": i,
                "timestamp": df.index[i],
                "entry": df["Close"].iloc[i],
                "stop_loss": premarket_high - (df["Close"].iloc[i] - premarket_high) * 0.5,
                "confidence": 0.8,
            })
            break

    return signals


def scan_all_patterns(df, prev_close=None, premarket_df=None, premarket_high=None):
    """
    Run all pattern detectors on the given dataframe.

    Returns a sorted list of all detected signals (highest confidence first).
    """
    all_signals = []

    detectors = [
        lambda: detect_bull_flag(df),
        lambda: detect_flat_top_breakout(df),
        lambda: detect_abcd(df),
        lambda: detect_micro_pullback(df),
        lambda: detect_whole_half_dollar(df),
        lambda: detect_opening_range_breakout(df),
        lambda: detect_red_to_green(df, prev_close),
        lambda: detect_premarket_pivot_break(df, premarket_df),
        lambda: detect_premarket_high_break(df, premarket_high),
    ]

    for detector in detectors:
        try:
            signals = detector()
            all_signals.extend(signals)
        except Exception:
            continue

    all_signals.sort(key=lambda s: s["confidence"], reverse=True)
    return all_signals
