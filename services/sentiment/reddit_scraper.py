import asyncio, json, os, praw
from kafka import KafkaProducer

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

class RedditScraper:
    def __init__(self):
        self.reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent=os.getenv("REDDIT_USER_AGENT", "prometheus/1.0"),
        )
        self.producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode()
        )
        self.subreddits = ["Bitcoin", "CryptoCurrency", "ethtrader", "CryptoMarkets"]

    async def run(self):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._stream)

    def _stream(self):
        sub = self.reddit.subreddit("+".join(self.subreddits))
        for post in sub.stream.submissions(skip_existing=True):
            self.producer.send("reddit_posts", {
                "title": post.title,
                "score": post.score,
                "subreddit": post.subreddit.display_name,
                "created_utc": post.created_utc,
            })
