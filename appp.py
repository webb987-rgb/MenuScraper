import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid
import json
import os
import google.generativeai as genai

# 1. Page Configuration
st.set_page_config(page_title="Wolt Scraper - PRO", page_icon="🍔", layout="wide")

# --- BEZBEDNO UČITAVANJE API KLJUČA ---
def get_gemini_key():
    if "GEMINI_API_KEY" in st.secrets:
        return st.secrets["GEMINI_API_KEY"]
    try:
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                config = json.load(f)
                return config.get("GEMINI_API_KEY")
    except:
        pass
    return None

GEMINI_KEY = get_gemini_key()

# CSS za UI
st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stExpander [data-testid="stExpanderDetails"] { padding-top: 0px !important; padding-left: 25px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    [data-testid="column"] { width: fit-content !important; min-width: fit-content !important; flex: none !important; padding-right: 15px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Menu Scraper")

# --- WOLT HELPER FUNCTIONS ---
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

# --- PHOTO MENU: GEMINI AI FUNCTIONS ---
def extract_menu_with_gemini(uploaded_files, api_key):
    genai.configure(api_key=api_key)
    
    # KORISTIMO TAČAN MODEL KOJI TVOJ NALOG PODRŽAVA
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = """Analiziraj priložene slike jelovnika i izvuci sva jela i cene.
    Vrati isključivo JSON objekat sa ovom strukturom:
    {
      "sections": [
        {
          "name": "Naziv sekcije (npr. Predjela)",
          "items": [
            {
              "name": "Naziv jela",
              "price": 650,
              "description": "Opis jela ako postoji"
            }
          ]
        }
      ]
    }
    Pravila: Cene moraju biti celi brojevi u RSD. Ako nema opisa, ostavi prazan string. Vrati samo sirov JSON."""

    content = []
    for uf in uploaded_files:
        img_data = uf.read()
        uf.seek(0)
        content.append({"mime_type": uf.type, "data": img_data})
    
    content.append(prompt)
    
    response = model.generate_content(content)
    text_response = response.text
    
    # Očisti odgovor da osiguraš validan JSON
    clean_json = re.sub(r'```json|```', '', text_response).strip()
    return json.loads(clean_json)

def build_dataframes_from_photo(menu_data):
    items_list = []
    ordered_sections = []
    for section in menu_data.get("sections", []):
        sec_name = section.get("name", "Ostalo").strip()
        if sec_name not in ordered_sections:
            ordered_sections.append(sec_name)
        for item in section.get("items", []):
            items_list.append({
                "External_ID": str(uuid.uuid4()),
                "Product_Name": str(item.get("name", "")).strip(),
                "Collection": "MENU",
                "Section": sec_name,
                "Price": int(item.get("price", 0)),
                "Image_1": "",
                "Description": str(item.get("description", "")).strip(),
                "Attribute_Groups": "",
                "Is_Alcoholic": "NO", "Is_Tobacco": "NO",
                "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
            })
    
    df_p = pd.DataFrame(items_list)
    df_g = pd.DataFrame(columns=["External_ID", "Max", "Min", "Name", "Multiple_Selection", "Collapse_by_Default", "Attributes"])
    df_a = pd.DataFrame(columns=["External_ID", "Group_ID_Internal", "Name", "Price", "Enabled", "Selected_by_Default"])
    return df_p, df_g, df_a, ordered_sections

def build_excel(df_p, df_g, df_a):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df_p.to_excel(w, index=False, sheet_name='Products')
        df_g.to_excel(w, index=False, sheet_name='Attribute Groups')
        if not df_a.empty and 'Group_ID_Internal' in df_a.columns:
            df_a.drop(columns=['Group_ID_Internal']).to_excel(w, index=False, sheet_name='Attributes')
        else:
            df_a.to_excel(w, index=False, sheet_name='Attributes')
    return out.getvalue()

def render_menu_preview(df_p, df_g, df_a, ordered_sections):
    for s in ordered_sections:
        prods = df_p[df_p['Section'] == s]
        if not prods.empty:
            st.markdown(f"**{s}**")
            for _, p in prods.iterrows():
                with st.expander(f"{p['Product_Name']} — {p['Price']} RSD"):
                    if p['Description']: st.write(f"_{p['Description']}_")
                    g_ids = [gid for gid in str(p['Attribute_Groups']).split(",") if gid]
                    for gid in g_ids:
                        if not df_g.empty:
                            g_i = df_g[df_g['External_ID'] == gid]
                            if not g_i.empty:
                                with st.expander(f"└ {g_i.iloc[0]['Name']}"):
                                    attrs = df_a[df_a['Group_ID_Internal'] == gid]
                                    for _, a in attrs.iterrows():
                                        st.write(f"• {a['Name']} ({a['Price']} RSD)")

# --- UI TABS ---
tab_wolt, tab_photo = st.tabs(["🌐 Wolt Scraper", "📷 Photo Menu"])

with tab_wolt:
    link_input = st.text_input("Paste Wolt link:", placeholder="https://wolt.com/en/srb/...")
    if st.button("🚀 RUN WOLT"):
        match = re.search(r'/(?:restaurant|venue)/([^/]+)', link_input.strip())
        if match:
            slug = match.group(1)
            raw = fetch_data(slug)
            if raw:
                p, g, a, o_s = process_all_data(raw)
                st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = p, g, a
                st.session_state['ordered_sections'], st.session_state['slug'] = o_s, slug
                st.success(f"Uspešno učitano: {slug}")

    if 'df_p' in st.session_state:
        st.markdown("### 📥 Download")
        col_ex, col_zip, _ = st.columns([1, 1.2, 4])
        with col_ex:
            excel_bytes = build_excel(st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'])
            st.download_button("📊 EXCEL", excel_bytes, f"menu_{st.session_state['slug']}.xlsx")
        
        with col_zip:
            if st.button("🖼️ DOWNLOAD PICTURES"):
                img_df = st.session_state['df_p'][st.session_state['df_p']['Image_1'] != ""]
                z_io = io.BytesIO()
                with zipfile.ZipFile(z_io, "w") as zf:
                    for _, r in img_df.iterrows():
                        try:
                            res = requests.get(r['Image_1'], timeout=10)
                            name = re.sub(r'[^\w\s-]', '', r['Product_Name']).strip().replace(' ', '_')
                            zf.writestr(f"{name}.jpg", res.content)
                        except: continue
                st.session_state['zip_ready'] = z_io.getvalue()
            if 'zip_ready' in st.session_state:
                st.download_button("🔥 SAVE ZIP FILE", st.session_state['zip_ready'], f"images_{st.session_state['slug']}.zip")
        
        render_menu_preview(st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['ordered_sections'])


with tab_photo:
    st.markdown("### 📷 AI Photo Extraction")
    
    active_key = GEMINI_KEY if GEMINI_KEY else st.text_input("Gemini API Key:", type="password")
    if not active_key: st.warning("⚠️ API ključ nije podešen.")
    
    rest_name = st.text_input("Naziv restorana:", placeholder="npr. La Piazza")
    uploaded_images = st.file_uploader("Uploaduj slike:", type=["jpg", "png", "webp"], accept_multiple_files=True)
    
    if st.button("🤖 ANALIZIRAJ JELOVNIK", type="primary"):
        if active_key and uploaded_images:
            with st.spinner("Gemini 2.5 Flash analizira slike..."):
                try:
                    menu_json = extract_menu_with_gemini(uploaded_images, active_key)
                    p, g, a, o = build_dataframes_from_photo(menu_json)
                    st.session_state['p_df_p'], st.session_state['p_df_g'], st.session_state['p_df_a'] = p, g, a
                    st.session_state['p_ordered_sections'], st.session_state['p_slug'] = o, rest_name
                    st.success("Gotovo! Uspešno izvučeno.")
                except Exception as e: st.error(f"Greška: {e}")

    if 'p_df_p' in st.session_state:
        excel_bytes_p = build_excel(st.session_state['p_df_p'], st.session_state['p_df_g'], st.session_state['p_df_a'])
        st.download_button("📊 DOWNLOAD EXCEL", excel_bytes_p, f"menu_{st.session_state['p_slug']}.xlsx")
        render_menu_preview(st.session_state['p_df_p'], st.session_state['p_df_g'], st.session_state['p_df_a'], st.session_state['p_ordered_sections'])
