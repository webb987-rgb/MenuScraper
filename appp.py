import streamlit as st
import requests
import pandas as pd
import io
import zipfile
import re
import uuid
from fpdf import FPDF # NOVO: Za PDF generisanje

# 1. Konfiguracija stranice
st.set_page_config(page_title="Wolt Scraper", page_icon="🍔", layout="wide")

# CSS za sitniji prikaz i maksimalno zbijanje dugmadi
st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stExpander [data-testid="stExpanderDetails"] { padding-top: 0px !important; padding-left: 25px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    /* Zbijanje kolona za dugmad */
    [data-testid="column"] { width: fit-content !important; min-width: fit-content !important; flex: none !important; padding-right: 10px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Wolt Menu Scraper")

# --- POMOĆNE FUNKCIJE ---
def get_slug(url):
    return url.strip().rstrip('/').split('/')[-1]

def sanitize_filename(filename):
    s = re.sub(r'[^\w\s-]', '', filename).strip().replace(' ', '_')
    return s if s else "bez_imena"

def create_pdf(df):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    # Dodajemo podršku za naša slova (koristi standardni font, ali bez specifičnih karaktera ako nisu instalirani fontovi)
    # Za punu podršku č,ć,š potreban je .ttf fajl, ovde koristimo standardni Arial-like
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="JELOVNIK", ln=True, align='C')
    pdf.ln(10)

    for section in df['Section'].unique():
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(200, 10, txt=str(section), ln=True, align='L')
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)
        
        section_products = df[df['Section'] == section]
        for _, prod in section_products.iterrows():
            pdf.set_font("Arial", 'B', 11)
            pdf.cell(0, 6, txt=f"{prod['Product_Name']} - {prod['Price']} RSD", ln=True)
            
            if prod['Description']:
                pdf.set_font("Arial", '', 9)
                pdf.multi_cell(0, 5, txt=str(prod['Description']))
            pdf.ln(3)
        pdf.ln(5)
    
    return pdf.output(dest='S').encode('latin-1', errors='replace')

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
        with st.spinner("Sakupljam podatke..."):
            slug = get_slug(link_input)
            raw = fetch_data(slug)
            if raw:
                st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = process_all_data(raw)
                st.session_state['slug'] = slug

if 'df_p' in st.session_state:
    df_p, df_g, df_a, slug = st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['slug']

    # --- DOWNLOAD SEKCIJA (Ultra zbijeno) ---
    st.markdown("### 📥 Download")
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
        pdf_data = create_pdf(df_p)
        st.download_button("📄 PDF", pdf_data, f"Menu_{slug}.pdf", "application/pdf")

    st.markdown("---")
    
    # --- TABOVI (Menu prvi) ---
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
