import asyncio, logging
logging.basicConfig(level="INFO")

async def main():
    logging.info("signal_engine starting")
    await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
