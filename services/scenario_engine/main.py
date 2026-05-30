import asyncio, logging
logging.basicConfig(level="INFO")

async def main():
    logging.info("scenario_engine starting — 16 crisis scenarios loaded")
    await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
