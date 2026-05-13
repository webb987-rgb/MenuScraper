import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid
import base64
import json
import os
import google.generativeai as genai

# 1. Page Configuration
st.set_page_config(page_title="Wolt Scraper - PRO", page_icon="🍔", layout="wide")

# --- BEZBEDNO UČITAVANJE KLJUČA ---
def get_gemini_key():
    # 1. Prvo gleda Streamlit Secrets (za cloud/server)
    if "GEMINI_API_KEY" in st.secrets:
        return st.secrets["GEMINI_API_KEY"]
    
    # 2. Zatim gleda lokalni config.json
    try:
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                config = json.load(f)
                return config.get("GEMINI_API_KEY")
    except Exception:
        pass
    return None

GEMINI_KEY = get_gemini_key()

# CSS za lepši UI
st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stExpander [data-testid="stExpanderDetails"] { padding-top: 0px !important; padding-left: 25px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Wolt Menu Scraper & AI OCR")

# --- WOLT SCRAPER FUNKCIJE ---
def fetch_data(slug):
    api_url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(api_url, headers=headers, timeout=15)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def process_all_data(data):
    ordered_sections = []
    item_to_section = {}
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Menu")
        ordered_sections.append(cat_name)
        for item_id in cat.get("item_ids", []):
            item_to_section[item_id] = cat_name

    wolt_group_to_new_id = {}
    groups_raw, attrs_raw = [], []
    for group in data.get("options", []):
        new_gid = str(uuid.uuid4())
        wolt_group_to_new_id[group.get("id")] = new_gid
        for val in group.get("values", []):
            new_aid = str(uuid.uuid4())
            attrs_raw.append({
                "External_ID": new_aid, "Group_ID_Internal": new_gid,
                "Name": val.get("name", ""), "Price": val.get("price", 0) / 100,
                "Enabled": "YES", "Selected_by_Default": "NO"
            })
        groups_raw.append({
            "External_ID": new_gid, "Max": 10, "Min": 0, "Name": group.get("name", "Option"),
            "Multiple_Selection": "NO", "Collapse_by_Default": "NO", 
            "Attributes": ",".join([a["External_ID"] for a in attrs_raw if a["Group_ID_Internal"] == new_gid])
        })

    items_list = []
    seen_ids = set()
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Menu")
        for w_id in cat.get("item_ids", []):
            if w_id in seen_ids: continue
            item = next((i for i in data.get("items", []) if i.get("id") == w_id), None)
            if not item: continue
            seen_ids.add(w_id)
            puna_cena = int((item.get("base_price") or item.get("price") or 0) / 100)
            img_url = ""
            main_img = item.get("main_image")
            if isinstance(main_img, dict) and main_img.get("id"):
                img_url = f"https://imageproxy.wolt.com/assets/{main_img['id']}?w=960"
            
            gids = [wolt_group_to_new_id[o.get("option_id")] for o in item.get("options", []) if o.get("option_id") in wolt_group_to_new_id]
            
            items_list.append({
                "External_ID": str(uuid.uuid4()), "Product_Name": item.get("name", ""), "Collection": "MENU",
                "Section": cat_name, "Price": puna_cena, "Image_1": img_url,
                "Description": item.get("description", "").replace("\n", " ").strip(),
                "Attribute_Groups": ",".join(gids), "Is_Alcoholic": "NO", "Is_Tobacco": "NO", 
                "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
            })
    return pd.DataFrame(items_list), pd.DataFrame(groups_raw), pd.DataFrame(attrs_raw), ordered_sections

# --- GEMINI AI FUNKCIJA (Fix za 404 grešku) ---
def extract_menu_with_gemini(uploaded_files, api_key):
    genai.configure(api_key=api_key)
    
    # Koristimo punu putanju do modela kako bismo izbegli v1beta konflikte
    model = genai.GenerativeModel('models/gemini-1.5-flash')
    
    prompt = """Analiziraj priložene slike jelovnika i vrati ISKLJUČIVO JSON objekat.
    Struktura:
    {
      "sections": [
        {
          "name": "Naziv Sekcije",
          "items": [{"name": "Ime jela", "price": 1200, "description": "opis"}]
        }
      ]
    }
    Pravila: Cene moraju biti celi brojevi (RSD). Ako nema opisa, ostavi prazan string. 
    Vrati samo sirov JSON bez markdown oznaka."""

    content = []
    for uf in uploaded_files:
        image_data = uf.read()
        uf.seek(0)
        content.append({"mime_type": uf.type, "data": image_data})
    
    content.append(prompt)
    
    response = model.generate_content(content)
    text_response = response.text
    # Čišćenje JSON-a ako AI doda ```json ... ```
    clean_json = re.sub(r'```json|```', '', text_response).strip()
    return json.loads(clean_json)

# --- POMOĆNE FUNKCIJE ---
def build_dataframes_from_photo(menu_data):
    items_list, ordered_sections = [], []
    for section in menu_data.get("sections", []):
        sec_name = section.get("name", "Ostalo").strip()
        if sec_name not in ordered_sections: ordered_sections.append(sec_name)
        for item in section.get("items", []):
            items_list.append({
                "External_ID": str(uuid.uuid4()), "Product_Name": str(item.get("name", "")),
                "Collection": "MENU", "Section": sec_name, "Price": item.get("price", 0),
                "Image_1": "", "Description": str(item.get("description", "")),
                "Attribute_Groups": "", "Is_Alcoholic": "NO", "Is_Tobacco": "NO",
                "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
            })
    return pd.DataFrame(items_list), pd.DataFrame(columns=["External_ID", "Name"]), pd.DataFrame(columns=["Name"]), ordered_sections

def build_excel(df_p, df_g, df_a):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df_p.to_excel(w, index=False, sheet_name='Products')
        df_g.to_excel(w, index=False, sheet_name='Attribute Groups')
        df_a.to_excel(w, index=False, sheet_name='Attributes')
    return out.getvalue()

def render_menu_preview(df_p, ordered_sections):
    for s in ordered_sections:
        prods = df_p[df_p['Section'] == s]
        if not prods.empty:
            st.markdown(f"### {s}")
            for _, p in prods.iterrows():
                with st.expander(f"{p['Product_Name']} — {p['Price']} RSD"):
                    if p['Description']: st.write(f"_{p['Description']}_")

# --- UI TABS ---
tab_wolt, tab_photo = st.tabs(["🌐 Wolt Scraper", "📷 Photo Menu (AI)"])

with tab_wolt:
    link = st.text_input("Unesi Wolt link restorana:")
    if st.button("🚀 POKRENI WOLT"):
        match = re.search(r'/(?:restaurant|venue)/([^/]+)', link)
        if match:
            slug = match.group(1)
            raw = fetch_data(slug)
            if raw:
                p, g, a, o_s = process_all_data(raw)
                st.session_state['w_p'], st.session_state['w_g'], st.session_state['w_a'], st.session_state['w_o'] = p, g, a, o_s
                st.success("Wolt podaci su spremni!")
        else: st.error("Neispravan link.")

    if 'w_p' in st.session_state:
        st.download_button("📊 Preuzmi Wolt Excel", build_excel(st.session_state['w_p'], st.session_state['w_g'], st.session_state['w_a']), "wolt_menu.xlsx")
        render_menu_preview(st.session_state['w_p'], st.session_state['w_o'])

with tab_photo:
    st.info("💡 Ovaj tab koristi Gemini 1.5 Flash za čitanje teksta sa slika.")
    
    # Prikaz statusa ključa
    if not GEMINI_KEY:
        current_api_key = st.text_input("Unesite Gemini API Key:", type="password")
    else:
        st.success("✅ Ključ je automatski učitan.")
        current_api_key = GEMINI_KEY

    rest_name = st.text_input("Naziv restorana (za fajl):", "Moj_Restoran")
    uploaded_files = st.file_uploader("Uploaduj slike menija:", type=["jpg", "png", "webp"], accept_multiple_files=True)
    
    if st.button("🤖 ANALIZIRAJ SLIKE", type="primary"):
        if current_api_key and uploaded_files:
            with st.spinner("AI analizira slike..."):
                try:
                    data = extract_menu_with_gemini(uploaded_files, current_api_key)
                    p, g, a, o = build_dataframes_from_photo(data)
                    st.session_state['p_p'], st.session_state['p_g'], st.session_state['p_a'], st.session_state['p_o'] = p, g, a, o
                    st.success("Analiza završena!")
                except Exception as e:
                    st.error(f"Došlo je do greške: {str(e)}")
        else:
            st.warning("Nedostaje API ključ ili slike.")

    if 'p_p' in st.session_state:
        st.download_button("📊 Preuzmi AI Excel", build_excel(st.session_state['p_p'], st.session_state['p_g'], st.session_state['p_a']), f"{rest_name}_meni.xlsx")
        render_menu_preview(st.session_state['p_p'], st.session_state['p_o'])
