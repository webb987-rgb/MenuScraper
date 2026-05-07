import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid

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

# --- HELPER FUNCTIONS ---
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
            
            # PRICE: Always base_price
            puna_cena = int((item.get("base_price") or item.get("price") or 0) / 100)

            # IMAGES: Advanced detection
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

            # Groups
            gids = [wolt_group_to_new_id[o.get("option_id")] for o in item.get("options", []) if o.get("option_id") in wolt_group_to_new_id]

            items_list.append({
                "External_ID": new_iid, "Product_Name": item.get("name", ""), "Collection": "MENU",
                "Section": cat_name, "Price": puna_cena, "Image_1": img_url,
                "Description": item.get("description", "").replace("\n", " ").strip(),
                "Attribute_Groups": ",".join(gids), "Is_Alcoholic": "NO", "Is_Tobacco": "NO", 
                "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
            })
        
    return pd.DataFrame(items_list), pd.DataFrame(groups_raw), pd.DataFrame(attrs_raw), ordered_sections

# --- UI LOGICA ---
st.info("💡 **Instructions:** Use a clean restaurant link without extra tracking numbers at the end.")
link_input = st.text_input("Paste restaurant link:", placeholder="https://wolt.com/en/srb/nis/restaurant/beer-point-nis")
st.caption("Example: `https://wolt.com/en/srb/nis/restaurant/beer-point-nis`")

if st.button("🚀 RUN"):
    if link_input:
        slug = link_input.strip().rstrip('/').split('/')[-1]
        raw = fetch_data(slug)
        if raw:
            p, g, a, o_s = process_all_data(raw)
            st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = p, g, a
            st.session_state['ordered_sections'] = o_s
            st.session_state['slug'] = slug
            st.success("Success! Everything loaded according to Wolt's original order.")
        else:
            st.error("Error loading data. Please check if the link is correct and clean.")

if 'df_p' in st.session_state:
    df_p = st.session_state['df_p']
    df_g = st.session_state['df_g']
    df_a = st.session_state['df_a']
    slug = st.session_state['slug']
    ordered_sections = st.session_state['ordered_sections']

    st.markdown("### 📥 Download")
    col_ex, col_zip, _ = st.columns([1, 1.2, 4])
    
    with col_ex:
        # Excel Preparation
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
            
        st.download_button("📊 EXCEL", out.getvalue(), f"Wolt_{slug}.xlsx")
        
    with col_zip:
        img_df = df_p[df_p['Image_1'] != ""]
        if not img_df.empty:
            # IZMENA: Novo ime dugmeta i info spinner
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
                st.download_button("🔥 SAVE ZIP FILE", st.session_state['zip_ready'], f"Images_{slug}.zip")

    st.markdown("---")
    t_menu, t_raw = st.tabs(["🌳 MENU PREVIEW", "📊 RAW DATA"])
    
    with t_menu:
        for s in ordered_sections:
            prods_in_section = df_p[df_p['Section'] == s]
            if not prods_in_section.empty:
                st.markdown(f"**{s}**")
                for _, p in prods_in_section.iterrows():
                    with st.expander(f"{p['Product_Name']} — {p['Price']} RSD"):
                        if p['Description']: st.write(f"_{p['Description']}_")
                        
                        # Displaying add-ons (options)
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
                                    
    with t_raw:
        st.dataframe(
            df_p[["Product_Name", "Section", "Price", "Image_1", "External_ID"]], 
            hide_index=True,
            column_config={"Image_1": st.column_config.LinkColumn("Image", display_text="View 🔗")}
        )
