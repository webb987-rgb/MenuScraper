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

# --- ULTRA-SIGURNA FUNKCIJA ZA ČIŠĆENJE TEKSTA ---
def latin_cleanup(text):
    if not isinstance(text, str):
        return str(text)
    
    # Prvo menjamo naša specifična slova
    mapping = {
        "č": "c", "Č": "C", "ć": "c", "Ć": "C",
        "š": "s", "Š": "S", "ž": "z", "Ž": "Z",
        "đ": "dj", "Đ": "Dj", "–": "-", "—": "-",
        "„": '"', "“": '"', "’": "'", "‘": "'"
    }
    for serbian_char, latin_char in mapping.items():
        text = text.replace(serbian_char, latin_char)
    
    # Na kraju, prisilno izbacujemo SVE što nije standardni ASCII (0-127)
    # Ovo garantuje da fpdf neće pući
    return text.encode('ascii', 'ignore').decode('ascii')

# --- POPRAVLJEN PDF GENERATOR ---
def create_clean_pdf(df_p, df_g, df_a):
    # Inicijalizujemo PDF sa 'latin-1' podrškom
    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Naslov
    pdf.set_font("Helvetica", 'B', 18) # Koristimo Helvetica jer je standardnija
    pdf.cell(0, 10, txt=latin_cleanup("JELOVNIK"), ln=True, align='C')
    pdf.ln(10)

    for section in df_p['Section'].unique():
        # Kategorija
        clean_section = latin_cleanup(str(section).upper())
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Helvetica", 'B', 14)
        pdf.cell(0, 10, txt=clean_section, ln=True, align='L', fill=True)
        pdf.ln(4)
        
        section_products = df_p[df_p['Section'] == section]
        for _, prod in section_products.iterrows():
            # Jelo i Cena
            clean_name = latin_cleanup(prod['Product_Name'])
            pdf.set_font("Helvetica", 'B', 11)
            # Koristimo kraće tačkice da ne pređemo ivicu
            pdf.cell(0, 7, txt=f"{clean_name} - {prod['Price']} RSD", ln=True)
            
            # Opis
            if prod['Description']:
                clean_desc = latin_cleanup(prod['Description'])
                pdf.set_font("Helvetica", '', 9)
                pdf.multi_cell(0, 5, txt=clean_desc)
            
            # Grupe i Atributi
            g_ids = [gid for gid in str(prod['Attribute_Groups']).split(",") if gid]
            if g_ids:
                for gid in g_ids:
                    g_info = df_g[df_g['External_ID'] == gid]
                    if not g_info.empty:
                        clean_group_name = latin_cleanup(g_info.iloc[0]['Name'])
                        pdf.set_font("Helvetica", 'B', 9)
                        pdf.set_x(15)
                        pdf.cell(0, 6, txt=f"  {clean_group_name}:", ln=True)
                        
                        rel_attrs = df_a[df_a['Group_ID_Internal'] == gid]
                        pdf.set_font("Helvetica", '', 8)
                        attr_names = [latin_cleanup(attr['Name']) for _, attr in rel_attrs.iterrows()]
                        
                        pdf.set_x(20)
                        pdf.multi_cell(0, 5, txt=", ".join(attr_names))
            
            pdf.ln(4)
        pdf.ln(6)
    
    # Generisanje PDF-a kao string (bajtovi)
    return pdf.output()

# --- UI LOGIKA ---
# ... (Ostatak koda ostaje isti, samo u download dugmetu za PDF koristimo):

if 'df_p' in st.session_state:
    # ... (kod za kolone i Excel/ZIP) ...

    with c3:
        try:
            pdf_bytes = create_clean_pdf(st.session_state['df_p'], st.session_state['df_g'], st.session_state['df_a'])
            st.download_button(
                label="📄 PDF",
                data=bytes(pdf_bytes), # Konvertujemo u bajtove za Streamlit
                file_name=f"Menu_{slug}.pdf",
                mime="application/pdf"
            )
        except Exception as e:
            st.error(f"Greška pri pravljenju PDF-a: {e}")
