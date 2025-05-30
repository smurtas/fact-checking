
import streamlit as st
import requests

st.title("Fact Checking Dashboard")
api_url = "http://api:8000"

if st.button("Carica Notizie Recenti"):
    res = requests.get(f"{api_url}/latest-news")
    data = res.json()
    for item in data:
        st.subheader(item["title"])
        st.write(item["content"])
        st.caption(f"Pubblicato il {item['published_at']}")