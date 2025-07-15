
# 🕵️ Fact-Checking Dashboard

This is a full-stack big data system for real-time fact-checking of news articles. It combines Natural Language Processing (NLP), pretrained models, and external APIs (like Google's Fact Check Tools API) to identify and verify potentially misleading claims in the media.

---

## 📦 Features

- **News ingestion**  via Kafka pipelines.
- **Claim detection** using spaCy and rule-based logic.
- **Fact classification** using fine-tuned [DeBERTa](https://huggingface.co/microsoft/deberta-v3-large) [RoBERTa](https://huggingface.co/Dzeniks/roberta-fact-check).
- **Cross-verification** using Google Fact Check Tools API.
- **Elasticsearch indexing** for fast search and article retrieval.
- **Streamlit frontend** with search, filters, and multilingual support.
- **DuckDB** for tracking manual checks.

---

## 🧱 Architecture

A [News APIs] --> B[Kafka Ingestion]
B --> C[ETL & Cleaning]
C --> D[NLP Pipeline (spaCy, RoBERTa, DeBERTa)]
D --> E[Elasticsearch]
D --> F[Kafka Manual Results]
F --> G[FastAPI Backend]
G --> H[Google Fact Check API]
G --> I[DuckDB History DB]
G --> J[Streamlit Frontend]


---

## 🚀 Setup & Installation

### 1. Clone the Repository

git clone https://github.com/smurtas/fact-checking.git 
cd fact-checking-dashboard```


### 2. Set Up Environment Variables
Create a .env file in the root and add:

# Required API Keys
#MEDIA_CLOUD_API_KEY=<apiKey>
NEWS_API_KEY=your_news_api_key_here
CLAIMBUSTER_API_KEY=your_claimbuster_api_key_here
GOOGLE_FACT_CHECK_API_KEY=your_google_fact_check_api_key_here
TOPIC_INPUT=user_topic_request

# Optional configurations
NEWS_TOPIC=misinformation  # Optional
LANGUAGE_CODE=en  # Optional, default is 'en' for English

# Internal configurations
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
API_URL=http://api:8000
ELASTICSEARCH_URL=http://elasticsearch:9200  # Optional, default is 'http://elasticsearch:9200'

Make sure your Google API key has access to the Fact Check Tools API.

docker-compose up --build

### 3. Build & Run with Docker Compose

docker-compose up --build

#### This spins up:

- elasticsearch
- kafka + zookeper
- api (FastAPI)
- nlp (RoBERTa + DeBERTa)
- etl (Cleaner and dispatcher)
- ingestion (News fetcher via APIs)
- frontend (Streamlit app on port 8501)

## 🖥️ Usage
Visit the dashboard at:
http://localhost:8501

Core Features in Tabs:
- Check Claims News: enter a claim, verified via Google, and in second istance with NLP models
- History: view the history of checked (via Google APIs or NLPs)
- Load Filterd News: get news articles by topic & language, with predictions

## 🤖 Models Used
- Dzeniks/roberta-fact-check
- microsoft/deberta-v3-large
- spaCy NLP pipeline (en_core_web_sm) for sentence splitting


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

🧠 Fine-tune DeBERTa and RoBERTa on multilingual fact-check data
🔗 Integrate structured sources like Wikidata
🧩 Add claim clustering to group similar claims
📉 UI improvements: trend charts, model confidence bars

## 📄 License
MIT © Stefano Murtas