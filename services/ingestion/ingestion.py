import requests, json, os
from kafka import KafkaProducer, KafkaConsumer
from datetime import datetime
from kafka.errors import KafkaTimeoutError
from time import sleep
import hashlib
import sys
sys.stdout.reconfigure(line_buffering=True)

# Kafka Producer setup
producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

consumer = KafkaConsumer(
    os.getenv("TOPIC_INPUT", "user_topic_request"),
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_deserializer=lambda m: m.decode("utf-8"),
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id="news-fetcher"
)

# Function to generate a unique ID for each article
def generate_id(article):
    unique_string = article["title"] + article["publishedAt"]
    return hashlib.md5(unique_string.encode("utf-8")).hexdigest()

def fetch_news(api_key, topic):
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

def main():
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
            for i in range(5):  # retry logic
                try:
                    producer.send("user_choice", article)  # it may be better to use a news.{topic} topic for a better scalability, but for now we decide to use a single topic
                    break
                except KafkaTimeoutError:
                    print(f"Kafka timeout... retrying ({i+1}/5)", flush=True)
                    sleep(2)
        producer.flush()

if __name__ == "__main__":
    main()
