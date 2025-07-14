#!/bin/sh
set -e

KAFKA_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-kafka:9092}
echo "⏳ Waiting for Kafka at $KAFKA_SERVERS..."

RETRIES=30
for i in $(seq 1 $RETRIES); do
  python3 -c "
from kafka import KafkaProducer
try:
    KafkaProducer(bootstrap_servers='$KAFKA_SERVERS')
    print('Kafka is ready.')
except Exception as e:
    raise SystemExit(1)
" && break
  echo "⏱️  Kafka not ready yet... ($i/$RETRIES)"
  sleep 2
done

echo "🚀 Kafka is up - starting API service"
#exec uvicorn main:app --host 0.0.0.0 --port 8000
exec "$@"