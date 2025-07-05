import requests
import os

GOOGLE_FACT_CHECK_API_KEY = os.getenv("FACT_CHECK_API_KEY")

def search_fact_checks(query: str, language: str = "en"):
    url = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
    params = {
        "query": query,
        "languageCode": language,
        "key": GOOGLE_FACT_CHECK_API_KEY
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json().get("claims", [])
    except Exception as e:
        print(f"Error querying Fact Check API: {e}")
        return []
