"""
Configuration for the Small Account Scalping Pipeline.
"""

# Account settings
ACCOUNT_SIZE = 500.00
MAX_RISK_PER_TRADE_PCT = 1.0  # 1% of account per trade
MAX_TRADES_PER_DAY = 1
MAX_LOSS_PER_DAY_PCT = 2.0  # 2% daily max loss

# Scanner settings
MIN_PRICE = 1.00
MAX_PRICE = 20.00
MIN_VOLUME = 500_000
MIN_RELATIVE_VOLUME = 2.0
MIN_FLOAT = 1_000_000
MAX_FLOAT = 50_000_000
MIN_GAP_PCT = 5.0  # Minimum pre-market gap %

# Pattern detection settings
BULL_FLAG_CONSOLIDATION_BARS = 5
FLAT_TOP_TOLERANCE_PCT = 0.5
ABCD_RETRACEMENT_MIN = 0.382
ABCD_RETRACEMENT_MAX = 0.786
MICRO_PULLBACK_BARS = 3
OPENING_RANGE_MINUTES = 1

# Risk management
STOP_LOSS_ATR_MULTIPLIER = 1.5
PROFIT_TARGET_RATIO = 2.0  # Risk/reward ratio (2:1)

# Loop settings
CYCLE_INTERVAL = 1.0  # Max seconds per pipeline cycle (must be <= 1.0)
SCAN_REFRESH_INTERVAL = 300  # Re-run full scanner every 5 minutes

# Data settings
INTRADAY_INTERVAL = "1m"
DAILY_INTERVAL = "1d"
PREMARKET_START = "04:00"
MARKET_OPEN = "09:30"
MARKET_CLOSE = "16:00"
