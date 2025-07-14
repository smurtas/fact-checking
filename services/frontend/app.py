import streamlit as st
import requests
import os
import urllib.parse  # Needed for URL-safe query
import time
import torch
from db import init_db, save_check, load_history

st.set_page_config(page_title="Fact Checking Dashboard", layout="wide")
st.title("Fact Checking Dashboard")

init_db()

# if "DOCKER" in os.environ:
#     api_url = "http://api:8000"
# else:
#     api_url = "http://localhost:8000"
api_url = os.getenv("API_URL", "http://localhost:8000")

# Create tabs for different sections of the app
tab1, tab2, tab3 = st.tabs(["📰 Load Filtered News", "✅ Check Claim", "📜 History"])


# to verify what streamlit is seeing
st.sidebar.write("🔍 API_URL from env:", api_url)

# --- Section: Filters ---
st.sidebar.header("Filters")

query = st.sidebar.text_input("Search articles (optional)")
language = st.sidebar.selectbox("Select Language", ["en", "it", "fr", "de", "es"])
topic = st.sidebar.selectbox("Select Topic", ["", "climate", "elections", "health", "technology", "misinformation"])

# --- Section: Latest News with Fact Check ---
#st.header("Latest News")
with tab1:
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

# # --- Section: Manual Claim Check ---
with tab2:
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
                    st.markdown("---")
            else:
                #st.warning(f"No fact-checks found for: **\"{claim_query}\"**")
                st.warning("❌ No results from Google. Using DeBERTa + RoBERTa instead...")

                # 2. Use Kafka + NLP pipeline
                response = requests.post(f"{api_url}/check-claim-kafka", json={"claim": claim_query})
                response.raise_for_status()
                result = response.json()

                label = result.get("label")
                # Save the check to the databasesave_check(claim_query, label, "roberta+deberta")
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

with tab3:
    # show history
    history_df = load_history()
    if history_df.empty:
        st.info("No past claims checked.")
    else:
        st.dataframe(history_df)
        # Optional: export to CSV
        st.download_button("⬇️ Download CSV", history_df.to_csv(index=False), "history.csv", "text/csv")