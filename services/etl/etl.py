
import json, os
from kafka import KafkaConsumer, KafkaProducer
import re

def clean_text(text):
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

consumer = KafkaConsumer(
    'raw_news',
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id='etl-service',
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

for msg in consumer:
    doc = msg.value
    doc['cleaned_text'] = clean_text(doc.get('content', ''))
    producer.send('cleaned_doc', doc)
    print(f"ETL: Pulito e inviato {doc['id']}")