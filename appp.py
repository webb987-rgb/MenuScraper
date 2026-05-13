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
st.set_page_config(page_title="Wolt & AI Scraper PRO", page_icon="🍔", layout="wide")

# --- BEZBEDNO DOBAVLJANJE KLJUČA ---
# Prvo gleda Streamlit Secrets, ako ne nađe, pokušava lokalni config.json
def get_api_key():
    if "GEMINI_API_KEY" in st.secrets:
        return st.secrets["GEMINI_API_KEY"]
    try:
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                return json.load(f).get("GEMINI_API_KEY")
    except:
        pass
    return None

GEMINI_KEY = get_api_key()

# CSS za bolji pregled (kompaktniji dizajn)
st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stMarkdown p { font-size: 14px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Wolt & AI Menu Scraper")

# --- WOLT SCRAPER FUNKCIJE (Originalna logika) ---
def fetch_wolt_data(slug):
    url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        return r.json() if r.status_code == 200 else None
    except: return None

def process_wolt_data(data):
    # (Tvoja originalna logika za mapiranje Wolt JSON-a u DataFrame)
    # Skraćeno ovde radi preglednosti, ali zadržava tvoju strukturu
    items_list, ordered_sections = [], []
    # ... (ostatak tvoje logike iz originalnog fajla) ...
    # Za potrebe primera, vraćamo prazne okvire ako je kod ovde skraćen
    return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), []

# --- GEMINI AI OCR FUNKCIJA (Rešava 404 grešku) ---
def extract_menu_with_gemini(uploaded_files, api_key):
    genai.configure(api_key=api_key)
    
    # Korišćenje čistog naziva modela. 
    # Biblioteka google-generativeai >= 0.7.0 automatski koristi stabilan v1 endpoint
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = """You are a menu extraction expert. Analyze the images and return ONLY a valid JSON.
    Structure:
    {
      "sections": [
        {
          "name": "Section Name",
          "items": [{"name": "Item Name", "price": 1200, "description": "optional text"}]
        }
      ]
    }
    Rules: Prices must be integers in RSD. If no description, use "". Return ONLY raw JSON code."""

    content = []
    for uf in uploaded_files:
        img_data = uf.read()
        uf.seek(0)
        content.append({"mime_type": uf.type, "data": img_data})
    
    content.append(prompt)
    
    # Generisanje sadržaja
    response = model.generate_content(content)
    
    # Čišćenje odgovora: AI nekad doda ```json ... ```, ovo to uklanja
    raw_text = response.text
    clean_json = re.sub(r'```json|```', '', raw_text).strip()
    
    # Dodatna provera: uzmi samo ono što je unutar prve { i poslednje } zagrade
    start_idx = clean_json.find('{')
    end_idx = clean_json.rfind('}') + 1
    if start_idx != -1 and end_idx != 0:
        clean_json = clean_json[start_idx:end_idx]
        
    return json.loads(clean_json)

# --- POMOĆNE FUNKCIJE ZA EXCEL ---
def build_excel(df_p, df_g, df_a):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df_p.to_excel(w, index=False, sheet_name='Products')
        if not df_g.empty: df_g.to_excel(w, index=False, sheet_name='Attribute Groups')
        if not df_a.empty: df_a.to_excel(w, index=False, sheet_name='Attributes')
    return out.getvalue()

# --- MAIN UI ---
tab_wolt, tab_photo = st.tabs(["🌐 Wolt Scraper", "📷 Photo Menu (AI)"])

with tab_wolt:
    wolt_url = st.text_input("Unesi Wolt link restorana:")
    if st.button("🚀 POKRENI WOLT"):
        slug_match = re.search(r'/(?:restaurant|venue)/([^/]+)', wolt_url)
        if slug_match:
            slug = slug_match.group(1)
            raw = fetch_wolt_data(slug)
            if raw:
                st.success(f"Uspešno učitano: {slug}")
                # Ovde pozivaš svoju originalnu funkciju process_all_data(raw)
            else: st.error("Neuspešno dobavljanje podataka.")
        else: st.error("Link nije ispravan.")

with tab_photo:
    st.subheader("AI OCR Digitalizacija")
    
    if not GEMINI_KEY:
        st.warning("⚠️ API ključ nije pronađen u Secrets. Unesite ga ručno:")
        current_key = st.text_input("Gemini API Key:", type="password")
    else:
        st.success("✅ API ključ učitan iz Secrets.")
        current_key = GEMINI_KEY

    rest_name = st.text_input("Naziv restorana:", "Meni_Restorana")
    uploaded_images = st.file_uploader("Uploaduj slike (JPG, PNG, WEBP):", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)

    if st.button("🤖 ANALIZIRAJ JELOVNIK", type="primary"):
        if current_key and uploaded_images:
            with st.spinner("AI analizira slike... ovo može potrajati par sekundi."):
                try:
                    menu_data = extract_menu_with_gemini(uploaded_images, current_key)
                    
                    # Konverzija JSON-a u DataFrame (tvoja logika iz build_dataframes_from_photo)
                    items = []
                    for sec in menu_data.get("sections", []):
                        for itm in sec.get("items", []):
                            items.append({
                                "External_ID": str(uuid.uuid4()),
                                "Product_Name": itm.get("name"),
                                "Collection": "MENU",
                                "Section": sec.get("name"),
                                "Price": itm.get("price", 0),
                                "Description": itm.get("description", ""),
                                "Is_Alcoholic": "NO", "Is_Tobacco": "NO"
                            })
                    
                    df_p = pd.DataFrame(items)
                    
                    st.success(f"Izvučeno {len(df_p)} jela!")
                    st.dataframe(df_p, use_container_width=True)
                    
                    # Download
                    excel_data = build_excel(df_p, pd.DataFrame(), pd.DataFrame())
                    st.download_button("📊 Preuzmi Excel", excel_data, f"{rest_name}.xlsx")
                    
                except Exception as e:
                    st.error(f"Greška: {str(e)}")
        else:
            st.error("Ubacite slike i proverite API ključ.")
