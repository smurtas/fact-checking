"""
etl.py

This script is part of the fact-checking pipeline.
It consumes raw news articles from a Kafka topic (`user_choice`),
cleans the content text to remove noise, and republishes the cleaned
document to a new Kafka topic (`cleaned_doc`) for further NLP processing.

The ETL step is essential to improve downstream model accuracy by reducing
unnecessary or misleading characters, links, and formatting from the input.

Components:
- KafkaConsumer: reads raw article data
- clean_text(): performs regex-based normalization
- KafkaProducer: sends cleaned output to the next stage
"""

import json, os
from kafka import KafkaConsumer, KafkaProducer
import re
import sys
# Ensure that standard output is line-buffered so logs and print statements
# are immediately flushed and visible in real time. This is especially useful
# in Docker or streaming environments where delayed output can hinder debugging.
sys.stdout.reconfigure(line_buffering=True)

# =====================
# Text Cleaning Logic
# =====================

#Clean and normalize text by removing unwanted characters and links.
def clean_text(text):
    """
    Cleans and normalizes article text content.

    Steps:
    - Replaces multiple whitespace characters with single space
    - Removes URLs
    - Removes non-alphanumeric characters except basic punctuation

    Args:
        text (str): Raw article content

    Returns:
        str: Cleaned, normalized string
    """
 
    text = re.sub(r'\s+', ' ', text)  # normalize spaces
    text = re.sub(r"http\S+", "", text)  # remove links
    text = re.sub(r"[^a-zA-Z0-9.,;:()!?\"' ]", "", text)  # remove strange characters
    return text.strip()

# ==============================
# Kafka Setup: Consumer/Producer
# ==============================

# Kafka Consumer to read from 'user_choice' topic (articles from ingestion)
consumer = KafkaConsumer(
    'user_choice',
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id='etl-debug',
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

# Kafka Producer to publish cleaned content to 'cleaned_doc' topic
producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

# ==============================
# Main ETL Processing Loop
# ==============================
try: 
    for msg in consumer:
        doc = msg.value #get the raw article data
        # add a new field with cleaned text 
        doc['cleaned_text'] = clean_text(doc.get('content', '')) 

        # Send cleaned document to next pipeline stage
        producer.send('cleaned_doc', doc)


        print(f"ETL: Pulito e inviato {doc['id']}", flush=True)
except KeyboardInterrupt:
    print("ETL: Interrotto manualmente", flush=True)
except Exception as e:
    print(f"ETL: Errore durante l'elaborazione: {e}", flush=True)
finally:

    # Close consumer and producer connections gracefully
    consumer.close()
    producer.close()
    print("ETL: Consumer e Producer chiusi", flush=True)
