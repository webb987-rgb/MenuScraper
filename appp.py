import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid

# 1. Konfiguracija stranice
st.set_page_config(page_title="Wolt Scraper", page_icon="🍔", layout="wide")

# CSS za zbijanje elemenata i lepši prikaz
st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stExpander [data-testid="stExpanderDetails"] { padding-top: 0px !important; padding-left: 25px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    [data-testid="column"] { width: fit-content !important; min-width: fit-content !important; flex: none !important; padding-right: 15px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Wolt Menu Scraper")
st.markdown("v5.")

# --- POMOĆNE FUNKCIJE ---
def fetch_data(slug):
    api_url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(api_url, headers=headers, timeout=15)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def process_all_data(data):
    # 1. Kategorije
    item_to_section = {}
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Meni")
        for item_id in cat.get("item_ids", []):
            item_to_section[item_id] = cat_name

    # 2. Atributi i Grupe (UUID logika)
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
            "Name": group.get("name", "Prilog"),
            "Multiple_Selection": "NO",
            "Collapse_by_Default": "NO",
            "Attributes": ",".join(a_ids)
        })

    # 3. Proizvodi
    items_list = []
    seen_ids = set()
    for item in data.get("items", []):
        w_id = item.get("id")
        if not w_id or w_id in seen_ids: continue
        seen_ids.add(w_id)
        
        new_iid = str(uuid.uuid4())
        img = item.get("main_image", {}).get("id", "")
        img_url = f"https://imageproxy.wolt.com/assets/{img}?w=960" if img else ""
        
        # Povezivanje grupa
        gids = [wolt_group_to_new_id[o.get("option_id")] for o in item.get("options", []) if o.get("option_id") in wolt_group_to_new_id]

        items_list.append({
            "External_ID": new_iid,
            "Product_Name": item.get("name", ""),
            "Collection": "MENI",
            "Section": item_to_section.get(w_id, "Ostalo"),
            "Price": int((item.get("price") or item.get("base_price") or 0) / 100),
            "Image_1": img_url,
            "Description": item.get("description", "").replace("\n", " ").strip(),
            "Attribute_Groups": ",".join(gids),
            "Is_Alcoholic": "NO", "Is_Tobacco": "NO", "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
        })
        
    return pd.DataFrame(items_list), pd.DataFrame(groups_raw), pd.DataFrame(attrs_raw)

# --- UI LOGIKA ---
link_input = st.text_input("Nalepi Wolt link restorana:")

if st.button("🚀 POKRENI"):
    if link_input:
        slug = link_input.strip().rstrip('/').split('/')[-1]
        raw = fetch_data(slug)
        if raw:
            st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = process_all_data(raw)
            st.session_state['slug'] = slug
            st.success("Podaci uspešno učitani!")

if 'df_p' in st.session_state:
    df_p, df_g, df_a, slug = st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['slug']

    st.markdown("### 📥 Download")
    col_ex, col_zip, _ = st.columns([1, 1, 4])
    
    with col_ex:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w:
            df_p.assign(Image_1="").to_excel(w, index=False, sheet_name='Products')
            df_g.to_excel(w, index=False, sheet_name='Attribute Groups')
            df_a.drop(columns=['Group_ID_Internal']).to_excel(w, index=False, sheet_name='Attributes')
        st.download_button("📊 EXCEL", out.getvalue(), f"Glovo_{slug}.xlsx")
        
    with col_zip:
        if st.button("🖼️ ZIP SLIKE"):
            z_io = io.BytesIO()
            with zipfile.ZipFile(z_io, "w") as zf:
                for _, r in df_p[df_p['Image_1'] != ""].iterrows():
                    try:
                        name = re.sub(r'[^\w\s-]', '', r['Product_Name']).strip().replace(' ', '_')
                        zf.writestr(f"{name}.jpg", requests.get(r['Image_1']).content)
                    except: continue
            st.download_button("🔥 SKINI ZIP", z_io.getvalue(), f"Slike_{slug}.zip")

    st.markdown("---")
    t_menu, t_raw = st.tabs(["🌳 MENU", "📊 SIROVI PODACI"])
    
    with t_menu:
        for s in df_p['Section'].unique():
            st.markdown(f"**{s}**")
            for _, p in df_p[df_p['Section'] == s].iterrows():
                with st.expander(f"{p['Product_Name']} — {p['Price']} RSD"):
                    if p['Description']: st.write(f"_{p['Description']}_")
                    g_ids = [g for g in p['Attribute_Groups'].split(",") if g]
                    for gid in g_ids:
                        g_info = df_g[df_g['External_ID'] == gid]
                        if not g_info.empty:
                            with st.expander(f"└ {g_info.iloc[0]['Name']}"):
                                for _, a in df_a[df_a['Group_ID_Internal'] == gid].iterrows():
                                    st.write(f"• {a['Name']} ({a['Price']} RSD)")
                                    
    with t_raw:
        st.dataframe(df_p[["Product_Name", "Section", "Price", "External_ID"]], hide_index=True)
