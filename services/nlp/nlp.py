"""
nlp_service.py

This is the **NLP microservice** for the fact-checking system.

Responsibilities:
- Ingest cleaned news articles from Kafka
- Break articles into sentences and run claim verification using:
    - DeBERTa (for priority scoring)
    - RoBERTa (as secondary validator)
- Process manual claims from users via Kafka
- Store fact-checked results in Elasticsearch
- Stream results back to the pipeline via Kafka

Key Features:
- Multi-model NLP pipeline with DeBERTa + RoBERTa
- Real-time Kafka integration for automated and manual processing
- Scalable and concurrent using threads
- Embedding and evidence search through Elasticsearch

Dependencies:
- HuggingFace Transformers, SentenceTransformers, Spacy, Elasticsearch, Kafka-Python
"""

from kafka import KafkaConsumer, KafkaProducer
from sentence_transformers import SentenceTransformer
from elasticsearch import Elasticsearch
import spacy  # to spleit text into sentences
import torch
#from transformers import RobertaTokenizer, RobertaForSequenceClassification
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from transformers import DebertaV2Tokenizer, DebertaV2ForSequenceClassification
import json, os, sys
import threading
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import time



# Set device: GPU if available, else CPU if Linux or MacOS
# device = torch.device("cuda" if torch.cuda.is_available() else "cpu") #linux 
device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")  # mac

#print(f"Using device: {device}")

# Flush stdout logs immediately
sys.stdout.reconfigure(line_buffering=True)

# === Global thresholds for confidence scoring ===
DEBERTA_THRESHOLD = 0.65  # modify here to be more sure
ROBERTA_THRESHOLD = 0.65  # modify here to be more sure

# Load NLP tools
nlp_spacy = spacy.load("en_core_web_sm")
embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

# Elasticsearch instance (used for evidence retrieval and news storage)
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
# tokenizer = RobertaTokenizer.from_pretrained('Dzeniks/roberta-fact-check')
# fact_model = RobertaForSequenceClassification.from_pretrained('Dzeniks/roberta-fact-check')
# fact_model.eval()

# Load RoBERTa-based fact-check model trained with Fever
roberta_tokenizer = AutoTokenizer.from_pretrained(
   "ynie/roberta-large-snli_mnli_fever_anli_R1_R2_R3-nli"
)
roberta_model = AutoModelForSequenceClassification.from_pretrained(
   "ynie/roberta-large-snli_mnli_fever_anli_R1_R2_R3-nli"
)
roberta_model.eval()


# Function to score claims using DeBERTa
# This function takes a list of sentences and an evidence string, and returns a list of dictionaries
# with the sentence text, predicted label (0 for false, 1 for true), and confidence score.
# The confidence score is the maximum probability of the predicted label.

def score_claims_with_deberta(sentences, evidence):
    results = []
    #threshold = 0.85 # Confidence threshold to consider a claim as true 

    for sentence in sentences:
        x = deberta_tokenizer.encode_plus(sentence, evidence, return_tensors="pt", truncation=True, max_length=512)
        x = {k: v.to(device) for k, v in x.items()}
        with torch.no_grad():
            prediction = deberta_model(**x)
            logits = prediction.logits
            probs = torch.nn.functional.softmax(logits, dim=1)
        label = torch.argmax(prediction.logits, dim=1).item()
        confidence = probs.max().item()

        # with a trained model, we can adjust the label based on confidence
        # Adjust label based on confidence threshold
        if label == 1 and confidence < DEBERTA_THRESHOLD:
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
    Evaluates claims using a pretrained RoBERTa NLI model.
    Interpretation of output labels:
    - 0 = Contradiction → Claim is likely FALSE
    - 1 = Neutral       → Not enough evidence (treated as FALSE by default)
    - 2 = Entailment    → Claim is likely TRUE
    Only 'Entailment' with high confidence is considered TRUE.
    """
    results = []
    #threshold = 0.85  # Confidence threshold for True prediction

    for sentence in sentences:
        x = roberta_tokenizer.encode_plus(sentence, evidence, return_tensors="pt", truncation=True, max_length=512)
        x = {k: v.to(device) for k, v in x.items()}
        
        with torch.no_grad():
            prediction = roberta_model(**x)
            logits = prediction.logits
            probs = torch.nn.functional.softmax(logits, dim=1)

        label = torch.argmax(prediction.logits, dim=1).item()
        confidence = probs.max().item()
                
        # Apply threshold for label adjustment
        if label == 2 and confidence > ROBERTA_THRESHOLD:
            adjusted_label = 1 # true
        else:
            adjusted_label = 0 # treat uncertain TRUE as FALSE
            
        results.append({
            "text": sentence,
            "label": adjusted_label, 
            "confidence": round(confidence, 2)
        })
    return results

# Kafka setup
consumer = KafkaConsumer(
    'cleaned_doc',
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    auto_offset_reset='latest', # change to earliest if you whant to process nlp continuing
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
    """
    Main NLP processing loop for articles:
    - Extracts sentences using spaCy
    - Runs RoBERTa on all
    - Flags suspect claims (False) for further validation with RoBERTa
    - Merges flagged claims, generates embeddings
    - Saves output in Elasticsearch and pushes to Kafka
    """
    for msg in consumer:
        doc = msg.value
        content = doc.get('content', '')
        embedding = embedding_model.encode(doc.get('cleaned_text', '')).tolist()

        # Sentence extraction
        spacy_doc = nlp_spacy(content)
        sentences = [sent.text.strip() for sent in spacy_doc.sents if len(sent.text.strip()) > 20]

        # Apply fact-checking models
        # Use DeBERTa for initial claim scoring
    
        # Step 1: run RoBERTa on all sentences
        roberta_results = score_claims_with_roberta(sentences, content)

        # Step 2: run DeBERTa only on sentences flagged as false by RoBERTa
        suspect_sentences = [c["text"] for c in roberta_results if c["label"] == 0]

        # Run DeBERTa only if needed
        if suspect_sentences:
            deberta_results = score_claims_with_deberta(suspect_sentences, content)
        else:
            deberta_results = []

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
    """
    Handles manual claims submitted by the user.
    - Retrieves best evidence via Elasticsearch
    - Runs DeBERTa and RoBERTa on the claim
    - Combines results with rule-based logic
    - Sends the result back through Kafka
    """
    manual_consumer = KafkaConsumer(
        'manual_claims',
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
        auto_offset_reset='latest', # change to earlies if you want to  process nlp in continuous
        enable_auto_commit=True,
        group_id='nlp-manual',
        value_deserializer=lambda x: json.loads(x.decode('utf-8'))
    )


    print("✅ NLP manual claim listener ready", flush=True)

    for msg in manual_consumer:
        claim = msg.value
        claim_text = claim["claim"]

        # Step 1: Retrieve all candidate sentences from ES (or from already-ingested corpus)
        candidate_sentences = get_sentences_from_existing_docs(claim_text)
        print(f"📥 Retrieved {len(candidate_sentences)} candidate sentences from local corpus.")


        # Step 2: Run NLI with RoBERTa against each sentence
        best_match = None
        best_conf = 0

        for sent in candidate_sentences:
            result = score_claims_with_roberta([claim_text], sent)[0]
            if result["label"] == 1 and result["confidence"] > best_conf:
                best_match = sent
                best_conf = result["confidence"]

        # Step 3: Use that sentence as evidence if confidence is strong enough
        if best_match and best_conf > ROBERTA_THRESHOLD:
            evidence = best_match
            print(f"✅ Evidence from model-selected sentence: {evidence}")
        else:
            # fallback to Elasticsearch
            evidence = get_best_evidence(claim_text)
        
        # Step 2: If fallback was returned, trigger ingestion
        if evidence.strip() == claim_text.strip():
            print("⚠️ No evidence found — sending to ingestion via Kafka...", flush=True)
            ingestion_trigger = KafkaProducer(
                bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
                value_serializer=lambda v: v.encode("utf-8")
            )
            try:
                ingestion_trigger.send("user_topic_request", claim_text)
                ingestion_trigger.flush()
                print("📨 Ingestion request sent", flush=True)
                #time.sleep(3)  # Wait for ingestion and ES indexing
                #evidence = get_best_evidence(claim_text)

                evidence = wait_for_evidence(claim_text)
            except Exception as e:
                print(f"❌ Ingestion error: {e}", flush=True)

        # Step 3: Inference
        deberta_results = score_claims_with_deberta([claim_text], evidence)
        roberta_results = score_claims_with_roberta([claim_text], evidence)

        deberta_label = deberta_results[0]["label"]
        deberta_confidence = deberta_results[0]["confidence"]
        roberta_label = roberta_results[0]["label"]
        roberta_confidence = roberta_results[0]["confidence"]

        # Step 4: Logic with RoBERTa priority
        if roberta_label == 1 and roberta_confidence > ROBERTA_THRESHOLD:
            final_label = 1
            reason = "✅ RoBERTa predicted True with high confidence (priority model)"
        elif deberta_label == 1 and deberta_confidence > DEBERTA_THRESHOLD:
            final_label = 1
            reason = "⚠️ RoBERTa=False or low confidence, but DeBERTa predicted True with high confidence"
        else:
            final_label = 0
            reason = "❌ Both models predicted False (or confidence too low)"

        print("🔍 DEBUG CLAIM INFERENCE")
        print(f"📌 Claim: {claim_text}")
        print(f"📚 Evidence: {evidence}")
        print(f"✅ Labels: DeBERTa={deberta_label}, RoBERTa={roberta_label}")
        print(f"🔎 Confidence: DeBERTa={deberta_confidence:.2f}")
        print(f"🔎 Confidence: RoBERTa={roberta_confidence:.2f}")
        print(f"📤 Sent manual claim result for {claim['id']} with final label={final_label}", flush=True)
        print(f"[🧠 RoBERTa label]: {roberta_results[0]['label']} — confidence: {roberta_confidence}")


        result = {
            "id": claim["id"],
            "claim": claim_text,
            "label": final_label,
            "models": {
                "deberta": deberta_label,
                "roberta": roberta_label,
                "roberta_confidence": roberta_confidence
            },
            "reason": reason
        }

        producer.send("manual_results", result)

def wait_for_evidence(claim_text, retries=5, delay=2):
    """
    Waits for relevant evidence to become available in Elasticsearch for a given claim.

    If no matching evidence is immediately found (i.e., the fallback is returned),
    the function retries up to `retries` times, waiting `delay` seconds between attempts.

    Parameters:
    - claim_text (str): The user-submitted claim to search evidence for.
    - retries (int): Number of times to retry evidence search if initial attempt fails.
    - delay (int): Time in seconds to wait between retries.

    Returns:
    - str: A string containing the retrieved evidence if found, or the original claim text as fallback.
    """
    for attempt in range(retries):
        evidence = get_best_evidence(claim_text)
        if evidence.strip() != claim_text.strip():
            print(f"✅ Evidence found after {attempt+1} attempt(s)", flush=True)
            return evidence
        print(f"⏳ Waiting for evidence ({attempt+1}/{retries})...", flush=True)
        time.sleep(delay)
    print("❌ Evidence still not found after retries. Using fallback.", flush=True)
    return "UNVERIFIABLE"


def get_best_evidence(claim_text, top_k=3, similarity_threshold=0.6):
    """
    Retrieves the top-k most relevant evidence snippets for a claim from Elasticsearch.
    Uses full-text matching and filters out short or duplicate results.
    """
    try:
        query = {
            "query": {
                "match": {
                    "content": {
                        "query": claim_text,
                        "minimum_should_match": "60%",
                        "fuzziness": "AUTO"
                    }
                }
            },
            "size": top_k
        }

        res = es.search(index="news_facts", body=query)
        print(f"🔎 Found {len(res['hits']['hits'])} hits", flush=True)

        evidences = []
        seen = set()

        claim_vec = embedding_model.encode([claim_text])[0]

        for hit in res["hits"]["hits"]:
            content = hit["_source"].get("content", "")
            if content and len(content) > 50 and content not in seen:
                # Use only first 500 chars
                trimmed = content[:500]
                doc_vec = embedding_model.encode([trimmed])[0]
                sim = cosine_similarity([claim_vec], [doc_vec])[0][0]

                if sim > similarity_threshold:
                    evidences.append(trimmed)
                    seen.add(trimmed)

        return " ".join(evidences) if evidences else "UNVERIFIABLE"
    except Exception as e:
        print(f"⚠️ Elasticsearch error: {e}")
        return claim_text

def get_sentences_from_existing_docs(claim_text, top_k=10):
    """
    Retrieve sentences from indexed documents that may support the claim.
    """
    try:
        query = {
            "query": {
                "match": {
                    "content": {
                        "query": claim_text,
                        "fuzziness": "AUTO"
                    }
                }
            },
            "size": top_k
        }

        res = es.search(index="news_facts", body=query)
        sentences = []

        for hit in res["hits"]["hits"]:
            content = hit["_source"].get("content", "")
            spacy_doc = nlp_spacy(content)
            for sent in spacy_doc.sents:
                if len(sent.text.strip()) > 20:
                    sentences.append(sent.text.strip())

        return sentences

    except Exception as e:
        print(f"⚠️ Error retrieving sentences: {e}")
        return []



if __name__ == "__main__":
    """
    Starts both Kafka consumers (cleaned_doc + manual_claims) in separate threads.
    Enables parallel processing of both real-time article ingestion and user-submitted claims.
    """
    # ✅ Ensure index exists before any processing
    try:
        es.indices.create(index="news_facts", ignore=400)
        print("✅ Elasticsearch index 'news_facts' ready", flush=True)
        #print(f"NLP: {doc['id']} - {len(flagged_claims)} false claims flagged", flush=True)
    except Exception as e:
        print(f"❌ Failed to create Elasticsearch index: {e}", flush=True)

    print("🚀 Starting NLP microservice listeners...", flush=True)

    t1 = threading.Thread(target=handle_cleaned_doc)
    t2 = threading.Thread(target=handle_manual_claims)

    t1.start()
    t2.start()

    t1.join()
    t2.join()