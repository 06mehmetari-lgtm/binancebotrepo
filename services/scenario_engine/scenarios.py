from dataclasses import dataclass

@dataclass
class CrisisScenario:
    name: str
    description: str
    btc_shock: float       # % price change
    vix_target: float
    duration_hours: int

SCENARIOS: list[CrisisScenario] = [
    CrisisScenario("covid_crash_2020",      "Pandemic black swan",              -0.50, 85, 72),
    CrisisScenario("luna_collapse_2022",    "UST depeg cascade",                -0.55, 40, 48),
    CrisisScenario("ftx_collapse_2022",     "Exchange insolvency contagion",    -0.25, 35, 96),
    CrisisScenario("btc_flash_crash_2021",  "Leveraged long wipeout",           -0.30, 30, 4),
    CrisisScenario("china_ban_2021",        "Regulatory shock",                 -0.20, 25, 24),
    CrisisScenario("mt_gox_2014",           "Exchange hack & liquidation",      -0.40, 30, 168),
    CrisisScenario("eth_dao_hack_2016",     "Protocol exploit",                 -0.45, 30, 48),
    CrisisScenario("binance_hack_2019",     "CEX security breach",              -0.15, 25, 12),
    CrisisScenario("bitfinex_hack_2016",    "Exchange hack freeze",             -0.20, 25, 24),
    CrisisScenario("march_2020_liquidity",  "Dollar liquidity crisis",          -0.40, 80, 24),
    CrisisScenario("fed_rate_shock",        "Unexpected 100bps hike",           -0.20, 45, 72),
    CrisisScenario("stablecoin_depeg",      "Major stablecoin loses peg",       -0.35, 40, 24),
    CrisisScenario("whale_dump",            "Single entity 10B USD dump",       -0.15, 20, 4),
    CrisisScenario("network_congestion",    "Chain halt / fee spike",           -0.10, 20, 8),
    CrisisScenario("sec_action",            "SEC major enforcement action",     -0.20, 30, 48),
    CrisisScenario("global_war_shock",      "Geopolitical black swan",          -0.30, 70, 96),
]

def get_scenario(name: str) -> CrisisScenario | None:
    return next((s for s in SCENARIOS if s.name == name), None)
