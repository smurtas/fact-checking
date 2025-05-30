
import requests, json, os, uuid
from kafka import KafkaProducer
from datetime import datetime

producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

def fetch_media_cloud(api_key, topic_id):
    url = "https://api.mediacloud.org/api/v2/stories/list"
    params = {"key": api_key, "topics_id": topic_id, "rows": 10}
    res = requests.get(url, params=params).json()
    return [
        {
            "id": str(uuid.uuid4()),
            "source": s.get("url", ""),
            "title": s.get("title", ""),
            "content": s.get("text", ""),
            "published_at": s.get("publish_date", ""),
            "language": s.get("language", "en")
        } for s in res.get("stories", [])
    ]

def main():
    api_key = os.getenv("MEDIA_CLOUD_API_KEY")
    topic_id = 123456  # swop with my topic ID
    items = fetch_media_cloud(api_key, topic_id)
    for item in items:
        producer.send('raw_news', item)
        print(f"Inviata notizia: {item['title']}")
    producer.flush()

if __name__ == "__main__":
    main()
