from kafka import KafkaConsumer, KafkaProducer
from sentence_transformers import SentenceTransformer
from elasticsearch import Elasticsearch
import spacy
import torch
from transformers import RobertaTokenizer, RobertaForSequenceClassification
import json, os, sys

# Flush stdout logs immediately
sys.stdout.reconfigure(line_buffering=True)

# Load NLP tools
nlp_spacy = spacy.load("en_core_web_sm")
embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
es = Elasticsearch("http://elasticsearch:9200")

# Load RoBERTa-based fact-check model
tokenizer = RobertaTokenizer.from_pretrained('Dzeniks/roberta-fact-check')
fact_model = RobertaForSequenceClassification.from_pretrained('Dzeniks/roberta-fact-check')
fact_model.eval()

def score_claims_with_roberta(sentences, evidence):
    """
    Use pretrained RoBERTa model to label claims:
    Label 0 = False, 1 = True
    """
    results = []
    for sentence in sentences:
        x = tokenizer.encode_plus(sentence, evidence, return_tensors="pt", truncation=True)
        with torch.no_grad():
            prediction = fact_model(**x)
        label = torch.argmax(prediction.logits, dim=1).item()
        results.append({
            "text": sentence,
            "label": label
        })
    return results

# Kafka setup
consumer = KafkaConsumer(
    'cleaned_doc',
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id='nlp-service',
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

# Main pipeline
for msg in consumer:
    doc = msg.value
    content = doc.get('content', '')
    embedding = embedding_model.encode(doc.get('cleaned_text', '')).tolist()

    # Sentence extraction
    spacy_doc = nlp_spacy(content)
    sentences = [sent.text.strip() for sent in spacy_doc.sents if len(sent.text.strip()) > 20]

    # Apply fact-check model
    claim_scores = score_claims_with_roberta(sentences, content)
    flagged_claims = [c for c in claim_scores if c["label"] == 0]  # label 0 = likely false

    # Prepare output
    nlp_output = {
        "id": doc["id"],
        "title": doc["title"],
        "content": content,
        "published_at": doc.get("published_at", ""),
        "embedding": embedding,
        "language": doc.get("language", "en"),
        "flagged_claims": flagged_claims
    }

    # Send to Kafka
    producer.send("nlp_output", nlp_output)

    # Store in Elasticsearch
    try:
        es.index(index="news_facts", id=doc["id"], body=nlp_output)
        print(f"NLP: Indexed and flagged {len(flagged_claims)} claims in article {doc['id']}", flush=True)
    except Exception as e:
        print(f"Elasticsearch indexing error for {doc['id']}: {e}", flush=True)
