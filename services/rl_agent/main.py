import asyncio, logging
from ppo_agent import PPOAgent

logging.basicConfig(level="INFO")

async def main():
    logging.info("rl_agent starting")
    agent = PPOAgent()
    agent.train(total_timesteps=1_000_000)

if __name__ == "__main__":
    asyncio.run(main())
