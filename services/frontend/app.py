import streamlit as st
import requests
import os
import urllib.parse  # Needed for URL-safe query

from transformers import RobertaTokenizer, RobertaForSequenceClassification
import torch

# Load tokenizer and model only once
tokenizer = RobertaTokenizer.from_pretrained('Dzeniks/roberta-fact-check')
model = RobertaForSequenceClassification.from_pretrained('Dzeniks/roberta-fact-check')
model.eval()

def score_claim_roberta_local(claim, evidence=""):
    x = tokenizer.encode_plus(claim, evidence, return_tensors="pt", truncation=True)
    with torch.no_grad():
        prediction = model(**x)
    label = torch.argmax(prediction.logits, dim=1).item()
    return label  # 0 = False, 1 = True


# Set up Streamlit page configuration
# This will set the title and layout of the Streamlit app

st.set_page_config(page_title="Fact Checking Dashboard", layout="wide")
st.title("Fact Checking Dashboard")

api_url = os.getenv("API_URL", "http://localhost:8000")

# --- Section: Filters ---
st.sidebar.header("Filters")

query = st.sidebar.text_input("Search articles (optional)")
language = st.sidebar.selectbox("Select Language", ["en", "it", "fr", "de", "es"])
topic = st.sidebar.selectbox("Select Topic", ["", "climate", "elections", "health", "technology", "misinformation"])

# --- Section: Latest News with Fact Check ---
st.header("Latest News")

if st.sidebar.button("Load Filtered News"):
    try:
        params = {
            "query": query,
            "language": language,
            "topic": topic
        }
        res = requests.get(f"{api_url}/latest-news", params={k: v for k, v in params.items() if v})
        res.raise_for_status()
        news_items = res.json()

        if not news_items:
            st.warning("No articles found.")
        for item in news_items:
            st.subheader(item["title"])
            st.write(item["content"])
            st.caption(f"Published at: {item['published_at']}")

            if "fact_check" in item:
                fact = item["fact_check"]
                st.markdown(f"**Fact Check Result:** `{fact.get('textual_rating', 'N/A')}`")
                if fact.get("url"):
                    st.markdown(f"[🔗 Read full review]({fact['url']})")
            else:
                st.markdown("_No fact-check data found._")

            if "flagged_claims" in item and item["flagged_claims"]:
                st.markdown("**Flagged Claims:**")
                for claim in item["flagged_claims"]:
                    if "label" in claim:
                        label_text = "✅ True" if claim["label"] == 1 else "❌ False"
                        score_display = f"Prediction: {label_text}"
                    elif "score" in claim:
                        score_display = f"Score: {claim['score']:.2f}"
                    else:
                        score_display = "N/A"
                    encoded_query = urllib.parse.quote(claim["text"])
                    fact_check_url = f"{api_url}/fact-check?query={encoded_query}&languageCode={language}"
                    st.markdown(f"- {claim['text']} ({score_display}) [🔎 Check with Google API]({fact_check_url})")

            st.markdown("---")

    except Exception as e:
        st.error(f"Failed to fetch news: {e}")

# --- Section: Manual Claim Check ---
st.header("Verify a Claim")

claim_query = st.text_input("Enter a claim to verify")
if st.button("Check Claim"):
    try:
        # Google Fact Check API URL
        fc_res = requests.get(f"{api_url}/fact-check", params={"query": claim_query, "languageCode": language})
        fc_res.raise_for_status()
        data = fc_res.json()

        # Roberta prediction
        roberta_res = requests.post(f"{api_url}/roberta-check", json={"claim": claim_query})
        roberta_res.raise_for_status()  # make sure request succeeded

        roberta_data = roberta_res.json()
        label = roberta_data.get("label")
        if label is not None:
            if label == 1:
                st.success("✅ RoBERTa predicts this claim is likely **True**")
            else:
                st.error("❌ RoBERTa predicts this claim is likely **False**")

        #Google Fact Check API response
        if "claims" in data and data["claims"]:
            # Check if any claim exactly matches the query
            exact_match_found = any(claim_query.lower() in c["text"].lower() for c in data["claims"])

            if not exact_match_found:
                st.success(f"🟢 No specific fact-check was found for: **\"{claim_query}\"**.\n\nIt may be true or unverified.")
                st.markdown("But we found related fact-checked claims:")

            else:
                st.info(f"🔍 Here are fact-checks related to your claim: **\"{claim_query}\"**")

            
            for c in data["claims"]:
                st.subheader(f"Claim: {c['text']}")
                for review in c.get("claimReview", []):
                    st.markdown(f"- **Rating**: `{review.get('textualRating')}`")
                    st.markdown(f"- **Publisher**: {review.get('publisher', {}).get('name')}")
                    st.markdown(f"[🔗 Full Review]({review.get('url')})")
                st.markdown("---")
        else:
            st.warning(f"No fact-checks found for: **\"{claim_query}\"**")
    except Exception as e:
        st.error(f"Error checking claim: {e}")
