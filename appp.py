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

# CSS za zbijanje elemenata
st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stExpander [data-testid="stExpanderDetails"] { padding-top: 0px !important; padding-left: 25px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    [data-testid="column"] { width: fit-content !important; min-width: fit-content !important; flex: none !important; padding-right: 10px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Wolt Menu Scraper")

# --- FUNKCIJA ZA ČIŠĆENJE TEKSTA (Sprečava beli ekran kod PDF-a) ---
def latin_cleanup(text):
    if not isinstance(text, str): return str(text)
    mapping = {
        "č": "c", "Č": "C", "ć": "c", "Ć": "C", "š": "s", "Š": "S", 
        "ž": "z", "Ž": "Z", "đ": "dj", "Đ": "Dj", "–": "-", "—": "-"
    }
    for k, v in mapping.items():
        text = text.replace(k, v)
    return text.encode('ascii', 'ignore').decode('ascii')

# --- PDF GENERATOR ---
def create_clean_pdf(df_p, df_g, df_a):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, txt=latin_cleanup("JELOVNIK"), ln=True, align='C')
    pdf.ln(10)

    for section in df_p['Section'].unique():
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Helvetica", 'B', 14)
        pdf.cell(0, 10, txt=latin_cleanup(str(section).upper()), ln=True, fill=True)
        pdf.ln(4)
        
        prods = df_p[df_p['Section'] == section]
        for _, prod in prods.iterrows():
            pdf.set_font("Helvetica", 'B', 11)
            pdf.cell(0, 7, txt=latin_cleanup(f"{prod['Product_Name']} - {prod['Price']} RSD"), ln=True)
            
            if prod['Description']:
                pdf.set_font("Helvetica", '', 9)
                pdf.multi_cell(0, 5, txt=latin_cleanup(prod['Description']))
            
            # Dodaci u PDF-u (bez ID-jeva)
            g_ids = [gid for gid in str(prod['Attribute_Groups']).split(",") if gid]
            for gid in g_ids:
                g_info = df_g[df_g['External_ID'] == gid]
                if not g_info.empty:
                    pdf.set_font("Helvetica", 'B', 9)
                    pdf.set_x(15)
                    pdf.cell(0, 6, txt=latin_cleanup(f"  {g_info.iloc[0]['Name']}:"), ln=True)
                    rel_attrs = df_a[df_a['Group_ID_Internal'] == gid]
                    attr_names = [latin_cleanup(a['Name']) for _, a in rel_attrs.iterrows()]
                    pdf.set_x(20)
                    pdf.set_font("Helvetica", '', 8)
                    pdf.multi_cell(0, 5, txt=", ".join(attr_names))
            pdf.ln(3)
        pdf.ln(5)
    return pdf.output()

# --- SCRAPER LOGIKA ---
def fetch_data(slug):
    api_url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    try:
        r = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        return r.json() if r.status_code == 200 else None
    except: return None

def process_all_data(data):
    item_to_section = {i_id: cat.get("name", "Meni") for cat in data.get("categories", []) for i_id in cat.get("item_ids", [])}
    wolt_group_to_new_id = {}
    groups_raw, attrs_raw = [], []
    
    for group in data.get("options", []):
        new_gid = str(uuid.uuid4())
        wolt_group_to_new_id[group.get("id")] = new_gid
        a_ids = []
        for val in group.get("values", []):
            new_aid = str(uuid.uuid4())
            a_ids.append(new_aid)
            attrs_raw.append({"External_ID": new_aid, "Group_ID_Internal": new_gid, "Name": val.get("name", ""), "Price": val.get("price", 0) / 100, "Enabled": "YES", "Selected_by_Default": "NO"})
        groups_raw.append({"External_ID": new_gid, "Max": 10, "Min": 0, "Name": group.get("name", "Prilog"), "Multiple_Selection": "NO", "Collapse_by_Default": "NO", "Attributes": ",".join(a_ids)})

    items_list = []
    for item in data.get("items", []):
        new_iid = str(uuid.uuid4())
        img = item.get("main_image", {}).get("id", "")
        img_url = f"https://imageproxy.wolt.com/assets/{img}?w=960" if img else ""
        gids = [wolt_group_to_new_id[o.get("option_id")] for o in item.get("options", []) if o.get("option_id") in wolt_group_to_new_id]
        items_list.append({
            "External_ID": new_iid, "Product_Name": item.get("name", ""), "Collection": "MENI", "Section": item_to_section.get(item.get("id"), "Ostalo"),
            "Price": int((item.get("price") or item.get("base_price") or 0) / 100), "Image_1": img_url, "Description": item.get("description", "").replace("\n", " ").strip(),
            "Attribute_Groups": ",".join(gids), "Is_Alcoholic": "NO", "Is_Tobacco": "NO", "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
        })
    return pd.DataFrame(items_list), pd.DataFrame(groups_raw), pd.DataFrame(attrs_raw)

# --- UI ---
link_input = st.text_input("Nalepi Wolt link:")

if st.button("🚀 POKRENI"):
    if link_input:
        slug = link_input.strip().rstrip('/').split('/')[-1]
        raw = fetch_data(slug)
        if raw:
            st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'] = process_all_data(raw)
            st.session_state['slug'] = slug

if 'df_p' in st.session_state:
    df_p, df_g, df_a, slug = st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'], st.session_state['slug']

    st.markdown("### 📥 Download")
    c1, c2, c3, _ = st.columns([1, 1, 1, 4])
    with c1:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w:
            df_p.assign(Image_1="").to_excel(w, index=False, sheet_name='Products')
            df_g.to_excel(w, index=False, sheet_name='Attribute Groups')
            df_a.drop(columns=['Group_ID_Internal']).to_excel(w, index=False, sheet_name='Attributes')
        st.download_button("📊 EXCEL", out.getvalue(), f"Glovo_{slug}.xlsx")
    with c2:
        if st.button("🖼️ ZIP"):
            z_io = io.BytesIO()
            with zipfile.ZipFile(z_io, "w") as zf:
                for _, r in df_p[df_p['Image_1'] != ""].iterrows():
                    try: zf.writestr(f"{r['Product_Name']}.jpg", requests.get(r['Image_1']).content)
                    except: continue
            st.download_button("🔥 ZIP", z_io.getvalue(), f"Slike_{slug}.zip")
    with c3:
        try: st.download_button("📄 PDF", create_clean_pdf(df_p, df_g, df_a), f"Menu_{slug}.pdf")
        except Exception as e: st.error(f"PDF Error: {e}")

    st.markdown("---")
    t_menu, t_raw = st.tabs(["🌳 MENU", "📊 SIROVI PODACI"])
    with t_menu:
        for s in df_p['Section'].unique():
            st.markdown(f"**{s}**")
            for _, p in df_p[df_p['Section'] == s].iterrows():
                with st.expander(f"{p['Product_Name']} — {p['Price']} RSD"):
                    if p['Description']: st.write(f"_{p['Description']}_")
                    for gid in [g for g in p['Attribute_Groups'].split(",") if g]:
                        g_i = df_g[df_g['External_ID'] == gid]
                        if not g_i.empty:
                            with st.expander(f"└ {g_i.iloc[0]['Name']}"):
                                for _, a in df_a[df_a['Group_ID_Internal'] == gid].iterrows():
                                    st.write(f"• {a['Name']} ({a['Price']} RSD)")
    with t_raw: st.dataframe(df_p[["Product_Name", "Section", "Price", "External_ID"]], hide_index=True)
