"""
ingestion.py

This script implements the **Ingestion Service** of the fact-checking system.
Its responsibility is to:
- Listen for topic requests from the frontend (via Kafka)
- Fetch relevant articles from NewsAPI based on the topic
- Preprocess and format those articles
- Send the cleaned articles to the next Kafka topic (`user_choice`) for ETL processing

This script is part of the **news-driven flow** in the pipeline.
"""

import requests, json, os
from kafka import KafkaProducer, KafkaConsumer
from datetime import datetime
from kafka.errors import KafkaTimeoutError
from time import sleep
import hashlib
import sys

# Ensure logs are printed immediately in Docker
sys.stdout.reconfigure(line_buffering=True)

# =============================
# Kafka Setup
# =============================

# Kafka Producer: sends fetched articles to the 'user_choice' topic
producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

# Kafka Consumer: listens to user requests on the 'user_topic_request' topic
consumer = KafkaConsumer(
    os.getenv("TOPIC_INPUT", "user_topic_request"),
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_deserializer=lambda m: m.decode("utf-8"),
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id="news-fetcher"
)

# =============================
# Utility Functions
# =============================
# Function to generate a unique ID for each article
def generate_id(article):
    """
    Generate a unique ID for each news article using MD5 hash of title + published date.
    This helps avoid duplicate entries and keeps article processing consistent.
    """
    title = article.get("title") or ""
    published = article.get("publishedAt") or ""
    unique_string = title + published
    return hashlib.md5(unique_string.encode()).hexdigest()


def fetch_news(api_key, topic):
    """
    Fetches news articles from NewsAPI filtered by a user-selected topic.
    
    Parameters:
        api_key (str): API key for accessing NewsAPI
        topic (str): Keyword or subject for news retrieval
    
    Returns:
        List[Dict]: Cleaned and structured article entries
    """
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": topic,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 100, # Adjust page size as needed - but newsApi has a limit of 100 per request in free tier
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
            "id": generate_id(a),
            "source": a["source"]["name"],
            "title": a["title"],
            "content": a.get("content", ""),
            "published_at": a["publishedAt"],
            "language": "en"
        } for a in articles
    ]


# =============================
# Main Execution Flow
# =============================
def main():
    """
    Entry point of the ingestion service:
    - Waits for topic requests via Kafka
    - Fetches news for each topic
    - Publishes articles to Kafka for downstream processing
    """
    api_key = os.getenv("NEWS_API_KEY")
    if not api_key:
        print("❌ NEWS_API_KEY is missing from environment.")
        return

    print("🟢 Ingestion service started. Waiting for topics...")
    for message in consumer:
        topic = message.value
        print(f"📥 Received topic: {topic}")

        articles = fetch_news(api_key, topic)

        for article in articles:
            # Retry logic for network/Kafka failure resilience
            for i in range(5):  # retry logic
                try:
                    # All articles go into the same topic (can be improved with partitioning)
                    producer.send("user_choice", article)  # it may be better to use a news.{topic} topic for a better scalability, but for now we decide to use a single topic
                    break
                except KafkaTimeoutError:
                    print(f"Kafka timeout... retrying ({i+1}/5)", flush=True)
                    sleep(2)
        producer.flush()  # Ensure all messages are sent before next loop

if __name__ == "__main__":
    main()
