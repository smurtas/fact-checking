
from fastapi import FastAPI
from elasticsearch import Elasticsearch

app = FastAPI()
es = Elasticsearch("http://elasticsearch:9200")

@app.get("/latest-news")
def latest_news():
    res = es.search(index="news_facts", size=10, sort="published_at:desc")
    return [hit["_source"] for hit in res["hits"]["hits"]]