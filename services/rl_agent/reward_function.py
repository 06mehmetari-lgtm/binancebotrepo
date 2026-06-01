"""
Step-based reward function for the PPO trading environment.

Design principles:
- Entry: small transaction cost only (no signal about direction yet)
- Holding: per-step unrealized P&L minus funding cost (shapes gradients continuously)
- Exit: full realized P&L minus transaction cost
- Flat/no action while flat: zero (no penalty for waiting)
"""

TRANSACTION_COST = 0.0004  # 0.04% per side (Binance taker fee)
HOLD_COST = 0.000005       # ~0.05% per 8h = per step cost to discourage infinite holds


def compute_reward(action: int, position: int, price: float, entry_price: float) -> float:
    reward = 0.0

    if action == 1 and position == 0:       # enter long
        reward = -TRANSACTION_COST

    elif action == 2 and position == 0:     # enter short
        reward = -TRANSACTION_COST

    elif action == 0 and position == 1:     # close long
        if entry_price > 0:
            reward = (price - entry_price) / entry_price - TRANSACTION_COST
        else:
            reward = -TRANSACTION_COST

    elif action == 0 and position == -1:    # close short
        if entry_price > 0:
            reward = (entry_price - price) / entry_price - TRANSACTION_COST
        else:
            reward = -TRANSACTION_COST

    elif action == 0 and position == 0:     # hold flat — neutral
        reward = 0.0

    elif action == 1 and position == 1:     # already long, hold
        # Step reward: unrealized P&L change encourages riding winners
        if entry_price > 0:
            reward = (price - entry_price) / entry_price * 0.1 - HOLD_COST
        else:
            reward = -HOLD_COST

    elif action == 2 and position == -1:    # already short, hold
        if entry_price > 0:
            reward = (entry_price - price) / entry_price * 0.1 - HOLD_COST
        else:
            reward = -HOLD_COST

    elif action == 1 and position == -1:    # flip short→long (penalise, should close first)
        reward = -TRANSACTION_COST * 2

    elif action == 2 and position == 1:     # flip long→short (penalise, should close first)
        reward = -TRANSACTION_COST * 2

    return float(reward)
