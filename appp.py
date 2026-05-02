import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid

# 1. Konfiguracija
st.set_page_config(page_title="Wolt Scraper", page_icon="🍔", layout="wide")

st.title("🍔 Wolt Menu Scraper")
st.markdown("Popravljene relacije: Sada Glovo mora da 'vidi' vezu između jela i priloga.")

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
    # 1. Mapiranje kategorija
    item_to_section = {}
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Meni")
        for item_id in cat.get("item_ids", []):
            item_to_section[item_id] = cat_name

    # 2. GENERISANJE UUID-jeva
    wolt_group_to_uuid = {}
    
    groups_raw, attributes_raw = [], []
    
    # Prvo obrađujemo grupe i njihove atribute
    for group in data.get("options", []):
        w_gid = group.get("id")
        new_gid = str(uuid.uuid4())
        wolt_group_to_uuid[w_gid] = new_gid
        
        g_name = group.get("name", "Prilog")
        
        current_group_new_aids = []
        for val in group.get("values", []):
            new_aid = str(uuid.uuid4())
            current_group_new_aids.append(new_aid)
            
            attributes_raw.append({
                "External_ID": new_aid,
                "Name": val.get("name", ""),
                "Price": val.get("price", 0) / 100,
                "Enabled": "YES",
                "Selected_by_Default": "NO"
            })
            
        # FIX: Koristimo samo zarez BEZ RAZMAKA (",") za listu atributa
        groups_raw.append({
            "External_ID": new_gid,
            "Name": g_name,
            "Max": 10, "Min": 0,
            "Multiple_Selection": "NO",
            "Collapse_by_Default": "NO",
            "Attributes": ",".join(current_group_new_aids) 
        })

    df_groups_final = pd.DataFrame(groups_raw)
    df_attributes_export = pd.DataFrame(attributes_raw)

    # 3. Obrada artikala
    items_list, seen_ids = [], set()
    for item in data.get("items", []):
        w_iid = item.get("id")
        if not w_iid or w_iid in seen_ids: continue
        seen_ids.add(w_iid)
        
        new_iid = str(uuid.uuid4())

        image_url = ""
        main_img = item.get("main_image")
        if isinstance(main_img, dict) and main_img.get("id"):
            image_url = f"https://imageproxy.wolt.com/assets/{main_img.get('id')}?w=960"
        elif item.get("images") and len(item.get("images")) > 0:
            image_url = item.get("images")[0].get("url", "")

        # Povezivanje na NOVE ID-jeve grupa
        item_opts = item.get("options", [])
        connected_new_gids = []
        for opt_entry in item_opts:
            w_target_id = opt_entry.get("option_id")
            if w_target_id in wolt_group_to_uuid:
                connected_new_gids.append(wolt_group_to_uuid[w_target_id])

        # FIX: Koristimo samo zarez BEZ RAZMAKA (",") za listu grupa
        items_list.append({
            "External_ID": new_iid,
            "Product_Name": item.get("name", ""),
            "Collection": "MENI",
            "Section": item_to_section.get(w_iid, "Ostalo"),
            "Price": int((item.get("price") or item.get("base_price") or 0) / 100),
            "Image_1": image_url,
            "Description": item.get("description", "").replace("\n", " ").strip(),
            "Attribute_Groups": ",".join(connected_new_gids),
            "Is_Alcoholic": "NO", "Is_Tobacco": "NO", "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
        })
    
    df_products = pd.DataFrame(items_list).sort_values(by=["Section", "Product_Name"])
    return df_products, df_groups_final, df_attributes_export

# --- UI ---
link_input = st.text_input("Nalepi Wolt link:")

if st.button("🚀 POKRENI"):
    if link_input:
        with st.spinner("Generišem čiste relacije..."):
            slug = get_slug(link_input)
            raw = fetch_data(slug)
            if raw:
                st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = process_all_data(raw)
                st.session_state['slug'] = slug
                st.success("Spremno! Relacije su sada očišćene od razmaka.")

if 'df_p' in st.session_state:
    df_p, df_g, df_a, slug = st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['slug']

    # --- DOWNLOAD ---
    st.markdown("### 📥 Download")
    c1, c2, _ = st.columns([1, 1.2, 4])
    with c1:
        df_excel = df_p.copy()
        df_excel['Image_1'] = ""
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_excel.to_excel(writer, index=False, sheet_name='Products')
            df_g.to_excel(writer, index=False, sheet_name='Attribute Groups')
            df_a.to_excel(writer, index=False, sheet_name='Attributes')
        st.download_button("📊 GLOVO EXCEL", output.getvalue(), f"Glovo_Import_{slug}.xlsx")
    
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
    # TABOVI
    t1, t2 = st.tabs(["📊 TABELE", "🔍 HIJERARHIJA"])

    with t1:
        st.write("**Products**")
        st.dataframe(df_p[["Product_Name", "Section", "Price", "Attribute_Groups"]], hide_index=True)
        st.write("**Attribute Groups**")
        st.dataframe(df_g, hide_index=True)

    with t2:
        # Prikaz stabla (kao provera veze)
        for section in df_p['Section'].unique():
            st.markdown(f"**{section}**")
            for _, prod in df_p[df_p['Section'] == section].iterrows():
                with st.expander(f"{prod['Product_Name']} ({prod['Price']} RSD)"):
                    # Ovde proveravamo da li skripta unutar sebe vidi vezu
                    g_ids = [gid for gid in str(prod['Attribute_Groups']).split(",") if gid]
                    for gid in g_ids:
                        g_info = df_g[df_g['External_ID'] == gid]
                        if not g_info.empty:
                            with st.expander(f"└ {g_info.iloc[0]['Name']}"):
                                a_ids = [aid for aid in str(g_info.iloc[0]['Attributes']).split(",") if aid]
                                for aid in a_ids:
                                    a_info = df_a[df_a['External_ID'] == aid]
                                    if not a_info.empty:
                                        st.write(f"• {a_info.iloc[0]['Name']}")
