import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid
import json
import os
import concurrent.futures
import google.generativeai as genai

# 1. Page Configuration
st.set_page_config(page_title="Menu Scraper PRO", page_icon="🍔", layout="wide")

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
    .stDataFrame { border: 1px solid #e6e9ef; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Menu Scraper PRO")

# --- HELPER: Primena marže, fiksnog iznosa i zaokruživanja ---
def apply_price_logic(price, markup_percent, fixed_amount, round_up):
    new_price = price * (1 + markup_percent / 100)
    new_price += fixed_amount
    final_price = int(new_price)
    if round_up and final_price > 0:
        final_price = ((final_price + 9) // 10) * 10
    return final_price

# --- HELPER: TURBO PREUZIMANJE SLIKE ---
def download_single_image(url, product_name):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            name = re.sub(r'[^\w\s-]', '', str(product_name)).strip().replace(' ', '_')
            name = f"{name}_{str(uuid.uuid4())[:4]}.jpg"
            return name, res.content
    except:
        pass
    return None, None

# --- WOLT LOGIKA ---
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
                "External_ID": new_aid, "Group_ID_Internal": new_gid,
                "Name": val.get("name", ""), "Price": val.get("price", 0) / 100,
                "Enabled": "YES", "Selected_by_Default": "NO"
            })
        groups_raw.append({
            "External_ID": new_gid, "Max": 10, "Min": 0, "Name": group.get("name", "Option"),
            "Multiple_Selection": "NO", "Collapse_by_Default": "NO", "Attributes": ",".join(a_ids)
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
                    if img_id: 
                        img_url = f"https://imageproxy.wolt.com/assets/{img_id}?w=960"
                    elif first_img.get('url'): 
                        img_url = first_img.get('url')

            gids = [wolt_group_to_new_id[o.get("option_id")] for o in item.get("options", []) if o.get("option_id") in wolt_group_to_new_id]
            items_list.append({
                "External_ID": new_iid, "Product_Name": item.get("name", ""), "Collection": "MENU",
                "Section": cat_name, "Price": puna_cena, "Image_1": img_url,
                "Description": item.get("description", "").replace("\n", " ").strip(),
                "Attribute_Groups": ",".join(gids), "Is_Alcoholic": "NO", "Is_Tobacco": "NO", 
                "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
            })
    return pd.DataFrame(items_list), pd.DataFrame(groups_raw), pd.DataFrame(attrs_raw), ordered_sections

# --- GEMINI AI FUNKCIJA ---
def extract_menu_with_gemini_core(content_to_send, api_keys_list):
    prompt = """Analiziraj priloženi sadržaj (slike, PDF ili tekst sa sajta) i izvuci sva jela i cene.
    Vrati ISKLJUČIVO JSON objekat sa ovom strukturom:
    {"sections": [{"name": "Naziv sekcije", "items": [{"name": "Naziv jela", "price": 100, "description": "Opis jela ako postoji"}]}]}
    Pravila: Cene moraju biti celi brojevi u RSD. Ako nema opisa, ostavi prazan string. Vrati samo sirov JSON bez markdowna."""
    
    full_request = content_to_send + [prompt]
    last_error = None
    for idx, key in enumerate(api_keys_list):
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(full_request)
            clean_json = re.sub(r'```json|```', '', response.text).strip()
            return json.loads(clean_json)
        except Exception as e:
            last_error = e
            if idx < len(api_keys_list) - 1:
                st.warning(f"Ključ {idx+1} je dostigao limit. Prebacujem na sledeći...")
                continue
            else: 
                raise Exception(f"Svi ključevi su blokirani/potrošeni. Poslednja greška: {last_error}")

# --- POMOĆNE FUNKCIJE ZA TABELE ---
def build_dataframes_from_ai(menu_data, markup, fixed_amount, round_up):
    items_list, ordered_sections = [], []
    for section in menu_data.get("sections", []):
        sec_name = section.get("name", "Ostalo").strip()
        if sec_name not in ordered_sections: ordered_sections.append(sec_name)
        for item in section.get("items", []):
            p = apply_price_logic(item.get("price", 0), markup, fixed_amount, round_up)
            items_list.append({
                "External_ID": str(uuid.uuid4()), "Product_Name": str(item.get("name", "")).strip(),
                "Collection": "MENU", "Section": sec_name, "Price": p,
                "Description": str(item.get("description", "")).strip(), "Image_1": "",
                "Attribute_Groups": "", "Is_Alcoholic": "NO", "Is_Tobacco": "NO",
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
        if not df_a.empty:
            cols_to_save = [c for c in df_a.columns if c != 'Group_ID_Internal']
            df_a[cols_to_save].to_excel(w, index=False, sheet_name='Attributes')
        else:
            df_a.to_excel(w, index=False, sheet_name='Attributes')
    return out.getvalue()

# ============================================================
# UI TABS
# ============================================================
tab_wolt, tab_photo, tab_link_ai, tab_edit = st.tabs(["🌐 Wolt Scraper", "📄 Photo/PDF AI Menu", "🔗 Link AI Menu", "📈 Uvećanje cena"])

# --- TAB 1: WOLT ---
with tab_wolt:
    link_input = st.text_input("Paste Wolt link:", placeholder="https://wolt.com/en/srb/...")
    if st.button("🚀 RUN"):
        match = re.search(r'/(?:restaurant|venue)/([^/]+)', link_input.strip())
        if match:
            slug = match.group(1)
            raw = fetch_data(slug)
            if raw:
                p, g, a, o_s = process_all_data(raw)
                st.session_state['w_df_p'], st.session_state['w_df_g'], st.session_state['w_df_a'] = p, g, a
                st.session_state['w_ordered_sections'], st.session_state['w_slug'] = o_s, slug
                st.success(f"Uspešno učitano: {slug}")

    if 'w_df_p' in st.session_state:
        st.markdown("### 📊 Pregled tabele")
        st.dataframe(st.session_state['w_df_p'], use_container_width=True)
        
        st.markdown("### 📥 Download")
        col_ex, col_zip, _ = st.columns([1, 1.2, 4])
        with col_ex:
            excel_bytes = build_excel(st.session_state['w_df_p'], st.session_state['w_df_g'], st.session_state['w_df_a'])
            st.download_button("📊 PREUZMI EXCEL", excel_bytes, f"wolt_menu_{st.session_state['w_slug']}.xlsx")
        
        with col_zip:
            if st.button("🖼️ PRIPREMI SLIKE"):
                with st.spinner("⚡ Turbo pakovanje..."):
                    img_df = st.session_state['w_df_p'][st.session_state['w_df_p']['Image_1'] != ""]
                    z_io = io.BytesIO()
                    img_count = 0
                    tasks = [(r['Image_1'], r['Product_Name']) for _, r in img_df.iterrows()]
                    with zipfile.ZipFile(z_io, "w") as zf:
                        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                            future_to_img = {executor.submit(download_single_image, url, name): name for url, name in tasks}
                            for future in concurrent.futures.as_completed(future_to_img):
                                filename, content = future.result()
                                if filename and content:
                                    zf.writestr(filename, content)
                                    img_count += 1
                    st.session_state['zip_ready'] = z_io.getvalue()
                    st.session_state['zip_count'] = img_count
            
            if 'zip_ready' in st.session_state:
                st.download_button(f"🔥 PREUZMI ZIP ({st.session_state['zip_count']} slika)", st.session_state['zip_ready'], f"images_{st.session_state['w_slug']}.zip")

# --- TAB 2: PHOTO/PDF AI ---
with tab_photo:
    st.subheader("AI Analiza slika i PDF dokumenata")
    active_keys = GEMINI_KEYS_LIST if GEMINI_KEYS_LIST else [st.text_input("API Ključ:", type="password")]

    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1: rest_name_p = st.text_input("Naziv restorana:", key="rest_p")
    with col2: markup_p = st.number_input("Uvećaj %:", min_value=0, value=0, step=5, key="mark_p")
    with col3: fixed_p = st.number_input("Fiksno + (RSD):", min_value=0, value=0, step=10, key="fix_p")
    with col4: 
        st.write("")
        round_p = st.checkbox("Zaokruži 10", value=False, key="round_p_1")
        
    files = st.file_uploader("Uploaduj Slike/PDF:", type=["jpg","jpeg","png","webp","pdf"], accept_multiple_files=True)
    
    if st.button("🤖 ANALIZIRAJ FAJLOVE", type="primary"):
        if files and active_keys:
            with st.spinner("AI čita..."):
                try:
                    content = []
                    for f in files:
                        d = f.read(); f.seek(0)
                        content.append({"mime_type": f.type, "data": d})
                    res = extract_menu_with_gemini_core(content, active_keys)
                    st.session_state['ai_res_photo'] = res
                    st.session_state['ai_name_photo'] = rest_name_p if rest_name_p else "Meni"
                except Exception as e: st.error(str(e))

    if 'ai_res_photo' in st.session_state:
        df_p, df_g, df_a, sects = build_dataframes_from_ai(st.session_state['ai_res_photo'], markup_p, fixed_p, round_p)
        st.markdown("### 📊 Pregled generisane tabele")
        st.dataframe(df_p, use_container_width=True)
        st.download_button("📊 PREUZMI EXCEL", build_excel(df_p, df_g, df_a), f"menu_{st.session_state['ai_name_photo']}.xlsx")

# --- TAB 3: LINK AI ---
with tab_link_ai:
    st.subheader("AI Analiza sajta (Jina Reader)")
    link_input_ai = st.text_input("Unesi link sajta:", placeholder="https://www.restoran.rs/jelovnik/")
    
    col_l1, col_l2, col_l3, col_l4 = st.columns([2, 1, 1, 1])
    with col_l1: rest_name_l = st.text_input("Naziv restorana:", key="rest_l")
    with col_l2: markup_l = st.number_input("Uvećaj %:", min_value=0, value=0, step=5, key="mark_l")
    with col_l3: fixed_l = st.number_input("Fiksno + (RSD):", min_value=0, value=0, step=10, key="fix_l")
    with col_l4:
        st.write("")
        round_l = st.checkbox("Zaokruži 10", value=False, key="round_l_2")

    if st.button("🌐 ANALIZIRAJ LINK", type="primary"):
        if link_input_ai and GEMINI_KEYS_LIST:
            with st.spinner("🤖 Čitam sajt..."):
                try:
                    jina_url = f"https://r.jina.ai/{link_input_ai}"
                    r = requests.get(jina_url, headers={"Accept": "application/json"}, timeout=45)
                    if r.status_code == 200:
                        text_only = r.json().get("data", {}).get("content", "")
                        content = [f"Ovo je tekst sa sajta. Izvuci jelovnik:\n\n {text_only[:35000]}"]
                        res = extract_menu_with_gemini_core(content, GEMINI_KEYS_LIST)
                        st.session_state['ai_res_link'] = res
                        st.session_state['ai_name_link'] = rest_name_l if rest_name_l else "Link_Meni"
                except Exception as e: st.error(f"Greška: {e}")

    if 'ai_res_link' in st.session_state:
        df_l, df_gl, df_al, sects_l = build_dataframes_from_ai(st.session_state['ai_res_link'], markup_l, fixed_l, round_l)
        st.markdown("### 📊 Pregled generisane tabele")
        st.dataframe(df_l, use_container_width=True)
        st.download_button("📊 PREUZMI EXCEL", build_excel(df_l, df_gl, df_al), f"menu_{st.session_state['ai_name_link']}_link.xlsx")

# --- TAB 4: UVEĆANJE CENA (IZMENJEN NAZIV) ---
with tab_edit:
    st.subheader("📈 Masovno uvećanje cena u Excelu")
    uploaded_edit_file = st.file_uploader("Uploaduj Excel fajl (.xlsx):", type=["xlsx"], key="edit_uploader")
    
    if uploaded_edit_file:
        try:
            sheets = pd.read_excel(uploaded_edit_file, sheet_name=None)
            df_p_edit = sheets.get('Products', pd.DataFrame())
            df_g_edit = sheets.get('Attribute Groups', pd.DataFrame())
            df_a_edit = sheets.get('Attributes', pd.DataFrame())
            
            st.markdown("### 📊 Pregled učitane tabele")
            st.dataframe(df_p_edit, use_container_width=True)
            
            st.markdown("---")
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                st.markdown("### 🍔 Glavna Jela (Products)")
                mark_p_edit = st.number_input("Products: Uvećaj %:", min_value=0, value=0, step=5, key="mpe")
                fix_p_edit = st.number_input("Products: Fiksno + (RSD):", min_value=0, value=0, step=10, key="fpe")
            with col_e2:
                st.markdown("### 🧩 Dodaci (Attributes)")
                mark_a_edit = st.number_input("Attributes: Uvećaj %:", min_value=0, value=0, step=5, key="mae")
                fix_a_edit = st.number_input("Attributes: Fiksno + (RSD):", min_value=0, value=0, step=10, key="fae")
            round_edit = st.checkbox("Zaokruži nove cene na 10 RSD", value=False, key="re")
            
            if st.button("🔄 PRERAČUNAJ", type="primary"):
                # Kreiramo kopije za obradu da ne menjamo preview odmah
                res_p = df_p_edit.copy()
                res_a = df_a_edit.copy()
                if not res_p.empty and 'Price' in res_p.columns:
                    res_p['Price'] = res_p['Price'].apply(lambda x: apply_price_logic(x, mark_p_edit, fix_p_edit, round_edit))
                if not res_a.empty and 'Price' in res_a.columns:
                    res_a['Price'] = res_a['Price'].apply(lambda x: apply_price_logic(x, mark_a_edit, fix_a_edit, round_edit))
                
                st.markdown("### 📊 Pregled novih cena")
                st.dataframe(res_p, use_container_width=True)
                
                st.session_state['edited_excel'] = build_excel(res_p, df_g_edit, res_a)
                st.success("Cene su preračunate!")

            if 'edited_excel' in st.session_state:
                st.download_button("📥 PREUZMI AZURIRAN EXCEL", st.session_state['edited_excel'], "azuriran_cenovnik.xlsx")
        except Exception as e:
            st.error(f"Greška: {e}")
