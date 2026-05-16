import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re

# 1. Konfiguracija stranice
st.set_page_config(page_title="Wolt Scraper", page_icon="🍔", layout="wide")

st.title("🍔 Wolt Menu Scraper")
st.markdown("Sajt prikazuje samo bitne informacije, dok Excel sadrži sve kolone za Glovo.")

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
    except:
        return None

def process_all_data(data):
    # 1. Mapiranje kategorija
    item_to_section = {}
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Meni")
        for item_id in cat.get("item_ids", []):
            item_to_section[item_id] = cat_name

    # 2. Generisanje tabela atributa
    groups_raw, attributes_raw = [], []
    for group in data.get("options", []):
        g_id, g_name = group.get("id"), group.get("name", "Prilog")
        groups_raw.append({
            "External_ID": g_id, "Name": g_name, "Max": 10, "Min": 0,
            "Multiple_Selection": "NO", "Collapse_by_Default": "NO"
        })
        for val in group.get("values", []):
            attributes_raw.append({
                "External_ID": val.get("id"), "Attribute_Group_ID": g_id,
                "Name": val.get("name", ""), "Price": val.get("price", 0) / 100,
                "Enabled": "YES", "Selected_by_Default": "NO"
            })

    df_groups_base = pd.DataFrame(groups_raw).drop_duplicates()
    df_attributes_final = pd.DataFrame(attributes_raw)
    attr_mapping = df_attributes_final.groupby("Attribute_Group_ID")["External_ID"].apply(lambda x: ", ".join(x)).reset_index()
    df_groups_final = pd.merge(df_groups_base, attr_mapping, left_on="External_ID", right_on="Attribute_Group_ID", how="left")
    df_groups_final = df_groups_final.drop(columns=["Attribute_Group_ID"]).rename(columns={"External_ID_y": "Attributes", "External_ID_x": "External_ID"})
    df_attributes_export = df_attributes_final.drop(columns=["Attribute_Group_ID"])

    # 3. Artikli (Sa svim Glovo kolonama)
    items_list, seen_ids = [], set()
    for item in data.get("items", []):
        i_id = item.get("id")
        if not i_id or i_id in seen_ids: continue
        seen_ids.add(i_id)

        image_url = ""
        main_img = item.get("main_image")
        if isinstance(main_img, dict) and main_img.get("id"):
            image_url = f"https://imageproxy.wolt.com/assets/{main_img.get('id')}?w=960"
        elif item.get("images") and len(item.get("images")) > 0:
            image_url = item.get("images")[0].get("url", "")

        items_list.append({
            "External_ID": i_id,
            "Product_Name": item.get("name", ""),
            "Collection": "MENI",
            "Section": item_to_section.get(i_id, "Ostalo"),
            "Price": int((item.get("price") or item.get("base_price") or 0) / 100),
            "Image_1": image_url,
            "Description": item.get("description", "").replace("\n", " ").strip(),
            "Attribute_Groups": ", ".join([o.get("option_id") for o in item.get("options", []) if o.get("option_id")]),
            "Is_Alcoholic": "NO", "Is_Tobacco": "NO", "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
        })
    
    df_products = pd.DataFrame(items_list).sort_values(by=["Section", "Product_Name"])
    return df_products, df_groups_final, df_attributes_export

# --- UI ---
link_input = st.text_input("Nalepi Wolt link restorana:")

if st.button("🚀 POKRENI"):
    if link_input:
        with st.spinner("Sakupljam podatke..."):
            slug = get_slug(link_input)
            raw = fetch_data(slug)
            if raw:
                st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = process_all_data(raw)
                st.session_state['slug'] = slug
                st.success("Sve učitano!")

if 'df_p' in st.session_state:
    df_p, df_g, df_a, slug = st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['slug']

    st.markdown("### 📥 Download zona")
    c1, c2, _ = st.columns([1, 1.2, 4])
    with c1:
        # EXPORT: Ovde zadržavamo sve kolone, ali praznimo linkove do slika (Glovo format)
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
    tab_raw, tab_tree = st.tabs(["📊 PREGLED TABELA", "🔍 HIJERARHIJA"])

    with tab_raw:
        # --- UI PRIKAZ: Ovde prikazujemo samo bitne kolone ---
        ui_columns = ["Product_Name", "Section", "Price", "Image_1", "Description", "Attribute_Groups"]
        
        st.write("**Products (Prikazane samo bitne kolone)**")
        st.dataframe(
            df_p[ui_columns], # Filtriramo kolone za sajt
            hide_index=True,
            column_config={
                "Image_1": st.column_config.LinkColumn("Slika", display_text="Otvori sliku 🔗")
            }
        )
        
        # Prikaz grupa i atributa (isto filtrirano ako treba, ali ovde su bitne sve kolone)
        st.write("**Attribute Groups**")
        st.dataframe(df_g[["Name", "Attributes", "Max", "Min"]], hide_index=True)
        
        st.write("**Attributes**")
        st.dataframe(df_a[["Name", "Price", "Enabled"]], hide_index=True)

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
