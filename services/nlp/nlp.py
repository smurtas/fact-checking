from kafka import KafkaConsumer, KafkaProducer
from sentence_transformers import SentenceTransformer
from elasticsearch import Elasticsearch
import spacy  # to spleit text into sentences
import torch
from transformers import RobertaTokenizer, RobertaForSequenceClassification
from transformers import DebertaV2Tokenizer, DebertaV2ForSequenceClassification
import json, os, sys

# Flush stdout logs immediately
sys.stdout.reconfigure(line_buffering=True)

# Load NLP tools
nlp_spacy = spacy.load("en_core_web_sm")
embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
es = Elasticsearch("http://elasticsearch:9200")

# Load DeBERTa model
deberta_tokenizer = DebertaV2Tokenizer.from_pretrained("microsoft/deberta-v3-large")
deberta_model = DebertaV2ForSequenceClassification.from_pretrained("microsoft/deberta-v3-large")
deberta_model.eval()

# Load RoBERTa-based fact-check model
tokenizer = RobertaTokenizer.from_pretrained('Dzeniks/roberta-fact-check')
fact_model = RobertaForSequenceClassification.from_pretrained('Dzeniks/roberta-fact-check')
fact_model.eval()

# Function to score claims using DeBERTa
# This function takes a list of sentences and an evidence string, and returns a list of dictionaries
# with the sentence text, predicted label (0 for false, 1 for true), and confidence score.
# The confidence score is the maximum probability of the predicted label.

def score_claims_with_deberta(sentences, evidence):
    results = []
    for sentence in sentences:
        x = deberta_tokenizer.encode_plus(sentence, evidence, return_tensors="pt", truncation=True)
        with torch.no_grad():
            prediction = deberta_model(**x)
            probs = torch.nn.functional.softmax(prediction.logits, dim=1)
        label = torch.argmax(prediction.logits, dim=1).item()
        confidence = probs.max().item()
        results.append({
            "text": sentence,
            "label": label,
            "confidence": round(confidence, 2)
        })
    return results

# Function to score claims using RoBERTa
# This function takes a list of sentences and an evidence string, and returns a list of dictionaries
# with the sentence text and predicted label (0 for false, 1 for true).
# It uses the pretrained RoBERTa model to classify the claims based on the evidence provided
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

    # Apply fact-checking models
    # Use DeBERTa for initial claim scoring
 
    # Step 1: run DeBERTa on all
    deberta_results = score_claims_with_deberta(sentences, content)

    # Step 2: run RoBERTa only on flagged ones
    suspect_sentences = [c["text"] for c in deberta_results if c["label"] == 0]

    # Run RoBERTa only if needed
    if suspect_sentences:
        roberta_results = score_claims_with_roberta(suspect_sentences, content)
    else:
        roberta_results = []

    # Flagged claims (label == 0 means likely false)
    flagged_by_roberta = [c for c in roberta_results if c["label"] == 0]
    flagged_by_deberta = [c for c in deberta_results if c["label"] == 0]

    # Merge flagged claims (remove duplicates by text)
    flagged_claims = list({c["text"]: c for c in roberta_results + [
        c for c in deberta_results if c["label"] == 0
    ]}.values())

    # Build result
    nlp_output = {
        "id": doc["id"],
        "title": doc["title"],
        "content": content,
        "published_at": doc.get("published_at", ""),
        "embedding": embedding,
        "language": doc.get("language", "en"),
        "flagged_claims": flagged_claims,
        "debug": {
            "deberta": deberta_results,
            "roberta": roberta_results
        }
    }

    # Send to Kafka
    producer.send("nlp_output", nlp_output)

    # Store in Elasticsearch
    try:
        es.index(index="news_facts", id=doc["id"], body=nlp_output)
        print(f"NLP: {doc['id']} - {len(flagged_claims)} false claims flagged", flush=True)
    except Exception as e:
        print(f"❌ Indexing error for {doc['id']}: {e}", flush=True)

    consumer = KafkaConsumer("manual_claims", ...)
    producer = KafkaProducer(...)

    for msg in consumer:
        claim = msg.value
        result = {
            "id": claim["id"],
            "text": claim["claim"],
            "label": ...,  # risultato finale
            "model": "roberta + deberta"
        }
        producer.send("manual_results", result)
manual_consumer = KafkaConsumer(
    'manual_claims',
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id='nlp-manual',
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

for msg in manual_consumer:
    claim = msg.value
    claim_text = claim["claim"]
    evidence = claim.get("evidence", "")

    # Apply DeBERTa
    deberta_x = deberta_tokenizer.encode_plus(claim_text, evidence, return_tensors="pt", truncation=True)
    with torch.no_grad():
        deberta_pred = deberta_model(**deberta_x)
        deberta_label = torch.argmax(deberta_pred.logits, dim=1).item()

    # Apply RoBERTa
    roberta_x = tokenizer.encode_plus(claim_text, evidence, return_tensors="pt", truncation=True)
    with torch.no_grad():
        roberta_pred = fact_model(**roberta_x)
        roberta_label = torch.argmax(roberta_pred.logits, dim=1).item()

    final_label = 0 if deberta_label == 0 or roberta_label == 0 else 1

    result = {
        "id": claim["id"],
        "claim": claim_text,
        "label": final_label,
        "models": {
            "deberta": deberta_label,
            "roberta": roberta_label
        }
    }

    producer.send("manual_results", result)
    print(f"NLP → ✅ Result for manual claim {claim['id']} sent", flush=True)
