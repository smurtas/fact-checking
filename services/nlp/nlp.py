from kafka import KafkaConsumer, KafkaProducer
from sentence_transformers import SentenceTransformer
from elasticsearch import Elasticsearch
import spacy  # to spleit text into sentences
import torch
from transformers import RobertaTokenizer, RobertaForSequenceClassification
from transformers import DebertaV2Tokenizer, DebertaV2ForSequenceClassification
import json, os, sys
import threading


# Set device: GPU if available, else CPU if Linux or MacOS
# device = torch.device("cuda" if torch.cuda.is_available() else "cpu") #linux 
device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")  # mac

#print(f"Using device: {device}")

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

# Uncomment the following lines if you have a local DeBERTa model
# This is useful if you have fine-tuned your model and saved it locally.
# # Load DeBERTa model
# deberta_model = DebertaV2ForSequenceClassification.from_pretrained(
#     "/app/ds_results", local_files_only=True
# )
# deberta_tokenizer = DebertaV2Tokenizer.from_pretrained(
#     "/app/ds_results", local_files_only=True
# )
# deberta_model.eval()

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
    threshold = 0.6 # Confidence threshold to consider a claim as true 
    for sentence in sentences:
        x = deberta_tokenizer.encode_plus(sentence, evidence, return_tensors="pt", truncation=True)
        x = {k: v.to(device) for k, v in x.items()}
        with torch.no_grad():
            prediction = deberta_model(**x)
            logits = prediction.logits
            probs = torch.nn.functional.softmax(logits, dim=1)
        label = torch.argmax(prediction.logits, dim=1).item()
        confidence = probs.max().item()

        # with a trained model, we can adjust the label based on confidence
        # Adjust label based on confidence threshold
        if label == 1 and confidence < threshold:
            adjusted_label = 0
        else:
            adjusted_label = label

        # # but for now we just return the label and confidence
        # if confidence < threshold:
        #     adjusted_label = -1  # claim incerta
        # else:
        #     adjusted_label = label

        results.append({
            "text": sentence,
            "label": adjusted_label,
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
        x = {k: v.to(device) for k, v in x.items()}
        with torch.no_grad():
            prediction = fact_model(**x)
            logits = prediction.logits
            probs = torch.nn.functional.softmax(logits, dim=1)
        label = torch.argmax(prediction.logits, dim=1).item()
        confidence = probs.max().item()
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
def handle_cleaned_doc():
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
            es.indices.create(index="news_facts", ignore=400)
            es.index(index="news_facts", id=doc["id"], body=nlp_output)
            print(f"NLP: {doc['id']} - {len(flagged_claims)} false claims flagged", flush=True)
        except Exception as e:
            print(f"❌ Indexing error for {doc['id']}: {e}", flush=True)

# Function to handle manual claims from Kafka
def handle_manual_claims():
    manual_consumer = KafkaConsumer(
        'manual_claims',
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
        auto_offset_reset='earliest',
        enable_auto_commit=True,
        group_id='nlp-manual',
        value_deserializer=lambda x: json.loads(x.decode('utf-8'))
    )

    print("✅ NLP manual claim listener ready", flush=True)
    for msg in manual_consumer:
        claim = msg.value
        claim_text = claim["claim"]
        #evidence = claim.get("evidence", "") or claim_text  # fallback
        evidence = get_best_evidence(claim_text)  # Get best evidence from Elasticsearch

        # DeBERTa
        deberta_results = score_claims_with_deberta([claim_text], evidence)
        deberta_label = deberta_results[0]["label"]
        deberta_confidence = deberta_results[0]["confidence"]


        # RoBERTa
        roberta_results = score_claims_with_roberta([claim_text], evidence)
        roberta_label = roberta_results[0]["label"]

        #final_label = 0 if deberta_label == 0 or roberta_label == 0 else 1
        # Debugging output
        print("🔍 DEBUG CLAIM INFERENCE")
        print(f"📌 Claim: {claim_text}")
        print(f"📚 Evidence: {evidence}")
        print(f"✅ Labels: DeBERTa={deberta_label}, RoBERTa={roberta_label}")
        print(f"🔎 Confidence: DeBERTa={deberta_confidence:.2f}")


        # Give priority to DeBERTa, if it says false, we trust it
        if deberta_label == 1:
            final_label = 1
            reason = "✅ DeBERTa predicted True (priority model)"
        elif roberta_label == 1:
            final_label = 1
            reason = "⚠️ DeBERTa=False, but RoBERTa predicted True"
        else:
            final_label = 0
            reason = "❌ Both models predicted False"


        result = {
            "id": claim["id"],
            "claim": claim_text,
            "label": final_label,
            "models": {
                "deberta": deberta_label,
                "roberta": roberta_label
            },
            "reason": reason  # Optional, for better debugging/logging
        }

        producer.send("manual_results", result)
        print(f"📤 NLP sent result for manual claim {claim['id']}", flush=True)

# Function to get best evidence from Elasticsearch
def get_best_evidence(claim_text):
    try:
        query = {
            "query": {
                "match": {
                    "content": claim_text
                }
            },
            "size": 1
        }
        res = es.search(index="news_facts", body=query)
        if res["hits"]["hits"]:
            return res["hits"]["hits"][0]["_source"].get("content", claim_text)
    except Exception as e:
        print(f"⚠️ Elasticsearch error: {e}")
    return claim_text  # fallback



if __name__ == "__main__":
    print("🚀 Starting NLP microservice listeners...", flush=True)

    t1 = threading.Thread(target=handle_cleaned_doc)
    t2 = threading.Thread(target=handle_manual_claims)

    t1.start()
    t2.start()

    t1.join()
    t2.join()