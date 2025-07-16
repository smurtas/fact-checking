import streamlit as st
import requests
import os
import urllib.parse  # Needed for URL-safe query
import time
import torch
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from services.database.claims_db import save_check, init_db, load_history, clear_history

def local_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Percorso relativo alla posizione dello script
local_css("style_front.css")

st.set_page_config(page_title="Fact Checking Dashboard", layout="wide")
st.title("Fact Checking Dashboard")

if "claim_checked" not in st.session_state:
    st.session_state.claim_checked = False


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

    with st.container():
        st.markdown("<div class='custom-claim-input'>", unsafe_allow_html=True)
        claim_query = st.text_input(
            "Enter a claim to verify",
            placeholder="e.g. 'The Earth is flat.'",
            key="claim_input",
            help="Type a claim you want to verify. The system will first check with Google Fact Check Tools API, and if no verified claims are found, it will use internal AI models (DeBERTa + RoBERTa) for automated verification.",
            label_visibility="collapsed"
        )
        st.markdown("</div>", unsafe_allow_html=True)
        if st.button("Check Claim"):
            claim_query = st.session_state.get("claim_input", "")
            if claim_query:
       

            #use_nlp = False

                try:
                    # Google Fact Check API URL
                    with st.spinner("🔍 Checking your claim... Please wait..."):
                        fc_res = requests.get(f"{api_url}/fact-check", 
                                            params={"query": claim_query, "languageCode": language}, 
                                            timeout=5)# add a timeout to avoid long waits
                        fc_res.raise_for_status()
                        data = fc_res.json()

        
                    #Google Fact Check API response
                    if "claims" in data and data["claims"]:
                        # Check if any claim exactly matches the query
                        exact_match_found = any(claim_query.lower() in c["text"].lower() for c in data["claims"])
                        st.caption("""
                            ℹ️ The system first checks with the Google Fact Check Tools API.
                            If no verified claims are found, it uses internal AI models (DeBERTa + RoBERTa) for automated verification.
                            """)
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
                        st.warning("❌ No fact-check results found from Google.")

                        st.info("🔄 Switching to internal AI models (DeBERTa + RoBERTa) to verify the claim.")

                        # 2. Use Kafka + NLP pipeline
                        st.write("📡 Sending claim to NLP pipeline...")
                        try:
                            with st.spinner("🔍 Checking your claim... Please wait..."):
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
                        label = result.get("label")
                        deberta_label = result["models"]["deberta"]
                        roberta_label = result["models"]["roberta"]

                        # Logic to determine the final label based on DeBERTa and RoBERTa outputs
                        # priority to DeBERTa
                        # - Both 0 → label = 0
                        # - DeBERTa = 0, RoBERTa = 1 → label = 0
                        # - DeBERTa = 1, RoBERTa = 0 → label = 1
                        # - Both 1 → label = 1

                        if deberta_label == 1:
                            label = 1
                        else:
                            label = 0

                        if label == 1 and roberta_label == 0:
                            st.success("⚠️ Our AI models predict this claim is likely **TRUE**.")
                            st.write("⚠️ But be aware DeBERTa model suggests this claim is likely **False**.")
                        elif label == 0 and roberta_label == 1:
                            st.warning("⚠️ Our AI models predict this claim is likely **FALSE**.")
                            st.write("⚠️ But be aware DeBERTa model suggests this claim is likely **True**.")
                        elif label == 1 and roberta_label == 1:
                            st.success("✅ Our AI models suggest this claim is likely **TRUE**.")
                        elif label == 0 and roberta_label == 0:
                            st.error("❌ Our AI models suggest this claim is likely **FALSE**.")
                        else:
                            st.error("❌ Our AI models suggest this claim is likely **FALSE**.")

                        st.caption("🧠 Model Details:")
                        st.markdown(f"- **DeBERTa**: {'True' if deberta_label == 1 else 'False'}")
                        st.markdown(f"- **RoBERTa**: {'True' if roberta_label == 1 else 'False'}")
                        st.write(f"🔍 NLP label = {label}")
                        # Save the claim check result to the database
                        save_check(claim_query, label, "roberta+deberta")
                        
                    

                        # if label == 1:
                        #     st.success("✅ NLP (DeBERTa + RoBERTa) predicts this claim is likely **True**")
                        # else:
                        #     st.error("❌ NLP (DeBERTa + RoBERTa) predicts this claim is likely **False**")


                        # st.caption("🧠 NLP model outputs (debug):")
                        # st.json(result)

                except requests.exceptions.Timeout:
                    st.warning("⏳ Google Fact Check API timed out.")
                    use_nlp = True
                except Exception as e:
                    st.error(f"Error checking claim: {e}")
                            # Button to new check 
            # if st.button("🔁 New Check"):
            #     st.session_state.claim_checked = False
            #     if "claim_input" in st.session_state:
            #         del st.session_state["claim_input"]
            #     st.rerun()

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
    
    # Clear history button
    st.subheader("Clear History")

    if st.button("🗑️ Clear All History"):
        try:
            clear_history()
            st.success("✅ History cleared successfully.")
            st.rerun()
        except Exception as e:  
            st.error(f"❌ Failed to clear history: {e}")

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
