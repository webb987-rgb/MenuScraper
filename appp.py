import streamlit as st
import requests
import pandas as pd
import io
import re
import uuid
import json
import os
import google.generativeai as genai

# 1. Konfiguracija stranice
st.set_page_config(page_title="Wolt & AI Scraper", page_icon="🍔", layout="wide")

# --- PAMETNO UČITAVANJE KLJUČA ---
def get_gemini_key():
    # Prvo gleda Streamlit Secrets (za Cloud)
    if "GEMINI_API_KEY" in st.secrets:
        return st.secrets["GEMINI_API_KEY"]
    
    # Drugo gleda lokalni fajl (za tvoj kompjuter)
    try:
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                # Provera da li je fajl prazan pre učitavanja
                content = f.read().strip()
                if content:
                    config = json.loads(content)
                    return config.get("GEMINI_API_KEY")
    except Exception:
        pass
    return None

GEMINI_KEY = get_gemini_key()

st.title("🍔 Wolt & AI Menu Scraper")

# --- WOLT LOGIKA (Skraćeno za preglednost, ostaje ista kao tvoja) ---
def fetch_wolt_data(slug):
    api_url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    try:
        r = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        return r.json() if r.status_code == 200 else None
    except: return None

# --- GEMINI AI OCR LOGIKA (REŠAVA 404 GREŠKU) ---
def extract_menu_with_gemini(uploaded_files, api_key):
    genai.configure(api_key=api_key)
    
    # Korišćenje "flash-latest" aliasa koji je najstabilniji na v1 API-ju
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    
    prompt = """Extract menu items into JSON. 
    Format: {"sections": [{"name": "Category", "items": [{"name": "Dish", "price": 100, "description": ""}]}]}
    Rules: Prices as integers in RSD. Return ONLY raw JSON."""

    content = []
    for uf in uploaded_files:
        img_data = uf.read()
        uf.seek(0)
        content.append({"mime_type": uf.type, "data": img_data})
    
    content.append(prompt)
    
    # Slanje zahteva
    response = model.generate_content(content)
    
    # Čišćenje odgovora od markdown oznaka (```json)
    raw_text = response.text
    clean_json = re.sub(r'```json|```', '', raw_text).strip()
    return json.loads(clean_json)

# --- UI TABS ---
tab1, tab2 = st.tabs(["🌐 Wolt Scraper", "📷 Photo AI OCR"])

with tab1:
    wolt_url = st.text_input("Paste Wolt link:")
    if st.button("Run Wolt"):
        slug_match = re.search(r'/(?:restaurant|venue)/([^/]+)', wolt_url)
        if slug_match:
            st.success(f"Učitavam: {slug_match.group(1)}")
            # Ovde bi išao tvoj process_all_data...
        else: st.error("Invalid link.")

with tab2:
    st.subheader("AI Čitanje slika")
    
    # Ako ključ nije u Secrets/Fajlu, dozvoli ručni unos
    active_key = GEMINI_KEY if GEMINI_KEY else st.text_input("Unesi Gemini API Key:", type="password")
    
    if not active_key:
        st.warning("⚠️ API ključ nije podešen. Ubaci ga u Secrets ili config.json.")
    
    uploaded_images = st.file_uploader("Ubaci slike menija:", type=["jpg", "png", "webp"], accept_multiple_files=True)
    
    if st.button("🚀 ANALIZIRAJ", type="primary"):
        if active_key and uploaded_images:
            with st.spinner("AI analizira slike..."):
                try:
                    menu_json = extract_menu_with_gemini(uploaded_images, active_key)
                    st.json(menu_json) # Preview rezultata
                    # Ovde bi išao tvoj build_excel...
                except Exception as e:
                    st.error(f"Greška: {str(e)}")
        else:
            st.error("Nedostaju slike ili ključ.")
