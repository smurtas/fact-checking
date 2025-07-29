"""
api_service.py

This module defines the main API service for the fact-checking application.
It is responsible for handling user interaction via FastAPI endpoints, including:
- Submitting topic requests for news ingestion
- Querying news from Elasticsearch
- Fact-checking claims using Google Fact Check API
- Submitting manual claims to Kafka for NLP processing
- Waiting for results from Kafka and saving to DuckDB

Services used:
- Elasticsearch for article storage and retrieval
- Kafka for decoupled communication between microservices
- DuckDB for lightweight result logging
"""

from fastapi import FastAPI, Query, Request, HTTPException
from elasticsearch import Elasticsearch
import httpx
import os
import sys
import json
from pydantic import BaseModel
from kafka import KafkaProducer, KafkaConsumer, TopicPartition
import time
import uuid
from services.database.claims_db import save_check , init_db # to save the claim check results

# =========================
# Initialization Section
# =========================

# Initialize DuckDB to log user queries and predictions
init_db()

# Initialize FastAPI App istance 
app = FastAPI()

# Connect to Elasticsearch instance
es = Elasticsearch("http://elasticsearch:9200")

# Load Google Fact Check API Key from environment
GOOGLE_FACT_CHECK_API_KEY = os.getenv("GOOGLE_FACT_CHECK_API_KEY")

# Set up Kafka producer for publishing to Kafka topics
producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

# =============================
# Data Models for API Inputs
# =============================
class ClaimRequest(BaseModel):
    """
    Request model for submitting a factual claim.
    Attributes:
        claim (str): The text of the claim to check.
        evidence (str): Optional additional context or support material.
    """
    claim: str
    evidence: str = ""


class TopicRequest(BaseModel):
    """
    Request model for submitting a topic to fetch news.
    Attributes:
        topic (str): The topic or keyword to fetch articles for.
    """
    topic: str

# =========================
# API Endpoint: Topic Push
# =========================
@app.post("/send-topic")
async def send_topic(data: TopicRequest):
    """
    Publish a user-selected topic to Kafka for ingestion.
    
    Args:
        data (TopicRequest): The topic request object with 'topic'.
        
    Returns:
        dict: A success message indicating topic submission.
    """
    producer.send("user_topic_request", data.topic)
    return {"message": f"✅ Topic '{data.topic}' sent to Kafka"}


# ====================================
# API Endpoint: Search News Articles
# ====================================
@app.get("/fetch-news")
async def latest_news(
    query: str = Query("", description="Search text"),
    topic: str = Query("", description="Topic filter"),
    language: str = Query("en", description="Language code")
):
    """
    Retrieve recent news articles from Elasticsearch based on filters.

    Args:
        query (str): Search keywords for title/content.
        topic (str): Specific topic to match in article title.
        language (str): Language filter, default is English.

    Returns:
        List[dict]: List of matching news articles.
    """
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

# ====================================================
# API Endpoint: External Google Fact Check Query API
# ====================================================
@app.get("/fact-check")
async def fact_check(query: str = Query(...), languageCode: str = "en"):
    """
    Query Google's Fact Check API for external validation of a claim.

    Args:
        query (str): The claim or statement to check.
        languageCode (str): Language code (default is 'en').

    Returns:
        dict: API response from Google Fact Check tools.
    """
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

# ==============================================
# API Endpoint: Submit Claim for NLP Check
# ==============================================
@app.post("/check-claim-kafka")
async def check_claim_kafka(data: ClaimRequest):
    """
    Submit a manual claim to Kafka, wait for NLP prediction, and store results.

    Args:
        data (ClaimRequest): Claim text and optional evidence.

    Returns:
        dict: NLP model's prediction result.
    """
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
    
    save_check(data.claim, result.get("label"), "roberta + deberta")  # save the result to the duckdb

    return result

# =====================================================
# Utility: Wait for NLP Result on Kafka Topic
# =====================================================
def wait_for_nlp_response(claim_id, timeout=20):
    """
    Listen for the response from the NLP service on the Kafka 'manual_results' topic.

    Args:
        claim_id (str): Unique ID used to match the response.
        timeout (int): Max seconds to wait for a reply.

    Returns:
        dict or None: NLP response message or None if timed out.
    """
    topic='manual_results'
    consumer = KafkaConsumer(
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
        auto_offset_reset='latest',
        enable_auto_commit=False,
        group_id=f'api-waiter-{claim_id}',
        value_deserializer=lambda x: json.loads(x.decode('utf-8'))
    )
    # Read only from latest messages
    tp = TopicPartition(topic, 0)
    consumer.assign([tp])
    consumer.seek_to_end(tp)

    start = time.time()
    for msg in consumer:
        result = msg.value
        if result.get("id") == claim_id:
            return result
        if time.time() - start > timeout:
            return None
        
    consumer.close()
    return None
