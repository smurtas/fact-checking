from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import JSONResponse
from kafka import KafkaProducer
import os, json

router = APIRouter()

producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

@router.get("/send-topic")
async def trigger_fetch_news(topic: str = Query(...)):
    if not topic:
        raise HTTPException(status_code=400, detail="Missing topic")

    producer.send("user_topic_request", topic)
    return {"message": f"✅ Topic '{topic}' sent to Kafka"}
