import streamlit as st
import requests
import os
import urllib.parse  # Needed for URL-safe query
import time
import torch
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from services.database.claims_db import save_check, init_db, load_history

def local_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Percorso relativo alla posizione dello script
local_css("style_front.css")

st.set_page_config(page_title="Fact Checking Dashboard", layout="wide")
st.title("Fact Checking Dashboard")

init_db()

# if "DOCKER" in os.environ:
#     api_url = "http://api:8000"
# else:
#     api_url = "http://localhost:8000"
api_url = os.getenv("API_URL", "http://localhost:8000")

# Create tabs for different sections of the app
tab1, tab2, tab3 = st.tabs(["✅ Check Claim", "📜 History of Checked Claims", "📰 Load Filtered News"])

language = "en"

# to verify what streamlit is seeing
#st.sidebar.write("🔍 API_URL from env:", api_url)

# --- Section: Latest News with Fact Check ---

# # --- Section: Manual Claim Check ---
with tab1:
    st.header("Verify a Claim")

    claim_query = st.text_input("Enter a claim to verify")
    if st.button("Check Claim"):
        try:
            # Google Fact Check API URL
            fc_res = requests.get(f"{api_url}/fact-check", params={"query": claim_query, "languageCode": language})
            fc_res.raise_for_status()
            data = fc_res.json()

 
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
                    # save in DuckDB
                    rating = review.get("textualRating", "").lower()
                    if "true" in rating or "correct" in rating:
                        label = 1
                    else: 
                        label = 0
                    

                    if label in (0, 1):  
                        save_check(c['text'], label, "google fact-check")
                    st.markdown("---")
            else:
                #st.warning(f"No fact-checks found for: **\"{claim_query}\"**")
                st.warning("❌ No results from Google. Using DeBERTa + RoBERTa instead...")

                # 2. Use Kafka + NLP pipeline
                st.write("📡 Sending claim to NLP pipeline...")
                try:
                    response = requests.post(f"{api_url}/check-claim-kafka", json={"claim": claim_query})   
                    st.write("📡 NLP response received.")
                    st.write(f"📡 NLP HTTP status: {response.status_code}")
                    response.raise_for_status()
                except requests.RequestException as e:
                    st.error(f"❌ Error sending claim to NLP pipeline: {e}")
                    st.stop()
                result = response.json()

                label = result.get("label")
                if label is None:
                    st.error("❌ No label found in NLP response.")
                    st.json(result)
                    st.stop()
                st.code(result, language="json")  # show raw result for debugging
                st.write(f"🔍 NLP label = {label}")
                # Save the claim check result to the database
                save_check(claim_query, label, "roberta+deberta")

                if label == 1:
                    st.success("✅ NLP (DeBERTa + RoBERTa) predicts this claim is likely **True**")
                else:
                    st.error("❌ NLP (DeBERTa + RoBERTa) predicts this claim is likely **False**")
                



                st.caption("🧠 NLP model outputs (debug):")
                st.json(result)
        except Exception as e:
            st.error(f"Error checking claim: {e}")


# Display the current API URL in the sidebar
#st.sidebar.markdown(f"🌐 API_URL: `{api_url}`")

with tab2:
    db_path = os.getenv("DB_PATH", "/app/services/database/claim_history.duckdb")

    if not os.path.exists(db_path):
        st.warning("No history available. Please check some claims first.")
        st.stop()
    else:
        st.success("History database found. Displaying past claims...")

    try:
    # show history
        st.header("History of Checked Claims")
        history_df = load_history()
        if history_df.empty:
            st.info("No past claims checked.")
        else:
            st.dataframe(history_df)
            # Optional: export to CSV
            st.download_button("⬇️ Download CSV", history_df.to_csv(index=False), "history.csv", "text/csv")
    except Exception as e:
        st.error(f"Error loading history: {e}")

#st.header("Latest News")
with tab3:
    # --- Section: Filters ---
    st.markdown("""
        <script>
            const sidebar = window.parent.document.querySelector('section[data-testid="stSidebar"]');
            if (sidebar) sidebar.style.display = 'block';
        </script>
    """, unsafe_allow_html=True)
    st.sidebar.header("Filters")

    query = st.sidebar.text_input("Search articles (optional)")
    language = st.sidebar.selectbox("Select Language", ["en", "it", "fr", "de", "es"])
    topic = st.sidebar.selectbox("Select Topic", ["", "climate", "elections", "health", "technology", "misinformation"])
    if st.sidebar.button("Load Filtered News"):
        try:
            if not topic:
                st.warning("Please select a topic to load news.")
            else:
                res = requests.post(f"{api_url}/send-topic", json={"topic": topic})
                res.raise_for_status()  # make sure request succeeded

                time.sleep(2) # Wait for the ingestion service to process the topic

                # Fetch news from the API
                fetch_res = requests.get(f"{api_url}/fetch-news", params={"topic": topic, "language": language})
                fetch_res.raise_for_status()
                news_items = fetch_res.json()


                if not isinstance(news_items, list):
                    st.error("Unexpected response format from API.")
                    st.stop()
                if not news_items:
                    st.warning("No articles found.")

                for item in news_items:
                    st.subheader(item["title"])
                    st.write(item["content"])
                    st.caption(f"Published at: {item['published_at']}")

                    # --- fact-checking ---
                    if "fact_check" in item:
                        fact = item["fact_check"]
                        st.markdown(f"**Fact Check Result:** `{fact.get('textual_rating', 'N/A')}`")
                        if fact.get("url"):
                            st.markdown(f"[🔗 Read full review]({fact['url']})")
                    else:
                        st.markdown("_No fact-check data found._")

                    # --- RoBERTa prediction ---
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
                            with st.expander(f"🔍 {claim['text']} ({score_display})"):
                                # Display RoBERTa prediction
                                try:
                                    google_res = requests.get(fact_check_url)
                                    google_res.raise_for_status()
                                    data = google_res.json()

                                    if "claims" in data and data["claims"]:
                                        for c in data["claims"]:
                                            st.subheader(f"📌 {c['text']}")
                                            for review in c.get("claimReview", []):
                                                st.markdown(f"- **Rating**: `{review.get('textualRating')}`")
                                                st.markdown(f"- **Publisher**: {review.get('publisher', {}).get('name')}`")
                                                st.markdown(f"[🔗 Full Review]({review.get('url')})")
                                            st.markdown("---")
                                    else:
                                        st.info("ℹ️ Nessun fact-check trovato da Google.")

                                except Exception as e:
                                    st.error(f"Errore nella verifica con Google API: {e}")


                    st.markdown("---")



        except Exception as e:
            st.error(f"Failed to fetch news: {e}")
