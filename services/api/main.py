from fastapi import FastAPI, Query
from elasticsearch import Elasticsearch
import httpx
import os
import torch
from transformers import RobertaTokenizer, RobertaForSequenceClassification
from pydantic import BaseModel



app = FastAPI()
es = Elasticsearch("http://elasticsearch:9200")

GOOGLE_FACT_CHECK_API_KEY = os.getenv("GOOGLE_FACT_CHECK_API_KEY")

# Load model once
tokenizer = RobertaTokenizer.from_pretrained('Dzeniks/roberta-fact-check')
model = RobertaForSequenceClassification.from_pretrained('Dzeniks/roberta-fact-check')
model.eval()

class ClaimRequest(BaseModel):
    claim: str
    evidence: str = ""

@app.post("/roberta-check")
def roberta_check(data: ClaimRequest):
    x = tokenizer.encode_plus(data.claim, data.evidence, return_tensors="pt", truncation=True)
    with torch.no_grad():
        prediction = model(**x)
    label = torch.argmax(prediction.logits, dim=1).item()
    return {"claim": data.claim, "label": label}  # 0 = False, 1 = True

@app.get("/latest-news")
async def latest_news(
    query: str = Query("", description="Search text"),
    topic: str = Query("", description="Topic filter"),
    language: str = Query("en", description="Language code")
):
    # --- Build dynamic query ---
    must_clauses = []

    if query:
        must_clauses.append({
            "multi_match": {
                "query": query,
                "fields": ["title", "content"]
            }
        })

    if topic:
        must_clauses.append({
            "match": {
                "title": topic
            }
        })

    if language:
        must_clauses.append({
            "match": {
                "language": language
            }
        })

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

    # --- Fact check enrichment ---
    
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

