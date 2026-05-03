import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid

# 1. Konfiguracija stranice
st.set_page_config(page_title="Wolt Scraper", page_icon="🍔", layout="wide")

# CSS za zbijanje elemenata
st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stExpander [data-testid="stExpanderDetails"] { padding-top: 0px !important; padding-left: 25px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    [data-testid="column"] { width: fit-content !important; min-width: fit-content !important; flex: none !important; padding-right: 15px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Wolt Menu Scraper")

# --- POMOĆNE FUNKCIJE ---
def fetch_data(slug):
    api_url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"}
    try:
        r = requests.get(api_url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
        else:
            st.error(f"Greška prilikom povlačenja podataka: Status kod {r.status_code}")
            return None
    except Exception as e:
        st.error(f"Došlo je do greške u konekciji: {e}")
        return None

def process_all_data(data):
    # 1. Mapiranje kategorija
    item_to_section = {}
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Meni")
        for item_id in cat.get("item_ids", []):
            item_to_section[item_id] = cat_name

    # 2. Atributi i Grupe
    wolt_group_to_new_id = {}
    groups_raw, attrs_raw = [], []
    
    # Inicijalizacija praznih lista u slučaju da nema opcija
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
        
        # LOGIKA CENE: Konvertujemo u ceo broj (dinari)
        puna_cena = int((item.get("base_price") or item.get("price") or 0) / 100)

        img = item.get("main_image", {}).get("id", "")
        img_url = f"https://imageproxy.wolt.com/assets/{img}?w=960" if img else ""
        
        # Povezivanje grupa
        gids = [wolt_group_to_new_id[o.get("option_id")] for o in item.get("options", []) if o.get("option_id") in wolt_group_to_new_id]

        items_list.append({
            "External_ID": new_iid,
            "Product_Name": item.get("name", ""),
            "Collection": "MENI",
            "Section": item_to_section.get(w_id, "Ostalo"),
            "Price": puna_cena,
            "Image_1": img_url,
            "Description": item.get("description", "").replace("\n", " ").strip(),
            "Attribute_Groups": ",".join(gids),
            "Is_Alcoholic": "NO", "Is_Tobacco": "NO", "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
        })
    
    # Kreiranje DataFrame-ova sa proverom praznih podataka
    df_p = pd.DataFrame(items_list)
    
    if groups_raw:
        df_g = pd.DataFrame(groups_raw)
    else:
        df_g = pd.DataFrame(columns=["External_ID", "Max", "Min", "Name", "Multiple_Selection", "Collapse_by_Default", "Attributes"])
        
    if attrs_raw:
        df_a = pd.DataFrame(attrs_raw)
    else:
        df_a = pd.DataFrame(columns=["External_ID", "Group_ID_Internal", "Name", "Price", "Enabled", "Selected_by_Default"])
        
    return df_p, df_g, df_a

# --- UI LOGIKA ---
link_input = st.text_input("Nalepi Wolt link restorana:", placeholder="https://wolt.com/sr/srb/belgrade/restaurant/restoran-primer")

if st.button("🚀 POKRENI"):
    if link_input:
        # Čišćenje URL-a da bi se dobio slug
        slug = link_input.strip().split('?')[0].rstrip('/').split('/')[-1]
        
        with st.spinner("Povlačim podatke sa Wolta..."):
            raw = fetch_data(slug)
            if raw:
                st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = process_all_data(raw)
                st.session_state['slug'] = slug
                st.success("Podaci uspešno učitani!")
    else:
        st.warning("Molimo unesite link.")

if 'df_p' in st.session_state:
    df_p = st.session_state['df_p']
    df_g = st.session_state['df_g']
    df_a = st.session_state['df_a']
    slug = st.session_state['slug']

    st.markdown("### 📥 Download")
    col_ex, col_zip, _ = st.columns([1, 1, 4])
    
    with col_ex:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w:
            df_p.assign(Image_1="").to_excel(w, index=False, sheet_name='Products')
            df_g.to_excel(w, index=False, sheet_name='Attribute Groups')
            # KLJUČNA ISPRAVKA: errors='ignore' sprečava pucanje ako kolona ne postoji
            df_a.drop(columns=['Group_ID_Internal'], errors='ignore').to_excel(w, index=False, sheet_name='Attributes')
        st.download_button("📊 EXCEL", out.getvalue(), f"Wolt_Data_{slug}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
    with col_zip:
        if st.button("🖼️ PRIPREMI SLIKE"):
            z_io = io.BytesIO()
            with zipfile.ZipFile(z_io, "w") as zf:
                valid_imgs = df_p[df_p['Image_1'] != ""]
                if not valid_imgs.empty:
                    bar = st.progress(0)
                    for i, (_, r) in enumerate(valid_imgs.iterrows()):
                        try:
                            clean_name = re.sub(r'[^\w\s-]', '', r['Product_Name']).strip().replace(' ', '_')
                            img_data = requests.get(r['Image_1'], timeout=10).content
                            zf.writestr(f"{clean_name}.jpg", img_data)
                        except:
                            continue
                        bar.progress((i + 1) / len(valid_imgs))
                    
                    st.download_button("🔥 SKINI ZIP", z_io.getvalue(), f"Slike_{slug}.zip")
                else:
                    st.info("Nema slika za ovaj restoran.")

    st.markdown("---")
    t_menu, t_raw = st.tabs(["🌳 PREGLED MENIJA", "📊 TABELARNI PODACI"])
    
    with t_menu:
        if not df_p.empty:
            for s in df_p['Section'].unique():
                st.markdown(f"#### {s}")
                for _, p in df_p[df_p['Section'] == s].iterrows():
                    with st.expander(f"{p['Product_Name']} — {p['Price']} RSD"):
                        if p['Description']: st.write(f"_{p['Description']}_")
                        
                        g_ids = [g for g in p['Attribute_Groups'].split(",") if g]
                        for gid in g_ids:
                            g_info = df_g[df_g['External_ID'] == gid]
                            if not g_info.empty:
                                with st.container():
                                    st.markdown(f"**└ {g_info.iloc[0]['Name']}**")
                                    # Prikaz atributa za tu grupu
                                    rel_attrs = df_a[df_a['Group_ID_Internal'] == gid]
                                    for _, a in rel_attrs.iterrows():
                                        st.write(f"&nbsp;&nbsp;&nbsp;&nbsp;• {a['Name']} (+{a['Price']} RSD)")
        else:
            st.info("Nema podataka za prikaz.")
                                    
    with t_raw:
        st.dataframe(df_p[["Product_Name", "Section", "Price", "External_ID"]], use_container_width=True, hide_index=True)
