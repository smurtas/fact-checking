
#!/bin/sh
set -e

echo "Waiting for Kafka at $KAFKA_BOOTSTRAP_SERVERS..."

until echo > /dev/tcp/kafka/9092 2>/dev/null; do
  echo "Kafka is not ready yet..."
  sleep 2
done

echo "Kafka is up - starting ETL"
exec python etl.py
