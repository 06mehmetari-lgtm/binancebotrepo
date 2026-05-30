class KellyCalculator:
    def calculate(self, win_rate: float, avg_win: float, avg_loss: float,
                  max_fraction: float = 0.05) -> float:
        if avg_loss == 0:
            return 0.0
        b = avg_win / avg_loss
        q = 1 - win_rate
        kelly = (b * win_rate - q) / b
        return max(0.0, min(kelly, max_fraction))
