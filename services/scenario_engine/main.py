import asyncio
import json
import logging
import os
import time

import asyncpg
import redis.asyncio as aioredis

from scenarios import SCENARIOS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
POSTGRES_URL = os.getenv("POSTGRES_URL", "")

# Run scenarios every 24 hours
RUN_INTERVAL = 86400


async def simulate_scenario(scenario, immunity_limits: dict) -> dict:
    """Simulate one crisis scenario against immunity system limits."""
    btc_shock = scenario.btc_shock
    vix_target = scenario.vix_target

    # Check if immunity system would catch this
    max_position_pct = immunity_limits.get("max_position_pct", 0.05)
    max_daily_loss = immunity_limits.get("max_daily_loss", 0.02)

    # Worst-case portfolio impact: full position × shock
    worst_case_impact = max_position_pct * abs(btc_shock)
    passed = worst_case_impact <= max_daily_loss

    # Estimate recovery time based on VIX
    recovery_time = max(60, int(scenario.duration_hours * 0.5))

    return {
        "scenario_id": scenario.name[:3].upper(),
        "scenario_name": scenario.name,
        "portfolio_impact_pct": worst_case_impact,
        "risk_engine_response": (
            f"Position capped at {max_position_pct:.0%} × shock={abs(btc_shock):.0%}"
        ),
        "recovery_time_min": recovery_time,
        "passed": passed,
        "details": {
            "btc_shock": btc_shock,
            "vix_target": vix_target,
            "duration_hours": scenario.duration_hours,
        },
    }


async def run_all_scenarios(redis: aioredis.Redis, db):
    log.info(f"Running {len(SCENARIOS)} crisis scenarios")
    immunity_limits = {
        "max_position_pct": 0.05,
        "max_daily_loss": 0.02,
        "max_leverage": 3.0,
    }
    results = []
    passed = 0
    for scenario in SCENARIOS:
        result = await simulate_scenario(scenario, immunity_limits)
        results.append(result)
        if result["passed"]:
            passed += 1

        if db:
            try:
                await db.execute("""
                    INSERT INTO scenario_results
                    (scenario_id, scenario_name, portfolio_impact_pct,
                     risk_engine_response, recovery_time_min, passed, details)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                    result["scenario_id"], result["scenario_name"],
                    result["portfolio_impact_pct"], result["risk_engine_response"],
                    result["recovery_time_min"], result["passed"],
                    json.dumps(result["details"])
                )
            except Exception as e:
                log.warning(f"DB insert error: {e}")

    summary = {
        "total": len(SCENARIOS),
        "passed": passed,
        "failed": len(SCENARIOS) - passed,
        "pass_rate": passed / len(SCENARIOS),
        "run_at": time.time(),
    }
    await redis.set("scenarios:latest_summary", json.dumps(summary), ex=86400)
    log.info(f"Scenario results: {passed}/{len(SCENARIOS)} passed ({summary['pass_rate']:.0%})")
    return summary


async def main():
    log.info(f"scenario_engine starting — {len(SCENARIOS)} crisis scenarios loaded")
    redis = await aioredis.from_url(REDIS_URL)

    db = None
    if POSTGRES_URL:
        try:
            db = await asyncpg.connect(POSTGRES_URL)
        except Exception as e:
            log.warning(f"DB connection failed: {e}")

    while True:
        await run_all_scenarios(redis, db)
        await asyncio.sleep(RUN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
