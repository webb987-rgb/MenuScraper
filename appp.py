import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid

# 1. Konfiguracija stranice
st.set_page_config(page_title="Wolt Scraper", page_icon="🍔", layout="wide")

st.title("🍔 Wolt Menu Scraper")
st.markdown("Relaciona logika je usklađena sa tvojim Glovo uputstvima (UUID + čisti zarez).")

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

    # 2. GENERISANJE UUID-jeva I RELACIJA
    wolt_group_to_new_id = {}
    
    groups_raw = []
    attributes_raw = []
    
    for group in data.get("options", []):
        w_gid = group.get("id")
        new_gid = str(uuid.uuid4()) # Novi ID za grupu (External ID u tvojoj 1. slici)
        wolt_group_to_new_id[w_gid] = new_gid
        
        g_name = group.get("name", "Prilog")
        
        current_group_attr_ids = []
        for val in group.get("values", []):
            new_aid = str(uuid.uuid4()) # Novi ID za atribut (External ID u tvojoj 2. slici)
            current_group_attr_ids.append(new_aid)
            
            attributes_raw.append({
                "External_ID": new_aid,
                "Name": val.get("name", ""),
                "Price": val.get("price", 0) / 100,
                "Enabled": "YES",
                "Selected_by_Default": "NO"
            })
            
        # Tabela: Attribute Groups (Povezuje na atribute preko External_ID-jeva bez razmaka)
        groups_raw.append({
            "External_ID": new_gid,
            "Max": 10, "Min": 0,
            "Name": g_name,
            "Multiple_Selection": "NO",
            "Collapse_by_Default": "NO",
            "Attributes": ",".join(current_group_attr_ids) # Bitno: Nema razmaka posle zareza
        })

    df_groups_final = pd.DataFrame(groups_raw)
    df_attributes_export = pd.DataFrame(attributes_raw)

    # 3. Artikli
    items_list, seen_ids = [], set()
    for item in data.get("items", []):
        w_iid = item.get("id")
        if not w_iid or w_iid in seen_ids: continue
        seen_ids.add(w_iid)
        
        new_iid = str(uuid.uuid4())

        # Slika (za ZIP download)
        image_url = ""
        main_img = item.get("main_image")
        if isinstance(main_img, dict) and main_img.get("id"):
            image_url = f"https://imageproxy.wolt.com/assets/{main_img.get('id')}?w=960"
        elif item.get("images") and len(item.get("images")) > 0:
            image_url = item.get("images")[0].get("url", "")

        # Povezivanje na grupe (Attribute_Groups u tvojoj 1. slici)
        item_opts = item.get("options", [])
        connected_gids = []
        for opt in item_opts:
            w_target_id = opt.get("option_id")
            if w_target_id in wolt_group_to_new_id:
                connected_gids.append(wolt_group_to_new_id[w_target_id])

        items_list.append({
            "External_ID": new_iid,
            "Product_Name": item.get("name", ""),
            "SuperCollection": "", "SuperCollection_Order": "", "SuperCollection_Image": "",
            "Collection": "MENI", "Collection_Image": "", "Collection_Order": 1,
            "Section": item_to_section.get(w_iid, "Ostalo"), "Section_Order": 1,
            "Price": int((item.get("price") or item.get("base_price") or 0) / 100),
            "Image_1": image_url,
            "Image_Source_1": "", "Image_2": "", "Image_Source_2": "", "Image_3": "", "Image_Source_3": "",
            "Image_4": "", "Image_Source_4": "", "Image_5": "", "Image_Source_5": "",
            "Image_6": "", "Image_Source_6": "", "Image_7": "", "Image_Source_7": "",
            "Image_8": "", "Image_Source_8": "", "Image_9": "", "Image_Source_9": "",
            "Image_10": "", "Image_Source_10": "",
            "Description": item.get("description", "").replace("\n", " ").strip(),
            "Is_Alcoholic": "NO", "Is_Tobacco": "NO",
            "Attribute_Groups": ",".join(connected_gids), # Bez razmaka posle zareza
            "Dietary": ""
        })
    
    df_products = pd.DataFrame(items_list).sort_values(by=["Section", "Product_Name"])
    return df_products, df_groups_final, df_attributes_export

# --- UI ---
link_input = st.text_input("Nalepi link restorana:")

if st.button("🚀 POKRENI"):
    if link_input:
        with st.spinner("Sakupljam podatke..."):
            slug = get_slug(link_input)
            raw = fetch_data(slug)
            if raw:
                st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = process_all_data(raw)
                st.session_state['slug'] = slug
                st.success("Sve je formatirano prema tvojim instrukcijama!")

if 'df_p' in st.session_state:
    df_p, df_g, df_a, slug = st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['slug']

    st.markdown("### 📥 Download zona")
    c1, c2, _ = st.columns([1, 1.2, 4])
    with c1:
        # Čišćenje za Excel export
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
    tab_raw, tab_tree = st.tabs(["📊 TABELE", "🔍 HIJERARHIJA"])

    with tab_raw:
        # Prikaz samo najbitnijih kolona da bi ostalo "sitno" i pregledno
        ui_cols = ["Product_Name", "Section", "Price", "Attribute_Groups"]
        st.write("**Products**")
        st.dataframe(df_p[ui_cols], hide_index=True)
        st.write("**Attribute Groups**")
        st.dataframe(df_g[["Name", "Attributes", "External_ID"]], hide_index=True)

    with tab_tree:
        for section in df_p['Section'].unique():
            st.markdown(f"**{section}**")
            for _, prod in df_p[df_p['Section'] == section].iterrows():
                with st.expander(f"{prod['Product_Name']} ({prod['Price']} RSD)"):
                    g_ids = [gid.strip() for gid in str(prod['Attribute_Groups']).split(",") if gid.strip()]
                    for gid in g_ids:
                        g_info = df_g[df_g['External_ID'] == gid]
                        if not g_info.empty:
                            with st.expander(f"└ {g_info.iloc[0]['Name']}"):
                                a_ids = [aid.strip() for aid in str(g_info.iloc[0]['Attributes']).split(",") if aid.strip()]
                                for aid in a_ids:
                                    a_info = df_a[df_a['External_ID'] == aid]
                                    if not a_info.empty:
                                        st.write(f"• {a_info.iloc[0]['Name']} (+{a_info.iloc[0]['Price']} RSD)")
