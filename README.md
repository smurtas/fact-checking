
# 🕵️ Fact-Checking Dashboard

This is a full-stack big data system for real-time fact-checking of news articles. It combines Natural Language Processing (NLP), pretrained models, and external APIs (like Google's Fact Check Tools API) to identify and verify potentially misleading claims in the media.

---

## 📦 Features

- **News ingestion** from various sources using Kafka pipelines.
- **Claim detection** using spaCy and ClaimBuster.
- **Fact classification** using fine-tuned [RoBERTa](https://huggingface.co/Dzeniks/roberta-fact-check).
- **Cross-verification** using Google Fact Check Tools API.
- **Elasticsearch indexing** for fast search and retrieval.
- **Streamlit frontend** with search, filters, and multilingual support.

---

## 🧱 Architecture


[News APIs] --> [Kafka Ingestion] --> [ETL] --> [NLP w/ RoBERTa + ClaimBuster]
|
[Elasticsearch]
|
[FastAPI Backend] <--------> [Google FactCheck API]
|
[Streamlit Frontend UI]


---

## 🚀 Setup & Installation

### 1. Clone the Repository

git clone https://github.com/smurtas/fact-checking.git 
cd fact-checking-dashboard```


### 2. Set Up Environment Variables
Create a .env file in the root and add:

NEWS_API_KEY=your_news_api_key
GOOGLE_FACT_CHECK_API_KEY=your_google_fact_check_api_key

Make sure your Google API key has access to the Fact Check Tools API.

docker-compose up --build

### 3. Build & Run with Docker Compose

docker-compose up --build

#### This spins up:

- elasticsearch
- zookeeper
- kafka
- api (FastAPI)
- nlp (RoBERTa + ClaimBuster)
- etl (Cleaner and dispatcher)
- ingestion (News fetcher)
- frontend (Streamlit app on port 8501)

## 🖥️ Usage
Visit the dashboard at:
http://localhost:8501

Core Features:
- Latest News: Displays fact-checked articles.
- Flagged Claims: Shows suspicious sentences and model predictions.
- Manual Claim Check: Enter any sentence to verify via Google API + RoBERTa model.

## 🤖 Models Used
- Dzeniks/roberta-fact-check
- spaCy NLP pipeline (en_core_web_sm)
- ClaimBuster

## 🧪 Testing
To manually test the system:

curl -X GET "http://localhost:8000/fact-check?query=Obama+was+born+in+Kenya"
To verify RoBERTa:

from transformers import RobertaTokenizer, RobertaForSequenceClassification
import torch

tokenizer = RobertaTokenizer.from_pretrained('Dzeniks/roberta-fact-check')
model = RobertaForSequenceClassification.from_pretrained('Dzeniks/roberta-fact-check')

model.eval()
x = tokenizer.encode_plus("Vaccines cause autism", "", return_tensors="pt")
with torch.no_grad():
    logits = model(**x).logits
print(torch.argmax(logits, dim=1).item())  # 0 = False, 1 = True

## 🛠️ Future Improvements
Fine-tune RoBERTa on more fact-check data

Add claim clustering (similar claims)

Integrate external structured databases (e.g., Wikidata)

## 📄 License
MIT © Stefano Murtas