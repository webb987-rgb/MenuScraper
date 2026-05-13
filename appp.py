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
import google.generativeai as genai  # Nova biblioteka

# 1. Page Configuration
st.set_page_config(page_title="Wolt Scraper - PRO", page_icon="🍔", layout="wide")

# Učitavanje API ključa iz eksternog fajla
def load_api_key():
    try:
        with open("config.json", "r") as f:
            config = json.load(f)
            return config.get("GEMINI_API_KEY")
    except FileNotFoundError:
        return None

GEMINI_KEY = load_api_key()

# CSS za UI
st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stExpander [data-testid="stExpanderDetails"] { padding-top: 0px !important; padding-left: 25px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    [data-testid="column"] { width: fit-content !important; min-width: fit-content !important; flex: none !important; padding-right: 15px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Wolt Menu Scraper")

# --- HELPER FUNCTIONS (Wolt Scraper ostaje isti) ---
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
        a_ids = []
        for val in group.get("values", []):
            new_aid = str(uuid.uuid4())
            a_ids.append(new_aid)
            attrs_raw.append({
                "External_ID": new_aid, 
                "Group_ID_Internal": new_gid,
                "Name": val.get("name", ""), 
                "Price": val.get("price", 0) / 100,
                "Enabled": "YES", 
                "Selected_by_Default": "NO"
            })
        groups_raw.append({
            "External_ID": new_gid, 
            "Max": 10, "Min": 0, 
            "Name": group.get("name", "Option"),
            "Multiple_Selection": "NO", 
            "Collapse_by_Default": "NO", 
            "Attributes": ",".join(a_ids)
        })

    items_list = []
    seen_ids = set()
    
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Menu")
        category_item_ids = cat.get("item_ids", [])
        
        for w_id in category_item_ids:
            if w_id in seen_ids: continue
            item = next((i for i in data.get("items", []) if i.get("id") == w_id), None)
            if not item: continue
            
            seen_ids.add(w_id)
            new_iid = str(uuid.uuid4())
            puna_cena = int((item.get("base_price") or item.get("price") or 0) / 100)

            img_url = ""
            main_img = item.get("main_image")
            if isinstance(main_img, dict) and main_img.get("id"):
                img_url = f"https://imageproxy.wolt.com/assets/{main_img['id']}?w=960"
            elif item.get("images") and len(item.get("images")) > 0:
                first_img = item['images'][0]
                if isinstance(first_img, dict):
                    img_id = first_img.get('id')
                    if img_id: img_url = f"https://imageproxy.wolt.com/assets/{img_id}?w=960"
                    elif first_img.get('url'): img_url = first_img.get('url')

            gids = [wolt_group_to_new_id[o.get("option_id")] for o in item.get("options", []) if o.get("option_id") in wolt_group_to_new_id]

            items_list.append({
                "External_ID": new_iid, "Product_Name": item.get("name", ""), "Collection": "MENU",
                "Section": cat_name, "Price": puna_cena, "Image_1": img_url,
                "Description": item.get("description", "").replace("\n", " ").strip(),
                "Attribute_Groups": ",".join(gids), "Is_Alcoholic": "NO", "Is_Tobacco": "NO", 
                "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
            })
        
    return pd.DataFrame(items_list), pd.DataFrame(groups_raw), pd.DataFrame(attrs_raw), ordered_sections


# --- PHOTO MENU: GEMINI AI VISION FUNCTIONS ---

def extract_menu_with_gemini(uploaded_files, api_key):
    """Izvlačenje podataka koristeći Google Gemini Flash 1.5."""
    genai.configure(api_key=api_key)
    
    # Koristimo Flash model jer je najbrži i najbolji za OCR
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = """You are a menu data extraction expert. Carefully analyze ALL the menu images provided and extract every single dish/item you can find.

Return ONLY a valid JSON object. The JSON must have this exact structure:

{
  "sections": [
    {
      "name": "Section Name (e.g. Predjela, Glavna jela, Deserti, Pića, etc.)",
      "items": [
        {
          "name": "Dish name",
          "price": 650,
          "description": "Description if visible, empty string if not"
        }
      ]
    }
  ]
}

Rules:
- Extract ALL items visible across all images.
- Prices must be integers in RSD (strip currency symbols and dots).
- If no clear sections exist, put everything under "Ostalo".
- Preserve original section names.
- Combine items from all images into one coherent structure."""

    # Priprema slika za Gemini
    content = [prompt]
    for uf in uploaded_files:
        image_data = uf.read()
        uf.seek(0)
        content.append({
            "mime_type": uf.type,
            "data": image_data
        })

    response = model.generate_content(content)
    
    # Čišćenje JSON-a iz odgovora
    text_response = response.text
    clean_json = re.sub(r'```json|```', '', text_response).strip()
    
    return json.loads(clean_json)

# --- OSTALE FUNKCIJE ZA FORMATE (Nepromenjene) ---

def build_dataframes_from_photo(menu_data, restaurant_name):
    items_list = []
    ordered_sections = []
    for section in menu_data.get("sections", []):
        sec_name = section.get("name", "Ostalo").strip()
        if sec_name not in ordered_sections:
            ordered_sections.append(sec_name)
        for item in section.get("items", []):
            new_iid = str(uuid.uuid4())
            try:
                price_int = int(item.get("price", 0))
            except:
                price_int = 0
            items_list.append({
                "External_ID": new_iid, "Product_Name": str(item.get("name", "")).strip(),
                "Collection": "MENU", "Section": sec_name, "Price": price_int,
                "Image_1": "", "Description": str(item.get("description", "")).strip(),
                "Attribute_Groups": "", "Is_Alcoholic": "NO", "Is_Tobacco": "NO",
                "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
            })
    
    df_p = pd.DataFrame(items_list)
    df_g = pd.DataFrame(columns=["External_ID", "Max", "Min", "Name", "Multiple_Selection", "Collapse_by_Default", "Attributes"])
    df_a = pd.DataFrame(columns=["External_ID", "Group_ID_Internal", "Name", "Price", "Enabled", "Selected_by_Default"])
    return df_p, df_g, df_a, ordered_sections

def build_excel(df_p, df_g, df_a):
    df_excel = df_p.copy()
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df_excel.to_excel(w, index=False, sheet_name='Products')
        df_g.to_excel(w, index=False, sheet_name='Attribute Groups')
        if not df_a.empty and 'Group_ID_Internal' in df_a.columns:
            df_a_final = df_a.drop(columns=['Group_ID_Internal'])
        else:
            df_a_final = df_a
        df_a_final.to_excel(w, index=False, sheet_name='Attributes')
    return out.getvalue()

def render_menu_preview(df_p, df_g, df_a, ordered_sections):
    for s in ordered_sections:
        prods_in_section = df_p[df_p['Section'] == s]
        if not prods_in_section.empty:
            st.markdown(f"**{s}**")
            for _, p in prods_in_section.iterrows():
                label = f"{p['Product_Name']} — {p['Price']} RSD" if p['Price'] > 0 else f"{p['Product_Name']} — cena nije dostupna"
                with st.expander(label):
                    if p['Description']: st.write(f"_{p['Description']}_")

# ============================================================
# UI - TABS
# ============================================================

tab_wolt, tab_photo = st.tabs(["🌐 Wolt Scraper", "📷 Photo Menu"])

with tab_wolt:
    # (Kod za Wolt scraper ostaje identičan tvom originalu)
    st.info("💡 **Instructions:** Možete uneti običan link restorana ili link specifične kolekcije.")
    link_input = st.text_input("Paste restaurant link:", placeholder="https://wolt.com/en/srb/...")
    if st.button("🚀 RUN"):
        if link_input:
            match = re.search(r'/(?:restaurant|venue)/([^/]+)', link_input.strip())
            if match:
                slug = match.group(1)
                raw = fetch_data(slug)
                if raw:
                    p, g, a, o_s = process_all_data(raw)
                    st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = p, g, a
                    st.session_state['ordered_sections'], st.session_state['slug'] = o_s, slug
                    st.success(f"Uspešno učitano: **{slug}**")
                else: st.error("Greška pri učitavanju.")
            else: st.error("Neispravan format linka.")

    if 'df_p' in st.session_state:
        # Prikaz downloada i preview-a
        excel_bytes = build_excel(st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'])
        st.download_button("📊 EXCEL", excel_bytes, f"menu_{st.session_state['slug']}.xlsx")
        render_menu_preview(st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['ordered_sections'])

# ============================================================
# TAB 2: PHOTO MENU - Gemini Vision
# ============================================================
with tab_photo:
    st.markdown("### 📷 Učitaj slike jelovnika (Gemini AI)")
    
    if not GEMINI_KEY:
        st.warning("⚠️ API ključ nije pronađen u config.json. Unesite ga ručno ispod.")
        current_key = st.text_input("Gemini API Key:", type="password")
    else:
        st.success("✅ API ključ učitan sa servera.")
        current_key = GEMINI_KEY

    restaurant_name_photo = st.text_input("Naziv restorana:", placeholder="npr. La Piazza")
    uploaded_images = st.file_uploader("Slike jelovnika:", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)

    if uploaded_images:
        cols = st.columns(min(len(uploaded_images), 5))
        for i, uf in enumerate(uploaded_images):
            with cols[i % 5]: st.image(uf, use_container_width=True)

    if st.button("🤖 ANALIZIRAJ JELOVNIK", type="primary"):
        if not current_key:
            st.error("⚠️ Nedostaje API ključ.")
        elif not uploaded_images:
            st.error("⚠️ Ubacite slike.")
        else:
            slug_photo = re.sub(r'[^\w]', '_', restaurant_name_photo.strip().lower()) if restaurant_name_photo.strip() else "restaurant"
            with st.spinner("🔍 Gemini analizira slike..."):
                try:
                    menu_data = extract_menu_with_gemini(uploaded_images, current_key)
                    df_p_photo, df_g_photo, df_a_photo, ordered_sections_photo = build_dataframes_from_photo(menu_data, slug_photo)
                    
                    st.session_state['photo_df_p'] = df_p_photo
                    st.session_state['photo_df_g'] = df_g_photo
                    st.session_state['photo_df_a'] = df_a_photo
                    st.session_state['photo_ordered_sections'] = ordered_sections_photo
                    st.session_state['photo_slug'] = slug_photo
                    st.success(f"✅ Uspešno prepoznato {len(df_p_photo)} jela!")
                except Exception as e:
                    st.error(f"⚠️ Greška: {e}")

    if 'photo_df_p' in st.session_state:
        excel_bytes_photo = build_excel(st.session_state['photo_df_p'], st.session_state['photo_df_g'], st.session_state['photo_df_a'])
        st.download_button("📊 PREUZMI EXCEL", excel_bytes_photo, f"menu_{st.session_state['photo_slug']}.xlsx")
        render_menu_preview(st.session_state['photo_df_p'], st.session_state['photo_df_g'], st.session_state['photo_df_a'], st.session_state['photo_ordered_sections'])
