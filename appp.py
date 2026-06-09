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

# --- SECURE LOADING OF MULTIPLE API KEYS ---
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

# CSS for UI Customization
st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stExpander [data-testid="stExpanderDetails"] { padding-top: 0px !important; padding-left: 25px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    .stDataFrame { border: 1px solid #e6e9ef; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Menu Scraper PRO")

# --- CURRENCY / MARKET SELECTION ---
currency = st.radio("Select Market / Currency:", ["RSD", "EUR"], horizontal=True)

# --- HELPER: Apply Markup, Fixed Amount, and Rounding Logic ---
def apply_price_logic(price, markup_percent, fixed_amount, round_up, curr):
    new_price = price * (1 + markup_percent / 100)
    new_price += fixed_amount
    
    if curr == "RSD":
        final_price = int(new_price)
        if round_up and final_price > 0:
            final_price = ((final_price + 9) // 10) * 10
        return final_price
    else:
        return round(new_price, 2)

# --- HELPER: HIGH-SPEED IMAGE DOWNLOAD ---
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

# --- WOLT SCRAPER LOGIC ---
def fetch_data(slug):
    api_url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(api_url, headers=headers, timeout=15)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def process_all_data(data, curr):
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
            
            attr_price = val.get("price", 0) / 100
            attr_price = int(attr_price) if curr == "RSD" else round(attr_price, 2)
            
            attrs_raw.append({
                "External_ID": new_aid, "Group_ID_Internal": new_gid,
                "Name": val.get("name", ""), "Price": attr_price,
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
            
            raw_price = (item.get("base_price") or item.get("price") or 0) / 100
            puna_cena = int(raw_price) if curr == "RSD" else round(raw_price, 2)
            
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

# --- GEMINI AI FUNCTION ---
def extract_menu_with_gemini_core(content_to_send, api_keys_list, curr):
    if curr == "RSD":
        price_rule = "Prices must be whole numbers (integers) in RSD."
    else:
        price_rule = "Prices must be numbers (can contain decimal values) in EUR."

    prompt = f"""Analyze the attached content (images, PDF, or website text) and extract all items and prices.
    Return EXCLUSIVELY a JSON object with this exact structure:
    {{"sections": [{{"name": "Section Name", "items": [{{"name": "Item Name", "price": 100, "description": "Item description if available"}}]}}]}}
    Rules: {price_rule} If there is no description, leave it as an empty string. Return only raw JSON without markdown code blocks."""
    
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
                st.warning(f"Key {idx+1} reached its limit. Switching to the next key...")
                continue
            else: 
                raise Exception(f"All API keys are blocked or exhausted. Last error: {last_error}")

# --- AI DESCRIPTION GENERATOR FUNCTION ---
def generate_descriptions_batch(product_names, api_keys_list, language, desc_length):
    length_map = {
        "Kratko (1 rečenica)": "1 short sentence, max 15 words",
        "Srednje (2-3 rečenice)": "2-3 sentences, max 50 words",
        "Dugo (4-5 rečenica)": "4-5 sentences, max 100 words"
    }
    length_instruction = length_map.get(desc_length, "2-3 sentences, max 50 words")

    if language == "Srpski":
        lang_instruction = "Write all descriptions in Serbian language (Latin script)."
    elif language == "Bosanski":
        lang_instruction = "Write all descriptions in Bosnian language (Latin script)."
    elif language == "Hrvatski":
        lang_instruction = "Write all descriptions in Croatian language."
    else:
        lang_instruction = "Write all descriptions in English."

    items_json = json.dumps(product_names, ensure_ascii=False)

    prompt = f"""You are a professional food copywriter for restaurant menus.
{lang_instruction}
For each dish name in the list below, write an appealing and appetizing description.
Description length: {length_instruction}.
Be creative, use sensory language (taste, smell, texture). Do NOT invent ingredients that are not typical for the dish.

Input list (JSON array of dish names):
{items_json}

Return EXCLUSIVELY a JSON object in this exact format (no markdown, no explanation):
{{"descriptions": {{"DISH_NAME": "description text", ...}}}}

Every dish name from the input must appear as a key in the output. Return only raw JSON."""

    last_error = None
    for idx, key in enumerate(api_keys_list):
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(prompt, generation_config={"max_output_tokens": 8192})
            raw = response.text.strip()
            # Ukloni markdown backticks
            clean = re.sub(r'```json|```', '', raw).strip()
            # Izvuci samo JSON objekat između prve { i zadnje }
            start = clean.find('{')
            end = clean.rfind('}')
            if start != -1 and end != -1:
                clean = clean[start:end+1]
            return json.loads(clean)
        except json.JSONDecodeError as e:
            last_error = e
            if idx < len(api_keys_list) - 1:
                st.warning(f"Key {idx+1} greška parsiranja. Pokušavam sljedeći ključ...")
                continue
            else:
                raise Exception(f"JSON parsing greška. Last error: {last_error}")
        except Exception as e:
            last_error = e
            if idx < len(api_keys_list) - 1:
                st.warning(f"Key {idx+1} reached its limit. Switching to the next key...")
                continue
            else:
                raise Exception(f"All API keys are blocked or exhausted. Last error: {last_error}")

# --- TABLE DATA GENERATION HELPERS ---
def build_dataframes_from_ai(menu_data, markup, fixed_amount, round_up, curr):
    items_list, ordered_sections = [], []
    for section in menu_data.get("sections", []):
        sec_name = section.get("name", "Other").strip()
        if sec_name not in ordered_sections: ordered_sections.append(sec_name)
        for item in section.get("items", []):
            p = apply_price_logic(item.get("price", 0), markup, fixed_amount, round_up, curr)
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

def render_menu_preview(df_p, df_g, df_a, ordered_sections, curr):
    for s in ordered_sections:
        prods = df_p[df_p['Section'] == s]
        if not prods.empty:
            st.markdown(f"**{s}**")
            for _, p in prods.iterrows():
                with st.expander(f"{p['Product_Name']} — {p['Price']} {curr}"):
                    if p['Description']: st.write(f"_{p['Description']}_")
                    if 'Attribute_Groups' in p and p['Attribute_Groups']:
                        g_ids = [gid for gid in str(p['Attribute_Groups']).split(",") if gid]
                        for gid in g_ids:
                            if not df_g.empty:
                                g_i = df_g[df_g['External_ID'] == gid]
                                if not g_i.empty:
                                    st.write(f"└ Option: {g_i.iloc[0]['Name']}")

# ============================================================
# UI TABS CONFIGURATION
# ============================================================
tab_wolt, tab_photo, tab_link_ai, tab_edit, tab_desc = st.tabs([
    "🌐 Wolt Scraper", "📄 Photo/PDF AI Menu", "🔗 Link AI Menu", "📈 Price Markup", "✍️ AI Opisi"
])

# --- TAB 1: WOLT SCRAPER ---
with tab_wolt:
    st.info('💡 **Important:** Please insert the restaurant link strictly using this format: `"https://wolt.com/en/srb/nis/restaurant/nn-chicken"`', icon="ℹ️")
    link_input = st.text_input("Paste Wolt link:", placeholder="https://wolt.com/en/srb/nis/restaurant/...")
    
    if st.button("🚀 RUN", help="Extract structure, items, choices, and images directly from the Wolt API via venue slug"):
        match = re.search(r'/(?:restaurant|venue)/([^/]+)', link_input.strip())
        if match:
            slug = match.group(1)
            raw = fetch_data(slug)
            if raw:
                p, g, a, o_s = process_all_data(raw, currency)
                st.session_state['w_df_p'], st.session_state['w_df_g'], st.session_state['w_df_a'] = p, g, a
                st.session_state['w_ordered_sections'], st.session_state['w_slug'] = o_s, slug
                st.success(f"Successfully loaded: {slug}")

    if 'w_df_p' in st.session_state:
        with st.expander("👀 CLICK TO VIEW THE FULL DATA TABLE"):
            st.dataframe(st.session_state['w_df_p'], height=600, use_container_width=True)
        
        st.markdown("### 📥 Download Output")
        col_ex, col_zip, _ = st.columns([1, 1.2, 4])
        with col_ex:
            excel_bytes = build_excel(st.session_state['w_df_p'], st.session_state['w_df_g'], st.session_state['w_df_a'])
            st.download_button("📊 DOWNLOAD EXCEL", excel_bytes, f"wolt_menu_{st.session_state['w_slug']}.xlsx", help="Export the scraped dataset structured into standard Products, Groups, and Attributes sheets")
        
        with col_zip:
            if st.button("🖼️ PREPARE IMAGES", help="Trigger simultaneous, asynchronous downloads of all item photos from proxy URLs into a local stream"):
                with st.spinner("⚡ Turbo packing..."):
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
                st.download_button(f"🔥 DOWNLOAD ZIP ({st.session_state['zip_count']} images)", st.session_state['zip_ready'], f"images_{st.session_state['w_slug']}.zip", help="Download the generated archive containing item photos mapped to sanitized product filenames")

# --- TAB 2: PHOTO/PDF AI ---
with tab_photo:
    st.subheader("AI Image & PDF Menu Analysis")
    active_keys = GEMINI_KEYS_LIST if GEMINI_KEYS_LIST else [st.text_input("API Key:", type="password")]

    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1: rest_name_p = st.text_input("Restaurant Name:", key="rest_p")
    with col2: markup_p = st.number_input("Markup %:", min_value=0, value=0, step=5, key="mark_p")
    with col3: fixed_p = st.number_input(f"Fixed Add-on ({currency}):", min_value=0.0, value=0.0, step=10.0 if currency == "RSD" else 1.0, key="fix_p")
    with col4: 
        st.write("")
        round_p = st.checkbox("Round to 10", value=False, key="round_p_1", help="Only applies when operating under RSD currency settings")
        
    files = st.file_uploader("Upload Images/PDF:", type=["jpg","jpeg","png","webp","pdf"], accept_multiple_files=True)
    
    if st.button("🤖 ANALYZE FILES", type="primary", help="Upload specified visual components or text files directly to Gemini multimodal models for structured item tracking"):
        if files and active_keys:
            with st.spinner("AI is reading..."):
                try:
                    content = []
                    for f in files:
                        d = f.read(); f.seek(0)
                        content.append({"mime_type": f.type, "data": d})
                    res = extract_menu_with_gemini_core(content, active_keys, currency)
                    st.session_state['ai_res_photo'] = res
                    st.session_state['ai_name_photo'] = rest_name_p if rest_name_p else "Menu"
                except Exception as e: st.error(str(e))

    if 'ai_res_photo' in st.session_state:
        df_p, df_g, df_a, sects = build_dataframes_from_ai(st.session_state['ai_res_photo'], markup_p, fixed_p, round_p, currency)
        with st.expander("👀 CLICK TO VIEW THE FULL DATA TABLE"):
            st.dataframe(df_p, height=600, use_container_width=True)
        
        st.download_button("📊 DOWNLOAD EXCEL", build_excel(df_p, df_g, df_a), f"menu_{st.session_state['ai_name_photo']}.xlsx", help="Export processed AI text data cleanly formatted as a standardized Excel output file")

# --- TAB 3: LINK AI ---
with tab_link_ai:
    st.subheader("AI Website Analysis (Jina Reader)")
    link_input_ai = st.text_input("Enter website link:", placeholder="https://www.restaurant.com/menu/")
    
    col_l1, col_l2, col_l3, col_l4 = st.columns([2, 1, 1, 1])
    with col_l1: rest_name_l = st.text_input("Restaurant Name:", key="rest_l")
    with col_l2: markup_l = st.number_input("Markup %:", min_value=0, value=0, step=5, key="mark_l")
    with col_l3: fixed_l = st.number_input(f"Fixed Add-on ({currency}):", min_value=0.0, value=0.0, step=10.0 if currency == "RSD" else 1.0, key="fix_l")
    with col_l4:
        st.write("")
        round_l = st.checkbox("Round to 10", value=False, key="round_l_2", help="Only applies when operating under RSD currency settings")

    if st.button("🌐 ANALYZE LINK", type="primary", help="Scrape semantic markup content from target menu web pages using the Jina AI engine prior to sending to the language model"):
        if link_input_ai and GEMINI_KEYS_LIST:
            with st.spinner("🤖 Reading website..."):
                try:
                    jina_url = f"https://r.jina.ai/{link_input_ai}"
                    r = requests.get(jina_url, headers={"Accept": "application/json"}, timeout=45)
                    if r.status_code == 200:
                        text_only = r.json().get("data", {}).get("content", "")
                        content = [f"This is raw text from the website. Extract the complete menu:\n\n {text_only[:35000]}"]
                        res = extract_menu_with_gemini_core(content, GEMINI_KEYS_LIST, currency)
                        st.session_state['ai_res_link'] = res
                        st.session_state['ai_name_link'] = rest_name_l if rest_name_l else "Link_Menu"
                except Exception as e: st.error(f"Error: {e}")

    if 'ai_res_link' in st.session_state:
        df_l, df_gl, df_al, sects_l = build_dataframes_from_ai(st.session_state['ai_res_link'], markup_l, fixed_l, round_l, currency)
        with st.expander("👀 CLICK TO VIEW THE FULL DATA TABLE"):
            st.dataframe(df_l, height=600, use_container_width=True)
            
        st.download_button("📊 DOWNLOAD EXCEL", build_excel(df_l, df_gl, df_al), f"menu_{st.session_state['ai_name_link']}_link.xlsx", help="Export scraped live URL outputs directly into a single multi-sheet spreadsheet workbook")

# --- TAB 4: PRICE MARKUP ENGINE ---
with tab_edit:
    st.subheader("📈 Bulk Price Increase in Excel")
    uploaded_edit_file = st.file_uploader("Upload Excel file (.xlsx):", type=["xlsx"], key="edit_uploader")
    
    if uploaded_edit_file:
        try:
            sheets = pd.read_excel(uploaded_edit_file, sheet_name=None)
            df_p_edit = sheets.get('Products', pd.DataFrame())
            df_g_edit = sheets.get('Attribute Groups', pd.DataFrame())
            df_a_edit = sheets.get('Attributes', pd.DataFrame())
            
            with st.expander("👀 CLICK TO VIEW THE UPLOADED TABLE"):
                st.dataframe(df_p_edit, height=600, use_container_width=True)
            
            st.markdown("---")
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                st.markdown("### 🍔 Main Dishes (Products)")
                mark_p_edit = st.number_input("Products: Markup %:", min_value=0, value=0, step=5, key="mpe")
                fix_p_edit = st.number_input(f"Products: Fixed Add-on ({currency}):", min_value=0.0, value=0.0, step=10.0 if currency == "RSD" else 1.0, key="fpe")
            with col_e2:
                st.markdown("### 🧩 Modifiers (Attributes)")
                mark_a_edit = st.number_input("Attributes: Markup %:", min_value=0, value=0, step=5, key="mae")
                fix_a_edit = st.number_input(f"Attributes: Fixed Add-on ({currency}):", min_value=0.0, value=0.0, step=10.0 if currency == "RSD" else 1.0, key="fae")
            
            round_edit = st.checkbox("Round new prices to 10 (RSD only)", value=False, key="re")
            
            if st.button("🔄 RECALCULATE", type="primary", help="Apply custom markup percentages and flat fees to separate matrix components instantly"):
                res_p = df_p_edit.copy()
                res_a = df_a_edit.copy()
                if not res_p.empty and 'Price' in res_p.columns:
                    res_p['Price'] = res_p['Price'].apply(lambda x: apply_price_logic(x, mark_p_edit, fix_p_edit, round_edit, currency))
                if not res_a.empty and 'Price' in res_a.columns:
                    res_a['Price'] = res_a['Price'].apply(lambda x: apply_price_logic(x, mark_a_edit, fix_a_edit, round_edit, currency))
                
                st.session_state['edited_excel'] = build_excel(res_p, df_g_edit, res_a)
                st.session_state['edited_df_p'] = res_p
                st.success("Prices have been recalculated!")

            if 'edited_excel' in st.session_state and 'edited_df_p' in st.session_state:
                with st.expander("👀 CLICK TO VIEW NEW PRICES", expanded=True):
                    st.dataframe(st.session_state['edited_df_p'], height=600, use_container_width=True)
                    
                st.download_button("📥 DOWNLOAD UPDATED EXCEL", st.session_state['edited_excel'], "updated_price_list.xlsx", help="Download the newly compiled menu layout file with recalculated pricing adjustments applied")
                
        except Exception as e:
            st.error(f"Error: {e}")

# --- TAB 5: AI OPISI ---
with tab_desc:
    st.subheader("✍️ AI Generator Opisa Jela")
    st.info("💡 Uploaduj Excel, sliku ili PDF sa menijem. AI će automatski generisati apetitne opise za sva jela.", icon="ℹ️")

    uploaded_desc_file = st.file_uploader(
        "Upload fajl (Excel, slika ili PDF):",
        type=["xlsx", "jpg", "jpeg", "png", "webp", "pdf"],
        key="desc_uploader"
    )

    if uploaded_desc_file:
        try:
            file_type = uploaded_desc_file.type
            df_desc = pd.DataFrame()
            df_desc_g = pd.DataFrame()
            df_desc_a = pd.DataFrame()
            source_is_excel = False

            # --- EXCEL ---
            if file_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                sheets_desc = pd.read_excel(uploaded_desc_file, sheet_name=None)
                df_desc = sheets_desc.get('Products', pd.DataFrame()).copy()
                df_desc_g = sheets_desc.get('Attribute Groups', pd.DataFrame())
                df_desc_a = sheets_desc.get('Attributes', pd.DataFrame())
                source_is_excel = True

            # --- SLIKA ILI PDF ---
            else:
                if not GEMINI_KEYS_LIST:
                    st.warning("⚠️ Gemini API ključ nije pronađen. Provjeri secrets ili config.json.")
                    st.stop()

                with st.spinner("🤖 AI čita meni iz fajla..."):
                    file_data = uploaded_desc_file.read()
                    uploaded_desc_file.seek(0)
                    content = [{"mime_type": file_type, "data": file_data}]
                    # Iskoristi postojeći extract koji vraća {sections: [{name, items: [{name, price, description}]}]}
                    extracted = extract_menu_with_gemini_core(content, GEMINI_KEYS_LIST, currency)

                # Pretvori u DataFrame isti kao Excel format
                items_list = []
                for section in extracted.get("sections", []):
                    sec_name = section.get("name", "Menu").strip()
                    for item in section.get("items", []):
                        items_list.append({
                            "External_ID": str(uuid.uuid4()),
                            "Product_Name": str(item.get("name", "")).strip(),
                            "Collection": "MENU",
                            "Section": sec_name,
                            "Price": item.get("price", 0),
                            "Description": str(item.get("description", "")).strip(),
                            "Image_1": "",
                            "Attribute_Groups": "",
                            "Is_Alcoholic": "NO",
                            "Is_Tobacco": "NO",
                            "SuperCollection": "",
                            "Section_Order": 1,
                            "Collection_Order": 1
                        })
                df_desc = pd.DataFrame(items_list)
                st.success(f"✅ AI izvukao {len(df_desc)} jela iz fajla.")

            if df_desc.empty or 'Product_Name' not in df_desc.columns:
                st.error("Nije moguće pronaći listu jela. Provjeri format fajla.")
            else:
                total_items = len(df_desc)
                if source_is_excel:
                    st.success(f"✅ Učitano {total_items} jela iz Excel fajla.")

                with st.expander("👀 POGLEDAJ UČITANU TABELU"):
                    st.dataframe(df_desc, height=400, use_container_width=True)

                st.markdown("---")
                col_d1, col_d2, col_d3 = st.columns(3)
                with col_d1:
                    desc_language = st.selectbox(
                        "Jezik opisa:",
                        ["Srpski", "Bosanski", "Hrvatski", "English"],
                        key="desc_lang"
                    )
                with col_d2:
                    desc_length = st.selectbox(
                        "Dužina opisa:",
                        ["Kratko (1 rečenica)", "Srednje (2-3 rečenice)", "Dugo (4-5 rečenica)"],
                        index=1,
                        key="desc_length"
                    )
                with col_d3:
                    overwrite_existing = st.checkbox(
                        "Prepiši postojeće opise",
                        value=False,
                        help="Ako je čekirano, AI će generisati opise i za jela koja već imaju opis.",
                        key="desc_overwrite"
                    )

                # Prikaz broja jela koja će biti obrađena
                if 'Description' in df_desc.columns and not overwrite_existing:
                    items_without_desc = df_desc[
                        df_desc['Description'].isna() | (df_desc['Description'].astype(str).str.strip() == '')
                    ]
                    to_process_count = len(items_without_desc)
                else:
                    to_process_count = total_items

                st.markdown(f"**Jela za obradu: `{to_process_count}` od ukupno `{total_items}`**")

                if not GEMINI_KEYS_LIST:
                    st.warning("⚠️ Gemini API ključ nije pronađen. Provjeri secrets ili config.json.")

                if st.button("🤖 GENERIŠI OPISE", type="primary", disabled=not GEMINI_KEYS_LIST or to_process_count == 0):
                    # Odredi koja jela treba obraditi
                    if 'Description' in df_desc.columns and not overwrite_existing:
                        mask = df_desc['Description'].isna() | (df_desc['Description'].astype(str).str.strip() == '')
                        names_to_process = df_desc.loc[mask, 'Product_Name'].tolist()
                    else:
                        names_to_process = df_desc['Product_Name'].tolist()

                    # Batch po 50 jela (da ne pređemo limit tokena)
                    BATCH_SIZE = 50
                    batches = [names_to_process[i:i+BATCH_SIZE] for i in range(0, len(names_to_process), BATCH_SIZE)]
                    
                    all_descriptions = {}
                    progress_bar = st.progress(0, text="AI piše opise...")
                    
                    try:
                        for batch_idx, batch in enumerate(batches):
                            result = generate_descriptions_batch(batch, GEMINI_KEYS_LIST, desc_language, desc_length)
                            batch_descs = result.get("descriptions", {})
                            all_descriptions.update(batch_descs)
                            progress = (batch_idx + 1) / len(batches)
                            progress_bar.progress(progress, text=f"Obrađeno {min((batch_idx+1)*BATCH_SIZE, len(names_to_process))} / {len(names_to_process)} jela...")

                        progress_bar.progress(1.0, text="✅ Gotovo!")

                        # Upiši opise nazad u DataFrame
                        if 'Description' not in df_desc.columns:
                            df_desc['Description'] = ''

                        updated_count = 0
                        for idx, row in df_desc.iterrows():
                            name = str(row['Product_Name']).strip()
                            if name in all_descriptions and all_descriptions[name]:
                                df_desc.at[idx, 'Description'] = all_descriptions[name]
                                updated_count += 1

                        st.session_state['desc_df_result'] = df_desc
                        st.session_state['desc_df_g'] = df_desc_g
                        st.session_state['desc_df_a'] = df_desc_a
                        st.session_state['desc_updated_count'] = updated_count

                    except Exception as e:
                        st.error(f"Greška: {e}")

                # Prikaz rezultata
                if 'desc_df_result' in st.session_state:
                    st.success(f"🎉 Generisano {st.session_state['desc_updated_count']} opisa!")

                    with st.expander("👀 POGLEDAJ REZULTAT SA OPISIMA", expanded=True):
                        # Prikaži samo relevantne kolone
                        preview_cols = ['Product_Name', 'Section', 'Price', 'Description']
                        available_cols = [c for c in preview_cols if c in st.session_state['desc_df_result'].columns]
                        st.dataframe(st.session_state['desc_df_result'][available_cols], height=500, use_container_width=True)

                    excel_out = build_excel(
                        st.session_state['desc_df_result'],
                        st.session_state['desc_df_g'],
                        st.session_state['desc_df_a']
                    )
                    st.download_button(
                        "📥 DOWNLOAD EXCEL SA OPISIMA",
                        excel_out,
                        "menu_sa_opisima.xlsx",
                        help="Preuzmi kompletan Excel fajl sa generisanim opisima jela"
                    )

        except Exception as e:
            st.error(f"Greška pri čitanju fajla: {e}")
