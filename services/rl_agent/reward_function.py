TRANSACTION_COST = 0.0004

def compute_reward(action: int, position: int, price: float, entry_price: float) -> float:
    reward = 0.0
    if action == 1 and position == 0:  # enter long
        reward -= TRANSACTION_COST
    elif action == 2 and position == 0:  # enter short
        reward -= TRANSACTION_COST
    elif action == 0 and position == 1:  # close long
        reward = (price - entry_price) / entry_price - TRANSACTION_COST
    elif action == 0 and position == -1:  # close short
        reward = (entry_price - price) / entry_price - TRANSACTION_COST
    return float(reward)
