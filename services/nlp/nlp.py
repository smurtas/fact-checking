
from kafka import KafkaConsumer
from kafka import KafkaProducer
from sentence_transformers import SentenceTransformer
import json, os
from elasticsearch import Elasticsearch

consumer = KafkaConsumer(
    'cleaned_doc',
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id='nlp-service',
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
es = Elasticsearch("http://elasticsearch:9200")

for msg in consumer:
    doc = msg.value
    text = doc.get('cleaned_text', '')
    embedding = model.encode(text).tolist()

    nlp_output = {
        "id": doc["id"],
        "title": doc["title"],
        "content": doc["content"],
        "published_at": doc.get("published_at", ""),
        "embedding": embedding,
        "language": doc.get("language", "en")
    }

    # Send to  Kafka
    producer.send('nlp_output', nlp_output)

    # index in Elasticsearch
    es.index(index="news_facts", id=doc["id"], body=nlp_output)
    print(f"NLP: Embedding calcolato e indicizzato {doc['id']}")