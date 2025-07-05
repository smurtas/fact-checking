import requests, json, os, uuid
from kafka import KafkaProducer
from datetime import datetime
from kafka.errors import KafkaTimeoutError  # Import KafkaTimeoutError for handling retries
from time import sleep  # Import sleep for retry logic
import sys
sys.stdout.reconfigure(line_buffering=True)# to get the message in stdout

# # This script fetches news articles from the News API and sends them to a Kafka topic.
# Kafka Producer setup

producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

def fetch_news(api_key, topic="election"):
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": topic,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 10,
        "apiKey": api_key
    }

    res = requests.get(url, params=params)
    print(f"🔎 Request URL: {res.url}")

    if res.status_code != 200:
        print(f"Error {res.status_code}: {res.text}", flush=True)
        return []

    data = res.json()
    articles = data.get("articles", [])
    print(f"🔍 Found {len(articles)} articles")

    return [
        {
            "id": str(uuid.uuid4()),
            "source": a["source"]["name"],
            "title": a["title"],
            "content": a.get("content", ""),
            "published_at": a["publishedAt"],
            "language": "en"
        } for a in articles
    ]

def main():
    api_key = os.getenv("NEWS_API_KEY")
    if not api_key:
        print("NEWS_API_KEY is missing from environment.")
        return

    topic = os.getenv("NEWS_TOPIC", "misinformation")  # Optional env override
    #articles = fetch_news(api_key, topic)

    # For testing purposes, we will use a static article
    # Uncomment the line below to fetch real articles
    # articles = fetch_news(api_key, topic)
    # For now, we will use a static article to simulate the process
    articles = [{
        "id": str(uuid.uuid4()),
        "source": "test",
        "title": "Vaccine Misinformation",
        "content": "The COVID-19 vaccine causes autism.",
        "published_at": datetime.utcnow().isoformat(),
        "language": "en"
    }]
    for article in articles:
        for i in range(5):  # max 5 retries add to wait for Kafka
            try:
                producer.send("raw_news", article)
                break
            except KafkaTimeoutError:
                print(f"Kafka timeout... retrying ({i+1}/5)", flush=True) # Retry logic 
                sleep(2)
    producer.flush()

if __name__ == "__main__":
    main()
