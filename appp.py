import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid
import json
import os
import math
import google.generativeai as genai

# 1. Page Configuration
st.set_page_config(page_title="Wolt Scraper - PRO", page_icon="🍔", layout="wide")

# --- BEZBEDNO UČITAVANJE VIŠE API KLJUČEVA ---
def get_gemini_keys():
    raw_keys = ""
    if "GEMINI_API_KEY" in st.secrets:
        raw_keys = st.secrets["GEMINI_API_KEY"]
    else:
        try:
            if os.path.exists("config.json"):
                with open("config.json", "r") as f:
                    config = json.load(f)
                    raw_keys = config.get("GEMINI_API_KEY", "")
        except:
            pass
    if raw_keys:
        return [k.strip() for k in raw_keys.split(",") if k.strip()]
    return []

GEMINI_KEYS_LIST = get_gemini_keys()

# CSS za UI
st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stExpander [data-testid="stExpanderDetails"] { padding-top: 0px !important; padding-left: 25px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Menu Scraper PRO")

# --- HELPER: Primena marže i zaokruživanja ---
def apply_price_logic(price, markup_percent, round_up):
    final_price = int(price * (1 + markup_percent / 100))
    if round_up and final_price > 0:
        final_price = ((final_price + 9) // 10) * 10
    return final_price

# --- WOLT LOGIKA (Standardna) ---
def fetch_wolt_data(slug):
    api_url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    try:
        r = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        return r.json() if r.status_code == 200 else None
    except: return None

# --- GEMINI AI FUNKCIJA (Rotacija ključeva) ---
def extract_menu_with_gemini_core(content_to_send, api_keys_list):
    """Zajednička funkcija za slanje podataka (slike, PDF ili Tekst) na Gemini."""
    prompt = """Extract all dishes, prices and descriptions. 
    Return ONLY a valid JSON object with this structure:
    {"sections": [{"name": "Category", "items": [{"name": "Dish Name", "price": 100, "description": "text"}]}]}
    Rules: Prices must be integers (RSD). If description is missing, use empty string. Return ONLY raw JSON."""
    
    full_request = content_to_send + [prompt]
    
    for idx, key in enumerate(api_keys_list):
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(full_request)
            clean_json = re.sub(r'```json|```', '', response.text).strip()
            return json.loads(clean_json)
        except Exception as e:
            if idx < len(api_keys_list) - 1:
                st.warning(f"Prebacujem na sledeći ključ...")
                continue
            else: raise Exception(f"Greška na svim ključevima: {e}")

# --- POMOĆNE FUNKCIJE ZA TABELE ---
def build_dataframes(menu_data, markup, round_up):
    items_list, ordered_sections = [], []
    for section in menu_data.get("sections", []):
        sec_name = section.get("name", "Ostalo").strip()
        if sec_name not in ordered_sections: ordered_sections.append(sec_name)
        for item in section.get("items", []):
            p = apply_price_logic(item.get("price", 0), markup, round_up)
            items_list.append({
                "External_ID": str(uuid.uuid4()), "Product_Name": str(item.get("name", "")),
                "Collection": "MENU", "Section": sec_name, "Price": p,
                "Description": str(item.get("description", "")), "Image_1": ""
            })
    return pd.DataFrame(items_list), ordered_sections

def build_excel(df_p):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df_p.to_excel(w, index=False, sheet_name='Products')
        # Prazni tabovi za kompatibilnost
        pd.DataFrame(columns=["External_ID", "Name"]).to_excel(w, index=False, sheet_name='Attribute Groups')
        pd.DataFrame(columns=["Name"]).to_excel(w, index=False, sheet_name='Attributes')
    return out.getvalue()

# ============================================================
# UI TABS
# ============================================================
tab_wolt, tab_photo, tab_link_ai = st.tabs(["🌐 Wolt Scraper", "📄 Photo/PDF AI Menu", "🔗 Link AI Menu"])

# --- TAB 1: WOLT ---
with tab_wolt:
    link_w = st.text_input("Wolt Link:")
    if st.button("🚀 Run Wolt"):
        # (Standardni Wolt kod koji već imaš...)
        st.info("Ovde ostaje tvoj postojeći kod za direktan Wolt scrap...")

# --- TAB 2: PHOTO/PDF AI ---
with tab_photo:
    st.subheader("Analiza slika i dokumenata")
    rest_n_p = st.text_input("Restoran:", key="rest_p")
    markup_p = st.number_input("Marža %:", value=0, key="mark_p")
    round_p = st.checkbox("Zaokruži na deseticu", key="round_p")
    files = st.file_uploader("Uploaduj Slike/PDF:", type=["jpg","png","pdf"], accept_multiple_files=True)
    
    if st.button("🤖 Analiziraj Slike", type="primary"):
        if files and GEMINI_KEYS_LIST:
            with st.spinner("AI čita slike/PDF..."):
                content = []
                for f in files:
                    d = f.read(); f.seek(0)
                    content.append({"mime_type": f.type, "data": d})
                res = extract_menu_with_gemini_core(content, GEMINI_KEYS_LIST)
                st.session_state['ai_res'] = res
                st.session_state['ai_name'] = rest_n_p

    if 'ai_res' in st.session_state:
        df, sects = build_dataframes(st.session_state['ai_res'], markup_p, round_p)
        st.download_button("📊 Preuzmi Excel", build_excel(df), f"{st.session_state['ai_name']}.xlsx")
        st.dataframe(df)

# --- TAB 3: LINK AI (NOVO!) ---
with tab_link_ai:
    st.subheader("AI Analiza bilo kog linka")
    st.info("💡 Ubaci link veb-sajta restorana (npr. njihov sajt ili on-line meni). AI će pokušati da pročita sadržaj stranice.")
    
    link_input_ai = st.text_input("Unesi link veb-sajta restorana:", placeholder="https://www.restoran.rs/jelovnik")
    
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        rest_n_l = st.text_input("Naziv restorana:", key="rest_l")
    with col_a2:
        markup_l = st.number_input("Marža %:", value=0, key="mark_l")
        round_l = st.checkbox("Zaokruži na deseticu", key="round_l")

    if st.button("🌐 ANALIZIRAJ LINK", type="primary"):
        if link_input_ai and GEMINI_KEYS_LIST:
            with st.spinner("Preuzimam sadržaj stranice i šaljem AI-ju na analizu..."):
                try:
                    # 1. Preuzimanje teksta sa linka
                    r = requests.get(link_input_ai, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                    if r.status_code == 200:
                        # Uzimamo sirov tekstualni sadržaj (bez HTML tagova je bolje)
                        # Koristimo jednostavan regex da očistimo HTML za Gemini (da mu bude lakše)
                        html_content = r.text
                        text_only = re.sub('<[^<]+?>', '', html_content) # Brzo čišćenje HTML-a
                        
                        # 2. Slanje teksta Gemini-ju
                        content = [f"Ovo je tekstualni sadržaj preuzet sa veb sajta: \n\n {text_only[:15000]}"] # Limit 15k karaktera radi stabilnosti
                        res = extract_menu_with_gemini_core(content, GEMINI_KEYS_LIST)
                        
                        st.session_state['link_ai_res'] = res
                        st.session_state['link_ai_name'] = rest_n_l
                        st.success("Analiza linka uspešna!")
                    else:
                        st.error(f"Greška: Veb sajt je odbio pristup (Status: {r.status_code})")
                except Exception as e:
                    st.error(f"Došlo je do greške: {e}")
        else:
            st.warning("Unesite link i proverite API ključeve.")

    if 'link_ai_res' in st.session_state:
        df_l, sects_l = build_dataframes(st.session_state['link_ai_res'], markup_l, round_l)
        st.download_button("📊 Preuzmi Excel (iz Linka)", build_excel(df_l), f"{st.session_state['link_ai_name']}_link.xlsx")
        
        for s in sects_l:
            with st.expander(f"Sekcija: {s}"):
                st.table(df_l[df_l['Section'] == s][["Product_Name", "Price", "Description"]])
