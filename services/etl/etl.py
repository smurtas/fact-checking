
import json, os
from kafka import KafkaConsumer, KafkaProducer
import re
import sys
sys.stdout.reconfigure(line_buffering=True)

def clean_text(text):
    #Clean and normalize text by removing unwanted characters and links.
    text = re.sub(r'\s+', ' ', text)  # normalize spaces
    text = re.sub(r"http\S+", "", text)  # remove links
    text = re.sub(r"[^a-zA-Z0-9.,;:()!?\"' ]", "", text)  # remove strange characters
    return text.strip()

consumer = KafkaConsumer(
    'user_choice',
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id='etl-debug',
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

try: 
    for msg in consumer:
        doc = msg.value
        doc['cleaned_text'] = clean_text(doc.get('content', ''))
        producer.send('cleaned_doc', doc)
        print(f"ETL: Pulito e inviato {doc['id']}", flush=True)
except KeyboardInterrupt:
    print("ETL: Interrotto manualmente", flush=True)
except Exception as e:
    print(f"ETL: Errore durante l'elaborazione: {e}", flush=True)
finally:
    consumer.close()
    producer.close()
    print("ETL: Consumer e Producer chiusi", flush=True)
