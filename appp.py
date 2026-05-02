import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid
from fpdf import FPDF

# 1. Konfiguracija stranice
st.set_page_config(page_title="Wolt Scraper", page_icon="🍔", layout="wide")

# --- FUNKCIJA ZA ČIŠĆENJE TEKSTA (Sređuje č,ć,š za PDF) ---
def latin_cleanup(text):
    if not isinstance(text, str):
        return str(text)
    # Mapiranje naših slova u obična latinica slova
    mapping = {
        "č": "c", "Č": "C",
        "ć": "c", "Ć": "C",
        "š": "s", "Š": "S",
        "ž": "z", "Ž": "Z",
        "đ": "dj", "Đ": "Dj"
    }
    for serbian_char, latin_char in mapping.items():
        text = text.replace(serbian_char, latin_char)
    return text

# --- POPRAVLJEN PDF GENERATOR ---
def create_clean_pdf(df_p, df_g, df_a):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Naslov
    pdf.set_font("Arial", 'B', 18)
    pdf.cell(200, 10, txt="JELOVNIK", ln=True, align='C')
    pdf.ln(10)

    for section in df_p['Section'].unique():
        # Kategorija - ČISTIMO TEKST
        clean_section = latin_cleanup(str(section).upper())
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 10, txt=clean_section, ln=True, align='L', fill=True)
        pdf.ln(4)
        
        section_products = df_p[df_p['Section'] == section]
        for _, prod in section_products.iterrows():
            # Jelo i Cena - ČISTIMO TEKST
            clean_name = latin_cleanup(prod['Product_Name'])
            pdf.set_font("Arial", 'B', 11)
            pdf.cell(0, 7, txt=f"{clean_name} ............................................ {prod['Price']} RSD", ln=True)
            
            # Opis - ČISTIMO TEKST
            if prod['Description']:
                clean_desc = latin_cleanup(prod['Description'])
                pdf.set_font("Arial", 'I', 9)
                pdf.multi_cell(0, 5, txt=clean_desc)
            
            # Grupe i Atributi
            g_ids = [gid for gid in str(prod['Attribute_Groups']).split(",") if gid]
            if g_ids:
                for gid in g_ids:
                    g_info = df_g[df_g['External_ID'] == gid]
                    if not g_info.empty:
                        clean_group_name = latin_cleanup(g_info.iloc[0]['Name'])
                        pdf.set_font("Arial", 'B', 9)
                        pdf.set_x(15)
                        pdf.cell(0, 6, txt=f"   {clean_group_name}:", ln=True)
                        
                        rel_attrs = df_a[df_a['Group_ID_Internal'] == gid]
                        pdf.set_font("Arial", '', 8)
                        attr_list = []
                        for _, attr in rel_attrs.iterrows():
                            p_val = f"+{attr['Price']} RSD" if attr['Price'] > 0 else "0"
                            clean_attr_name = latin_cleanup(attr['Name'])
                            attr_list.append(f"{clean_attr_name} ({p_val})")
                        
                        pdf.set_x(20)
                        pdf.multi_cell(0, 5, txt=", ".join(attr_list))
            
            pdf.ln(4)
        pdf.ln(6)
    
    # 'latin-1' sada prolazi jer smo uradili cleanup
    return pdf.output(dest='S').encode('latin-1', errors='ignore')

# --- OSTATAK KODA (Funcije za scrapovanje ostaju iste) ---
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
    item_to_section = {}
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Meni")
        for item_id in cat.get("item_ids", []):
            item_to_section[item_id] = cat_name

    wolt_group_to_new_id = {}
    groups_raw, attributes_raw = [], []
    for group in data.get("options", []):
        w_gid = group.get("id")
        new_gid = str(uuid.uuid4())
        wolt_group_to_new_id[w_gid] = new_gid
        current_group_attr_ids = []
        for val in group.get("values", []):
            new_aid = str(uuid.uuid4())
            current_group_attr_ids.append(new_aid)
            attributes_raw.append({
                "External_ID": new_aid, "Group_ID_Internal": new_gid,
                "Name": val.get("name", ""), "Price": val.get("price", 0) / 100,
                "Enabled": "YES", "Selected_by_Default": "NO"
            })
        groups_raw.append({
            "External_ID": new_gid, "Name": group.get("name", "Prilog"),
            "Max": 10, "Min": 0, "Multiple_Selection": "NO", "Collapse_by_Default": "NO",
            "Attributes": ",".join(current_group_attr_ids)
        })

    df_p, seen_ids = [], set()
    for item in data.get("items", []):
        w_iid = item.get("id")
        if not w_iid or w_iid in seen_ids: continue
        seen_ids.add(w_iid)
        new_iid = str(uuid.uuid4())
        img_url = ""
        main_img = item.get("main_image")
        if isinstance(main_img, dict) and main_img.get("id"):
            img_url = f"https://imageproxy.wolt.com/assets/{main_img.get('id')}?w=960"

        conn_gids = [wolt_group_to_new_id[o.get("option_id")] for o in item.get("options", []) if o.get("option_id") in wolt_group_to_new_id]

        df_p.append({
            "External_ID": new_iid, "Product_Name": item.get("name", ""),
            "Collection": "MENI", "Section": item_to_section.get(w_iid, "Ostalo"),
            "Price": int((item.get("price") or item.get("base_price") or 0) / 100),
            "Image_1": img_url, "Description": item.get("description", "").replace("\n", " ").strip(),
            "Attribute_Groups": ",".join(conn_gids), "Is_Alcoholic": "NO", "Is_Tobacco": "NO", 
            "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
        })
    
    return pd.DataFrame(df_p).sort_values(by=["Section", "Product_Name"]), pd.DataFrame(groups_raw), pd.DataFrame(attributes_raw)

# --- UI ---
link_input = st.text_input("Nalepi link restorana:")

if st.button("🚀 POKRENI"):
    if link_input:
        with st.spinner("Učitavam..."):
            slug = get_slug(link_input)
            raw = fetch_data(slug)
            if raw:
                st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = process_all_data(raw)
                st.session_state['slug'] = slug

if 'df_p' in st.session_state:
    df_p, df_g, df_a, slug = st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['slug']

    st.markdown("### 📥 Download")
    # Zbijena dugmad
    st.markdown("""<style>[data-testid="column"] {width: fit-content !important; min-width: fit-content !important; flex: none !important; padding-right: 10px !important;}</style>""", unsafe_allow_html=True)
    c1, c2, c3, _ = st.columns([1, 1, 1, 4])
    
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
        if st.button("🖼️ ZIP"):
            img_df = df_p[df_p['Image_1'] != ""]
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, "w") as zf:
                for _, row in img_df.iterrows():
                    try:
                        res = requests.get(row['Image_1'], timeout=10)
                        zf.writestr(f"{sanitize_filename(row['Product_Name'])}.jpg", res.content)
                    except: continue
            st.download_button("🔥 ZIP", zip_io.getvalue(), f"Slike_{slug}.zip")
            
    with c3:
        pdf_data = create_clean_pdf(df_p, df_g, df_a)
        st.download_button("📄 PDF", pdf_data, f"Jelovnik_{slug}.pdf", "application/pdf")

    st.markdown("---")
    tab_menu, tab_raw = st.tabs(["🌳 MENU", "📊 SIROVI PODACI"])

    with tab_menu:
        for section in df_p['Section'].unique():
            st.markdown(f"**{section}**")
            for _, prod in df_p[df_p['Section'] == section].iterrows():
                with st.expander(f"{prod['Product_Name']} — {prod['Price']} RSD"):
                    if prod['Description']: st.write(f"_{prod['Description']}_")
                    g_ids = [gid for gid in str(prod['Attribute_Groups']).split(",") if gid]
                    for gid in g_ids:
                        g_info = df_g[df_g['External_ID'] == gid]
                        if not g_info.empty:
                            with st.expander(f"└ {g_info.iloc[0]['Name']}"):
                                rel_attrs = df_a[df_a['Group_ID_Internal'] == gid]
                                for _, attr in rel_attrs.iterrows():
                                    st.write(f"• {attr['Name']} ({attr['Price']} RSD)")

    with tab_raw:
        st.dataframe(df_p[["Product_Name", "Section", "Price", "External_ID"]], hide_index=True)
