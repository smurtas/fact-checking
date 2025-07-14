from fastapi import FastAPI, Query, Request, HTTPException
from elasticsearch import Elasticsearch
import httpx
import os
#import torch
import json
#from transformers import RobertaTokenizer, RobertaForSequenceClassification , DebertaV2Tokenizer
from pydantic import BaseModel
from kafka import KafkaProducer
from fetch_news import router as fetch_news_router
import time
#from fastapi.middleware.cors import CORSMiddleware # to allow CORS requests from frontend 
# to be impreved, we should use a more secure way to handle CORS in production

#from transformers import AutoTokenizer, AutoModelForSequenceClassification


# === DeBERTa model  to be removed===

# deberta_tokenizer = DebertaV2Tokenizer.from_pretrained("microsoft/deberta-v3-large")
# # Load the DeBERTa model for sequence classification
# # Ensure you have the correct model for your task, e.g., sentiment analysis, fact-checking, etc.
# # You can replace "microsoft/deberta-v3-large" with the appropriate model name if needed.
# # here we use a large model, but with use_fast=False to avoid issues with the tokenizer
# deberta_model = AutoModelForSequenceClassification.from_pretrained("microsoft/deberta-v3-large") 

# === FastAPI App ===
app = FastAPI()
#app.include_router(fetch_news_router)

# === Elasticsearch ===
es = Elasticsearch("http://elasticsearch:9200")

# === Google API ===
GOOGLE_FACT_CHECK_API_KEY = os.getenv("GOOGLE_FACT_CHECK_API_KEY")

# === Kafka Producer ===
producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

# === API Models ===
class ClaimRequest(BaseModel):
    claim: str
    evidence: str = ""



class TopicRequest(BaseModel):
    topic: str

@app.post("/send-topic")
async def send_topic(data: TopicRequest):
    producer.send("user_topic_request", data.topic)
    return {"message": f"✅ Topic '{data.topic}' sent to Kafka"}

# to be removed, we use deberta_check instead
# @app.post("/roberta-check")
# def roberta_check(data: ClaimRequest):
#     x = tokenizer.encode_plus(data.claim, data.evidence, return_tensors="pt", truncation=True)
#     with torch.no_grad():
#         prediction = model(**x)
#     label = torch.argmax(prediction.logits, dim=1).item()
#     return {"claim": data.claim, "label": label}  # 0 = False, 1 = True

@app.get("/fetch-news")
async def latest_news(
    query: str = Query("", description="Search text"),
    topic: str = Query("", description="Topic filter"),
    language: str = Query("en", description="Language code")
):
    must_clauses = []

    if query:
        must_clauses.append({
            "multi_match": {
                "query": query,
                "fields": ["title", "content"]
            }
        })

    if topic:
        must_clauses.append({"match": {"title": topic}})
    if language:
        must_clauses.append({"match": {"language": language}})

    es_query = {
        "query": {
            "bool": {
                "must": must_clauses
            }
        },
        "size": 10,
        "sort": [{"published_at": {"order": "desc"}}]
    }

    res = es.search(index="news_facts", body=es_query)
    articles = [hit["_source"] for hit in res["hits"]["hits"]]
    return articles

@app.get("/fact-check")
async def fact_check(query: str = Query(...), languageCode: str = "en"):
    if not GOOGLE_FACT_CHECK_API_KEY:
        return {"error": "Missing Google API key"}

    url = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
    params = {
        "query": query,
        "key": GOOGLE_FACT_CHECK_API_KEY,
        "languageCode": languageCode
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        if response.status_code != 200:
            return {"error": response.text}
        return response.json()

# to be removed, we use deberta_check instead

# @app.post("/deberta-check")
# def deberta_check(data: ClaimRequest):
#     x = deberta_tokenizer.encode_plus(data.claim, data.evidence, return_tensors="pt", truncation=True)
#     with torch.no_grad():
#         prediction = deberta_model(**x)
#     label = torch.argmax(prediction.logits, dim=1).item()
#     return {"claim": data.claim, "label": label}  # 0 = False, 1 = True

@app.post("/check-claim-kafka")
async def check_claim_kafka(data: ClaimRequest):
    claim_id = str(uuid.uuid4())
    message = {"id": claim_id, "claim": data.claim, "evidence": data.evidence}

    # Send the claim to the Kafka topic for NLP processing
    producer.send("manual_claims", message)
    producer.flush()

    # wait for NLP result 
    timeout = 10  # sec
    result = wait_for_nlp_response(claim_id, timeout)
    if not result:
        raise HTTPException(status_code=504, detail="No response from NLP in time")
    return result

def wait_for_nlp_response(claim_id, timeout=10):
    consumer = KafkaConsumer(
        'manual_results',
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
        auto_offset_reset='earliest',
        enable_auto_commit=False,
        group_id='api-waiter',
        value_deserializer=lambda x: json.loads(x.decode('utf-8'))
    )

    start = time.time()
    for msg in consumer:
        result = msg.value
        if result.get("id") == claim_id:
            return result
        if time.time() - start > timeout:
            return None
