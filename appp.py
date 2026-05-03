import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid

# 1. Konfiguracija stranice
st.set_page_config(page_title="Wolt Scraper", page_icon="🍔", layout="wide")

st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Wolt Menu Scraper")

# --- POMOĆNE FUNKCIJE ---
def fetch_data(slug):
    api_url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "sr-RS,sr;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    try:
        r = requests.get(api_url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
        return None
    except:
        return None

def process_all_data(data):
    item_to_section = {}
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Meni")
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
            "External_ID": new_gid, "Max": 10, "Min": 0, "Name": group.get("name", "Prilog"),
            "Multiple_Selection": "NO", "Collapse_by_Default": "NO", "Attributes": ",".join(a_ids)
        })

    items_list = []
    seen_ids = set()
    for item in data.get("items", []):
        w_id = item.get("id")
        if not w_id or w_id in seen_ids: continue
        seen_ids.add(w_id)
        
        # LOGIKA ZA SLIKU - Proveravamo više lokacija
        img_id = ""
        if item.get("main_image"):
            img_id = item.get("main_image", {}).get("id", "")
        elif item.get("images") and len(item.get("images")) > 0:
            img_id = item.get("images")[0].get("id", "")
        
        img_url = f"https://imageproxy.wolt.com/assets/{img_id}?w=1200" if img_id else ""
        
        puna_cena = int((item.get("base_price") or item.get("price") or 0) / 100)
        gids = [wolt_group_to_new_id[o.get("option_id")] for o in item.get("options", []) if o.get("option_id") in wolt_group_to_new_id]

        items_list.append({
            "External_ID": str(uuid.uuid4()),
            "Product_Name": item.get("name", ""),
            "Collection": "MENI",
            "Section": item_to_section.get(w_id, "Ostalo"),
            "Price": puna_cena,
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
        slug = link_input.strip().split('?')[0].rstrip('/').split('/')[-1]
        raw = fetch_data(slug)
        if raw:
            st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = process_all_data(raw)
            st.session_state['slug'] = slug
            st.success("Podaci povučeni!")

if 'df_p' in st.session_state:
    df_p, df_g, df_a, slug = st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['slug']

    st.markdown("### 📥 Download")
    col1, col2 = st.columns(2)
    
    with col1:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w:
            df_p.to_excel(w, index=False, sheet_name='Products')
            df_g.to_excel(w, index=False, sheet_name='Attribute Groups')
            df_a.drop(columns=['Group_ID_Internal'], errors='ignore').to_excel(w, index=False, sheet_name='Attributes')
        st.download_button("📊 EXCEL", out.getvalue(), f"Wolt_{slug}.xlsx")

    with col2:
        # Prikazujemo dugme za pripremu samo ako ima slika
        has_images = df_p[df_p['Image_1'] != ""].shape[0] > 0
        if has_images:
            if st.button(f"🖼️ ZIPUJ {df_p[df_p['Image_1'] != ''].shape[0]} SLIKA"):
                z_io = io.BytesIO()
                with zipfile.ZipFile(z_io, "w") as zf:
                    progress_bar = st.progress(0)
                    imgs_to_process = df_p[df_p['Image_1'] != ""]
                    for i, (_, r) in enumerate(imgs_to_process.iterrows()):
                        try:
                            # Čišćenje imena fajla
                            name = re.sub(r'[^\w\s-]', '', r['Product_Name']).strip().replace(' ', '_')
                            # Preuzimanje slike sa timeout-om
                            img_data = requests.get(r['Image_1'], timeout=10).content
                            zf.writestr(f"{name}.jpg", img_data)
                        except:
                            continue
                        progress_bar.progress((i + 1) / len(imgs_to_process))
                st.download_button("🔥 SKINI ZIP", z_io.getvalue(), f"Slike_{slug}.zip")
        else:
            st.error("Nisu pronađeni linkovi do slika u API-ju.")

    st.dataframe(df_p[["Product_Name", "Section", "Price", "Image_1"]])
