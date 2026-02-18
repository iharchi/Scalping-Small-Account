"""
Pre-Trading Checklist — must pass before the pipeline allows any trades.
Based on the Warrior Trading Small Account Challenge checklist.
"""

import datetime


CHECKLIST_ITEMS = [
    ("Did you eat & sleep well?", True),
    ("Are you in a good mood?", True),
    ("Do you have a stock that looks good this morning based on your strategy?", True),
    ("Is the overall market condition favorable for your strategy?", True),
    ("Do you have an A-Quality setup printed and pinned next to your computer?", True),
    ("Do you have your metrics and track record from SIM trading printed?", True),
    ("Are you willing to NOT take any trades if nothing looks good?", True),
    ("Are you restricting the number of trades today?", True),
]


def run_checklist(auto_mode=False):
    """
    Run the pre-trading checklist interactively or in auto mode.

    Args:
        auto_mode: If True, skip interactive prompts and return True (for backtesting).

    Returns:
        True if the checklist passes, False otherwise.
    """
    if auto_mode:
        return True

    print("\n" + "=" * 60)
    print("PRE-TRADING CHECKLIST")
    print(f"Date: {datetime.date.today()}")
    print("=" * 60)
    print("Trading is risky. Most traders lose money.")
    print("Trading in a small account is about PROOF OF CONCEPT.")
    print("Can you be disciplined enough to take one trade a day")
    print("and grow the account slowly?")
    print("=" * 60 + "\n")

    failed = []

    for question, required_answer in CHECKLIST_ITEMS:
        while True:
            response = input(f"  {question} (y/n): ").strip().lower()
            if response in ("y", "n", "yes", "no"):
                break
            print("    Please answer y or n.")

        answered_yes = response in ("y", "yes")

        if answered_yes != required_answer:
            failed.append(question)

    if failed:
        print("\n[CHECKLIST FAILED] You did not pass the following items:")
        for item in failed:
            print(f"  - {item}")
        print("\nConsider sitting today out. Trading is a marathon, not a sprint.")
        return False

    print("\n[CHECKLIST PASSED] You are cleared to look for setups today.")
    return True
