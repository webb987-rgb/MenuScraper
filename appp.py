import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid

# 1. Konfiguracija
st.set_page_config(page_title="Wolt Scraper", page_icon="🍔", layout="wide")

st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stExpander [data-testid="stExpanderDetails"] { padding-top: 0px !important; padding-left: 25px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Wolt Menu Scraper")
st.info("Popravljeno: Dubinsko skeniranje veza između jela i priloga za Glovo.")

# --- POMOĆNE FUNKCIJE ---
def get_slug(url):
    return url.strip().rstrip('/').split('/')[-1]

def sanitize_filename(filename):
    s = re.sub(r'[^\w\s-]', '', filename).strip().replace(' ', '_')
    return s if s else "bez_imena"

def fetch_data(slug):
    api_url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(api_url, headers=headers, timeout=15)
        return r.json() if r.status_code == 200 else None
    except: return None

def process_all_data(data):
    # 1. Kategorije
    item_to_section = {}
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Meni")
        for item_id in cat.get("item_ids", []):
            item_to_section[item_id] = cat_name

    # 2. MAPIRANJE GRUPA I ATRIBUTA (Pravimo "rečnik" veza)
    wolt_group_to_new_id = {}
    groups_raw, attributes_raw = [], []
    
    # Prvo izvučemo sve grupe koje postoje u restoranu
    for group in data.get("options", []):
        w_gid = group.get("id")
        new_gid = str(uuid.uuid4())
        wolt_group_to_new_id[w_gid] = new_gid # Pamtimo: Wolt ID -> Novi UUID
        
        g_name = group.get("name", "Prilog")
        current_group_attr_ids = []
        
        for val in group.get("values", []):
            new_aid = str(uuid.uuid4())
            current_group_attr_ids.append(new_aid)
            attributes_raw.append({
                "External_ID": new_aid,
                "Group_ID_Internal": new_gid,
                "Name": val.get("name", ""),
                "Price": val.get("price", 0) / 100,
                "Enabled": "YES",
                "Selected_by_Default": "NO"
            })
            
        groups_raw.append({
            "External_ID": new_gid,
            "Name": g_name,
            "Max": 10, "Min": 0,
            "Multiple_Selection": "NO",
            "Collapse_by_Default": "NO",
            "Attributes": ",".join(current_group_attr_ids)
        })

    df_groups = pd.DataFrame(groups_raw)
    df_attributes = pd.DataFrame(attributes_raw)

    # 3. OBRADA ARTIKALA (Spajanje)
    items_list, seen_ids = [], set()
    for item in data.get("items", []):
        w_iid = item.get("id")
        if not w_iid or w_iid in seen_ids: continue
        seen_ids.add(w_iid)
        
        new_iid = str(uuid.uuid4())
        
        # Skupljamo ID-jeve grupa za ovaj artikal
        connected_new_gids = []
        
        # Wolt krije opcije u 'options' ili 'selection_groups'
        wolt_opts = item.get("options", []) + item.get("selection_groups", [])
        
        for opt in wolt_opts:
            # Tražimo ID grupe (proveravamo tri različita ključa)
            target_w_gid = opt.get("option_id") or opt.get("id") or opt.get("selection_group_id")
            
            if target_w_gid in wolt_group_to_new_id:
                connected_new_gids.append(wolt_group_to_new_id[target_w_gid])

        # Slika
        img_url = ""
        main_img = item.get("main_image")
        if isinstance(main_img, dict) and main_img.get("id"):
            img_url = f"https://imageproxy.wolt.com/assets/{main_img.get('id')}?w=960"

        items_list.append({
            "External_ID": new_iid,
            "Product_Name": item.get("name", ""),
            "Collection": "MENI",
            "Section": item_to_section.get(w_iid, "Ostalo"),
            "Price": int((item.get("price") or item.get("base_price") or 0) / 100),
            "Image_1": img_url,
            "Description": item.get("description", "").replace("\n", " ").strip(),
            "Attribute_Groups": ",".join(list(set(connected_new_gids))), # set() uklanja duplikate
            "Is_Alcoholic": "NO", "Is_Tobacco": "NO", "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
        })
    
    df_products = pd.DataFrame(items_list).sort_values(by=["Section", "Product_Name"])
    return df_products, df_groups, df_attributes

# --- UI ---
link_input = st.text_input("Nalepi link restorana:")

if st.button("🚀 POKRENI"):
    if link_input:
        with st.spinner("Povezujem jela i priloge..."):
            slug = get_slug(link_input)
            raw = fetch_data(slug)
            if raw:
                p, g, a = process_all_data(raw)
                st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = p, g, a
                st.session_state['slug'] = slug
                st.success("Sistem je uspešno povezao sve relacije!")

if 'df_p' in st.session_state:
    df_p, df_g, df_a, slug = st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['slug']

    # DOWNLOAD
    c1, c2, _ = st.columns([0.15, 0.2, 0.65])
    with c1:
        df_excel = df_p.copy()
        df_excel['Image_1'] = "" 
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_excel.to_excel(writer, index=False, sheet_name='Products')
            df_g.to_excel(writer, index=False, sheet_name='Attribute Groups')
            df_a.drop(columns=['Group_ID_Internal']).to_excel(writer, index=False, sheet_name='Attributes')
        st.download_button("📊 EXCEL", output.getvalue(), f"Glovo_{slug}.xlsx")
    with c2:
        if st.button("🖼️ PRIPREMI SLIKE"):
            img_df = df_p[df_p['Image_1'] != ""]
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, "w") as zf:
                for _, row in img_df.iterrows():
                    try:
                        res = requests.get(row['Image_1'], timeout=10)
                        zf.writestr(f"{sanitize_filename(row['Product_Name'])}.jpg", res.content)
                    except: continue
            st.download_button("🔥 SKINI ZIP", zip_io.getvalue(), f"Slike_{slug}.zip")

    st.markdown("---")
    tab_raw, tab_tree = st.tabs(["📊 TABELE", "🔍 HIJERARHIJA"])

    with tab_raw:
        st.dataframe(df_p[["Product_Name", "Section", "Price", "Attribute_Groups"]], hide_index=True)

    with tab_tree:
        for section in df_p['Section'].unique():
            st.markdown(f"**{section}**")
            for _, prod in df_p[df_p['Section'] == section].iterrows():
                with st.expander(f"{prod['Product_Name']} ({prod['Price']} RSD)"):
                    g_ids = [gid for gid in str(prod['Attribute_Groups']).split(",") if gid]
                    if g_ids:
                        for gid in g_ids:
                            g_info = df_g[df_g['External_ID'] == gid]
                            if not g_info.empty:
                                with st.expander(f"└ {g_info.iloc[0]['Name']}"):
                                    rel_attrs = df_a[df_a['Group_ID_Internal'] == gid]
                                    for _, attr in rel_attrs.iterrows():
                                        st.write(f"• {attr['Name']} ({attr['Price']} RSD)")
                    else:
                        st.write("Nema priloga.")
