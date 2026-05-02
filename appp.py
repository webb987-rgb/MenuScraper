import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid

# 1. Konfiguracija stranice
st.set_page_config(page_title="Wolt Scraper v2", page_icon="🍔", layout="wide")

st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    [data-testid="column"] { width: fit-content !important; min-width: fit-content !important; flex: none !important; padding-right: 15px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Wolt Scraper (Puna cena + Akcije)")

# --- POMOĆNE FUNKCIJE ---
def fetch_data(slug):
    api_url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    try:
        r = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        return r.json() if r.status_code == 200 else None
    except: return None

def process_all_data(data):
    # Mapiranje kategorija
    item_to_section = {i_id: cat.get("name", "Meni") for cat in data.get("categories", []) for i_id in cat.get("item_ids", [])}
    
    # Grupe i Atributi
    w_group_to_new_id = {}
    groups_raw, attrs_raw = [], []
    for group in data.get("options", []):
        new_gid = str(uuid.uuid4())
        w_group_to_new_id[group.get("id")] = new_gid
        a_ids = []
        for val in group.get("values", []):
            new_aid = str(uuid.uuid4())
            a_ids.append(new_aid)
            attrs_raw.append({"External_ID": new_aid, "Group_ID_Internal": new_gid, "Name": val.get("name", ""), "Price": val.get("price", 0) / 100, "Enabled": "YES", "Selected_by_Default": "NO"})
        groups_raw.append({"External_ID": new_gid, "Max": 10, "Min": 0, "Name": group.get("name", "Prilog"), "Multiple_Selection": "NO", "Collapse_by_Default": "NO", "Attributes": ",".join(a_ids)})

    # Proizvodi i Akcije
    items_list = []
    promos = []
    seen_ids = set()

    for item in data.get("items", []):
        w_id = item.get("id")
        if not w_id or w_id in seen_ids: continue
        seen_ids.add(w_id)
        
        # LOGIKA CENE: Uvek uzimamo base_price (punu cenu) ako postoji
        base_price_raw = item.get("base_price") or item.get("price") or 0
        current_price_raw = item.get("price") or 0
        puna_cena = int(base_price_raw / 100)
        akcijska_cena = int(current_price_raw / 100)

        # Provera da li je na promociji
        if akcijska_cena < puna_cena and akcijska_cena > 0:
            promos.append({
                "Proizvod": item.get("name", ""),
                "Kategorija": item_to_section.get(w_id, "Ostalo"),
                "Puna cena": f"{puna_cena} RSD",
                "Akcijska cena": f"{akcijska_cena} RSD",
                "Popust": f"{round((1 - akcijska_cena/puna_cena)*100)}%"
            })

        new_iid = str(uuid.uuid4())
        img = item.get("main_image", {}).get("id", "")
        img_url = f"https://imageproxy.wolt.com/assets/{img}?w=960" if img else ""
        gids = [w_group_to_new_id[o.get("option_id")] for o in item.get("options", []) if o.get("option_id") in w_group_to_new_id]

        items_list.append({
            "External_ID": new_iid,
            "Product_Name": item.get("name", ""),
            "Collection": "MENI",
            "Section": item_to_section.get(w_id, "Ostalo"),
            "Price": puna_cena, # OVDE IDE PUNA CENA
            "Image_1": img_url,
            "Description": item.get("description", "").replace("\n", " ").strip(),
            "Attribute_Groups": ",".join(gids),
            "Is_Alcoholic": "NO", "Is_Tobacco": "NO", "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
        })
        
    return pd.DataFrame(items_list), pd.DataFrame(groups_raw), pd.DataFrame(attrs_raw), pd.DataFrame(promos)

# --- UI ---
link_input = st.text_input("Nalepi Wolt link:")

if st.button("🚀 POKRENI"):
    if link_input:
        slug = link_input.strip().rstrip('/').split('/')[-1]
        raw = fetch_data(slug)
        if raw:
            st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['df_promos'] = process_all_data(raw)
            st.session_state['slug'] = slug

if 'df_p' in st.session_state:
    df_p, df_g, df_a, df_promos, slug = st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['df_promos'], st.session_state['slug']

    st.markdown("### 📥 Download")
    c1, c2, _ = st.columns([1, 1, 4])
    with c1:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w:
            df_p.assign(Image_1="").to_excel(w, index=False, sheet_name='Products')
            df_g.to_excel(w, index=False, sheet_name='Attribute Groups')
            df_a.drop(columns=['Group_ID_Internal']).to_excel(w, index=False, sheet_name='Attributes')
        st.download_button("📊 EXCEL (PUNE CENE)", out.getvalue(), f"Glovo_PUNE_CENE_{slug}.xlsx")
    with c2:
        if st.button("🖼️ ZIP SLIKE"):
            z_io = io.BytesIO()
            with zipfile.ZipFile(z_io, "w") as zf:
                for _, r in df_p[df_p['Image_1'] != ""].iterrows():
                    try: zf.writestr(f"{r['Product_Name']}.jpg", requests.get(r['Image_1']).content)
                    except: continue
            st.download_button("🔥 SKINI ZIP", z_io.getvalue(), f"Slike_{slug}.zip")

    st.markdown("---")
    t_menu, t_promos, t_raw = st.tabs(["🌳 MENU", "🏷️ AKCIJE", "📊 SIROVI PODACI"])
    
    with t_menu:
        for s in df_p['Section'].unique():
            st.markdown(f"**{s}**")
            for _, p in df_p[df_p['Section'] == s].iterrows():
                with st.expander(f"{p['Product_Name']} — {p['Price']} RSD"):
                    st.write(p['Description'])
    
    with t_promos:
        if not df_promos.empty:
            st.warning(f"Pronađeno {len(df_promos)} artikala na popustu!")
            st.table(df_promos)
        else:
            st.info("Trenutno nema aktivnih popusta na Woltu za ovaj restoran.")
            
    with t_raw:
        st.dataframe(df_p[["Product_Name", "Section", "Price", "External_ID"]], hide_index=True)
