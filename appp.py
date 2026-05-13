import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid
import base64
import json

# 1. Page Configuration
st.set_page_config(page_title="Wolt Scraper - PRO", page_icon="🍔", layout="wide")

# CSS for compact elements and UI fixing
st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stExpander [data-testid="stExpanderDetails"] { padding-top: 0px !important; padding-left: 25px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    [data-testid="column"] { width: fit-content !important; min-width: fit-content !important; flex: none !important; padding-right: 15px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Wolt Menu Scraper")

# --- HELPER FUNCTIONS (original, unchanged) ---
def fetch_data(slug):
    api_url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(api_url, headers=headers, timeout=15)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def process_all_data(data):
    # 1. Mapping categories WITH ORDER RETENTION
    ordered_sections = []
    item_to_section = {}
    
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Menu")
        ordered_sections.append(cat_name)
        for item_id in cat.get("item_ids", []):
            item_to_section[item_id] = cat_name

    # 2. Attributes and Groups (UUID logic)
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

    # 3. Products - DISH ORDER RETENTION
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


# --- PHOTO MENU: AI VISION FUNCTIONS ---

def image_to_base64(uploaded_file):
    """Convert uploaded file to base64 string."""
    bytes_data = uploaded_file.read()
    uploaded_file.seek(0)  # Reset pointer after reading
    return base64.standard_b64encode(bytes_data).decode("utf-8")

def extract_menu_from_images(uploaded_files, api_key):
    """
    Send all uploaded menu images to Claude Vision API and extract structured menu data.
    Returns a list of items with section, name, price, description.
    """
    
    # Build content blocks - one per image
    content_blocks = []
    
    for uf in uploaded_files:
        b64 = image_to_base64(uf)
        # Detect media type
        fname = uf.name.lower()
        if fname.endswith(".png"):
            media_type = "image/png"
        elif fname.endswith(".webp"):
            media_type = "image/webp"
        elif fname.endswith(".gif"):
            media_type = "image/gif"
        else:
            media_type = "image/jpeg"
        
        content_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64
            }
        })
    
    content_blocks.append({
        "type": "text",
        "text": """You are a menu data extraction expert. Carefully analyze ALL the menu images provided and extract every single dish/item you can find.

Return ONLY a valid JSON object, no markdown, no explanation, no backticks. The JSON must have this exact structure:

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
- Extract ALL items visible across all images
- Prices must be integers in RSD (strip 'RSD', 'din', 'рсд', commas, dots used as thousands separators)
- If price is not visible or unclear, use 0
- If no clear sections exist, put everything under "Ostalo"
- Preserve the original section names from the menu (in original language - Serbian, English, etc.)
- Do not skip any item even if description is missing
- Combine items from all images into one coherent menu structure, merging sections with the same name"""
    })
    
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }
    
    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": content_blocks
            }
        ]
    }
    
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=120
    )
    
    if response.status_code != 200:
        raise Exception(f"API error {response.status_code}: {response.text}")
    
    data = response.json()
    raw_text = data["content"][0]["text"].strip()
    
    # Clean up in case model added backticks
    raw_text = re.sub(r'^```json\s*', '', raw_text)
    raw_text = re.sub(r'^```\s*', '', raw_text)
    raw_text = re.sub(r'\s*```$', '', raw_text)
    
    return json.loads(raw_text)


def build_dataframes_from_photo(menu_data, restaurant_name):
    """Convert extracted menu JSON into the same DataFrames format as Wolt scraper."""
    items_list = []
    ordered_sections = []
    
    for section in menu_data.get("sections", []):
        sec_name = section.get("name", "Ostalo").strip()
        if sec_name not in ordered_sections:
            ordered_sections.append(sec_name)
        
        for item in section.get("items", []):
            new_iid = str(uuid.uuid4())
            price_raw = item.get("price", 0)
            try:
                price_int = int(price_raw)
            except:
                price_int = 0
            
            items_list.append({
                "External_ID": new_iid,
                "Product_Name": str(item.get("name", "")).strip(),
                "Collection": "MENU",
                "Section": sec_name,
                "Price": price_int,
                "Image_1": "",
                "Description": str(item.get("description", "")).strip(),
                "Attribute_Groups": "",
                "Is_Alcoholic": "NO",
                "Is_Tobacco": "NO",
                "SuperCollection": "",
                "Section_Order": 1,
                "Collection_Order": 1
            })
    
    df_p = pd.DataFrame(items_list)
    df_g = pd.DataFrame(columns=["External_ID", "Max", "Min", "Name", "Multiple_Selection", "Collapse_by_Default", "Attributes"])
    df_a = pd.DataFrame(columns=["External_ID", "Group_ID_Internal", "Name", "Price", "Enabled", "Selected_by_Default"])
    
    return df_p, df_g, df_a, ordered_sections


def build_excel(df_p, df_g, df_a):
    """Build Excel file in the same format as Wolt scraper."""
    df_excel = df_p.copy()
    df_excel['Image_1'] = ""
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
    """Render the tree-style menu preview (same as Wolt tab)."""
    for s in ordered_sections:
        prods_in_section = df_p[df_p['Section'] == s]
        if not prods_in_section.empty:
            st.markdown(f"**{s}**")
            for _, p in prods_in_section.iterrows():
                label = f"{p['Product_Name']} — {p['Price']} RSD" if p['Price'] > 0 else f"{p['Product_Name']} — cena nije dostupna"
                with st.expander(label):
                    if p['Description']:
                        st.write(f"_{p['Description']}_")
                    
                    g_ids = [gid for gid in str(p['Attribute_Groups']).split(",") if gid]
                    for gid in g_ids:
                        if not df_g.empty:
                            g_i = df_g[df_g['External_ID'] == gid]
                            if not g_i.empty:
                                with st.expander(f"└ {g_i.iloc[0]['Name']}"):
                                    if not df_a.empty:
                                        attrs = df_a[df_a['Group_ID_Internal'] == gid]
                                        for _, a in attrs.iterrows():
                                            st.write(f"• {a['Name']} ({a['Price']} RSD)")


# ============================================================
# MAIN UI - TWO TABS
# ============================================================

tab_wolt, tab_photo = st.tabs(["🌐 Wolt Scraper", "📷 Photo Menu"])


# ============================================================
# TAB 1: ORIGINAL WOLT SCRAPER (unchanged)
# ============================================================
with tab_wolt:
    st.info("💡 **Instructions:** Možete uneti običan link restorana ili link specifične kolekcije.")
    link_input = st.text_input("Paste restaurant link:", placeholder="https://wolt.com/en/srb/belgrade/venue/breadventure/collections/popular")
    st.caption("Primeri: `.../restaurant/ime` ili `.../venue/ime/collections/...` ")

    if st.button("🚀 RUN"):
        if link_input:
            match = re.search(r'/(?:restaurant|venue)/([^/]+)', link_input.strip())
            
            if match:
                slug = match.group(1)
                raw = fetch_data(slug)
                if raw:
                    p, g, a, o_s = process_all_data(raw)
                    st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = p, g, a
                    st.session_state['ordered_sections'] = o_s
                    st.session_state['slug'] = slug
                    st.success(f"Uspešno učitano: **{slug}**")
                else:
                    st.error("Greška pri učitavanju podataka. Proverite link.")
            else:
                st.error("Neispravan format linka. Link mora sadržati '/restaurant/' ili '/venue/'.")

    if 'df_p' in st.session_state:
        df_p = st.session_state['df_p']
        df_g = st.session_state['df_g']
        df_a = st.session_state['df_a']
        slug = st.session_state['slug']
        ordered_sections = st.session_state['ordered_sections']

        st.markdown("### 📥 Download")
        col_ex, col_zip, _ = st.columns([1, 1.2, 4])
        
        with col_ex:
            excel_bytes = build_excel(df_p, df_g, df_a)
            st.download_button("📊 EXCEL", excel_bytes, f"menu_{slug}.xlsx")
            
        with col_zip:
            img_df = df_p[df_p['Image_1'] != ""]
            if not img_df.empty:
                if st.button("🖼️ DOWNLOAD PICTURES"):
                    with st.spinner("Downloading pictures, please wait..."):
                        z_io = io.BytesIO()
                        with zipfile.ZipFile(z_io, "w") as zf:
                            for _, r in img_df.iterrows():
                                try:
                                    clean_name = re.sub(r'[^\w\s-]', '', r['Product_Name']).strip().replace(' ', '_')
                                    res = requests.get(r['Image_1'], timeout=10)
                                    zf.writestr(f"{clean_name}.jpg", res.content)
                                except: continue
                        st.session_state['zip_ready'] = z_io.getvalue()
                
                if 'zip_ready' in st.session_state:
                    st.download_button("🔥 SAVE ZIP FILE", st.session_state['zip_ready'], f"menu_images_{slug}.zip")

        st.markdown("---")
        t_menu, t_raw = st.tabs(["🌳 MENU PREVIEW", "📊 RAW DATA"])
        
        with t_menu:
            render_menu_preview(df_p, df_g, df_a, ordered_sections)
                    
        with t_raw:
            st.dataframe(
                df_p[["Product_Name", "Section", "Price", "Image_1", "External_ID"]], 
                hide_index=True,
                column_config={"Image_1": st.column_config.LinkColumn("Image", display_text="View 🔗")}
            )


# ============================================================
# TAB 2: PHOTO MENU - AI Vision extraction
# ============================================================
with tab_photo:
    st.markdown("### 📷 Ucitaj slike jelovnika")
    st.info("💡 Slikaj stranice jelovnika i uploaduj ih ovde. AI će automatski pročitati sva jela, sekcije i cene i pretvoriti ih u Excel.")

    # API Key input
    api_key = st.text_input(
        "🔑 Anthropic API Key:",
        type="password",
        placeholder="sk-ant-...",
        help="Potreban je API key za AI čitanje slika. Možeš ga dobiti na console.anthropic.com"
    )

    # Restaurant name for filename
    restaurant_name_photo = st.text_input(
        "Naziv restorana (za ime fajla):",
        placeholder="npr. La Piazza",
        help="Koristi se samo za naziv Excel fajla koji se preuzima."
    )

    # Image uploader - multiple files
    uploaded_images = st.file_uploader(
        "Uploaduj slike jelovnika:",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        help="Možeš odabrati više slika odjednom. Podržani formati: JPG, PNG, WEBP"
    )

    if uploaded_images:
        st.caption(f"✅ {len(uploaded_images)} slika učitano: {', '.join([f.name for f in uploaded_images])}")
        
        # Show thumbnails in a row
        cols = st.columns(min(len(uploaded_images), 5))
        for i, uf in enumerate(uploaded_images):
            with cols[i % 5]:
                st.image(uf, use_container_width=True, caption=uf.name)

    st.markdown("---")

    if st.button("🤖 ANALIZIRAJ JELOVNIK", type="primary"):
        # Validations
        if not api_key:
            st.error("⚠️ Unesite Anthropic API key.")
        elif not uploaded_images:
            st.error("⚠️ Uploadujte bar jednu sliku jelovnika.")
        else:
            slug_photo = re.sub(r'[^\w]', '_', restaurant_name_photo.strip().lower()) if restaurant_name_photo.strip() else "restaurant"
            
            with st.spinner(f"🔍 AI analizira {len(uploaded_images)} slika... Ovo može potrajati 15-30 sekundi."):
                try:
                    menu_data = extract_menu_from_images(uploaded_images, api_key)
                    
                    df_p_photo, df_g_photo, df_a_photo, ordered_sections_photo = build_dataframes_from_photo(menu_data, slug_photo)
                    
                    # Store in session state (separate namespace from Wolt)
                    st.session_state['photo_df_p'] = df_p_photo
                    st.session_state['photo_df_g'] = df_g_photo
                    st.session_state['photo_df_a'] = df_a_photo
                    st.session_state['photo_ordered_sections'] = ordered_sections_photo
                    st.session_state['photo_slug'] = slug_photo
                    
                    total_items = len(df_p_photo)
                    total_sections = len(ordered_sections_photo)
                    st.success(f"✅ Uspešno prepoznato **{total_items} jela** u **{total_sections} sekcija**!")
                    
                except json.JSONDecodeError as e:
                    st.error(f"⚠️ AI nije vratio ispravan format podataka. Pokušajte ponovo. Detalji: {e}")
                except Exception as e:
                    err_msg = str(e)
                    if "401" in err_msg or "authentication" in err_msg.lower():
                        st.error("⚠️ Neispravan API key. Proverite key na console.anthropic.com")
                    elif "413" in err_msg or "too large" in err_msg.lower():
                        st.error("⚠️ Slike su prevelike. Pokušajte sa manjim brojem slika ili smanjite rezoluciju.")
                    else:
                        st.error(f"⚠️ Greška: {err_msg}")

    # Results section (only shown if analysis was run)
    if 'photo_df_p' in st.session_state:
        df_p_ph = st.session_state['photo_df_p']
        df_g_ph = st.session_state['photo_df_g']
        df_a_ph = st.session_state['photo_df_a']
        ordered_sections_ph = st.session_state['photo_ordered_sections']
        slug_ph = st.session_state['photo_slug']

        st.markdown("### 📥 Download")
        col_dl, _ = st.columns([1, 5])
        with col_dl:
            excel_bytes_photo = build_excel(df_p_ph, df_g_ph, df_a_ph)
            st.download_button(
                "📊 EXCEL",
                excel_bytes_photo,
                f"menu_{slug_ph}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        st.markdown("---")
        t_menu_ph, t_raw_ph = st.tabs(["🌳 MENU PREVIEW", "📊 RAW DATA"])

        with t_menu_ph:
            render_menu_preview(df_p_ph, df_g_ph, df_a_ph, ordered_sections_ph)

        with t_raw_ph:
            st.dataframe(
                df_p_ph[["Product_Name", "Section", "Price", "Description", "External_ID"]],
                hide_index=True
            )
