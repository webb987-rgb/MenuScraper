import asyncio
import datetime
import os
import platform
import subprocess
import re
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import plotly.express as px          
import plotly.graph_objects as go    
import random
from io import BytesIO
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import time
import streamlit as st
import sys

# PODEŠAVANJE LOKALNOG VREMENA
try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Europe/Belgrade")
except Exception:
    LOCAL_TZ = datetime.timezone(datetime.timedelta(hours=2))

def lokalno_vreme():
    return datetime.datetime.now(LOCAL_TZ)

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# Konfiguracija Streamlit stranice
st.set_page_config(page_title="Nadzor Dostave", page_icon="🍔", layout="wide")

# ================= MODERNI CSS DIZAJN =================
st.markdown("""
<style>
    /* Stil za Live Brojace */
    .live-card {
        display: flex; gap: 20px; background: #f8f9fa; padding: 15px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    .wolt-card {
        flex: 1; text-align: center; background: white; padding: 15px; border-radius: 10px; border-left: 6px solid #00c2e8; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .glovo-card {
        flex: 1; text-align: center; background: white; padding: 15px; border-radius: 10px; border-left: 6px solid #ffc244; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .metric-value { font-size: 32px; font-weight: bold; margin: 0; }
    .metric-title { font-size: 14px; color: #666; margin: 0; text-transform: uppercase; letter-spacing: 1px;}
    
    /* Moderni Dashboard KPI blokovi */
    .kpi-wrapper { display: flex; gap: 15px; margin-bottom: 20px; flex-wrap: wrap; }
    .kpi-card { 
        flex: 1; background: #ffffff; padding: 20px; border-radius: 12px; 
        box-shadow: 0 4px 15px rgba(0,0,0,0.04); border: 1px solid #f0f2f6; 
        text-align: center; transition: transform 0.2s, box-shadow 0.2s;
    }
    .kpi-card:hover { transform: translateY(-5px); box-shadow: 0 8px 25px rgba(0,0,0,0.1); }
    .kpi-title { font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; font-weight: 700;}
    .kpi-value { font-size: 36px; font-weight: 800; color: #2c3e50; margin: 0; line-height: 1.1;}
    .kpi-wolt { border-bottom: 4px solid #00c2e8; }
    .kpi-glovo { border-bottom: 4px solid #ffc244; }

    /* Stil za Tabove */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 8px 8px 0px 0px; padding: 10px 20px; color: #4f4f4f;}
    .stTabs [aria-selected="true"] { background-color: #e0e5ec !important; font-weight: bold; border-bottom: 3px solid #ff4b4b;}
</style>
""", unsafe_allow_html=True)
# ======================================================

# ================= FIX ZA WINDOWS I PLAYWRIGHT =================
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

@st.cache_resource
def install_playwright():
    import os
    os.system("playwright install chromium")

install_playwright()

# ================= GLOBALNA PODEŠAVANJA =================
EMAIL_POSILJAOCA = "webb987@gmail.com"
LOZINKA_POSILJAOCA = "sdehqzbnqefjlomo" 

OUTPUT_DIR = Path.cwd() / "izvestaji"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = OUTPUT_DIR / "istorija_dostave.csv"

ERRORS_DIR = Path.cwd() / "greske"
ERRORS_DIR.mkdir(parents=True, exist_ok=True)

GLOVO_AUTH_FILE = "glovo_auth.json"
WOLT_AUTH_FILE = "wolt_auth.json"

def timestamp(): return lokalno_vreme().strftime("%Y%m%d_%H%M%S")
def format_time_short(): return lokalno_vreme().strftime("%H:%M")
def log_msg(msg, placeholder=None):
    print(msg)
    if placeholder: placeholder.text(msg)

# ---------------- LJUDSKI LIVE BROJAČ (UI) ----------------
def osvezi_live_ui(ph, wolt_count, glovo_count, adresa):
    html = f"""
    <div class="live-card">
        <div class="wolt-card">
            <p class="metric-title">🚲 Wolt</p>
            <p class="metric-value" style="color: #00c2e8;">{wolt_count}</p>
        </div>
        <div class="glovo-card">
            <p class="metric-title">🍔 Glovo</p>
            <p class="metric-value" style="color: #ffc244;">{glovo_count}</p>
        </div>
    </div>
    <p style="text-align: center; color: #666; font-size: 14px;">📍 Trenutno skeniram: <b>{adresa}</b></p>
    """
    ph.markdown(html, unsafe_allow_html=True)

# ---------------- PODRŠKA ZA ĆIRILICU I EMAIL ----------------
def cirilica_u_latinicu(tekst):
    if not tekst: return ""
    mapa = { 'а':'a', 'б':'b', 'в':'v', 'г':'g', 'д':'d', 'ђ':'dj', 'е':'e', 'ж':'z', 'з':'z', 'и':'i', 'ј':'j', 'к':'k', 'л':'l', 'љ':'lj', 'м':'m', 'н':'n', 'њ':'nj', 'о':'o', 'п':'p', 'р':'r', 'с':'s', 'т':'t', 'ћ':'c', 'у':'u', 'ф':'f', 'х':'h', 'ц':'c', 'ч':'c', 'џ':'dz', 'ш':'s', 'А':'A', 'Б':'B', 'В':'V', 'Г':'G', 'Д':'D', 'Ђ':'Dj', 'Е':'E', 'Ж':'Z', 'З':'Z', 'И':'I', 'Ј':'J', 'К':'K', 'Л':'L', 'Љ':'Lj', 'М':'M', 'Н':'N', 'Њ':'Nj', 'О':'O', 'П':'P', 'Р':'R', 'С':'S', 'Т':'T', 'Ћ':'C', 'У':'U', 'Ф':'F', 'Х':'H', 'Ц':'C', 'Ч':'C', 'Џ':'Dz', 'Ш':'S' }
    for k, v in mapa.items(): tekst = tekst.replace(k, v)
    return tekst

def posalji_email(pdf_putanje, primaoci_str, log_ph=None):
    lista_primaoca = [e.strip() for e in primaoci_str.split(",") if e.strip()]
    if not lista_primaoca: return
    try:
        log_msg(f"[SISTEM] Šaljem email na: {', '.join(lista_primaoca)}...", log_ph)
        for primalac in lista_primaoca:
            msg = MIMEMultipart()
            msg['From'] = EMAIL_POSILJAOCA
            msg['To'] = primalac
            msg['Subject'] = f"Izveštaji o dostavi - {lokalno_vreme().strftime('%d.%m. u %H:%M')}"
            body = "Pozdrav šefe,\n\nU prilogu se nalaze zbirni i pojedinačni izveštaji o statusu restorana.\n\nSistem je uspešno završio ciklus."
            msg.attach(MIMEText(body, 'plain'))
            for pdf_putanja in pdf_putanje:
                with open(pdf_putanja, "rb") as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f"attachment; filename= {os.path.basename(pdf_putanja)}")
                    msg.attach(part)
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(EMAIL_POSILJAOCA, LOZINKA_POSILJAOCA)
            server.sendmail(EMAIL_POSILJAOCA, primalac, msg.as_string())
            server.quit()
        log_msg("[USPEH] Svi emailovi su poslati!", log_ph)
    except Exception as e: log_msg(f"[GREŠKA] Email nije uspeo: {e}", log_ph)

# ---------------- ISTORIJA ----------------
def sacuvaj_u_istoriju(df):
    vreme_sada = format_time_short()
    datum_sada = lokalno_vreme().strftime("%Y-%m-%d")
    istorija_podaci = []
    adrese = df["Adresa"].unique()
    for adr in adrese:
        for plat in ["Wolt", "Glovo"]:
            sub = df[(df["Adresa"] == adr) & (df["Platforma"] == plat)]
            if sub.empty: continue
            
            otvoreno = len(sub[sub["Status"] == "Otvoreno"])
            zatvoreno = len(sub[sub["Status"] == "Zatvoreno"])
            
            avg_vreme = sub["Vreme_Broj"].dropna().mean()
            avg_vreme = 0 if pd.isna(avg_vreme) else round(avg_vreme, 1)
            
            broj_akcija = len(sub[sub["Akcija"] != "-"])
            
            istorija_podaci.append({ 
                "Datum": datum_sada, "Vreme": vreme_sada, 
                "Adresa": adr, "Platforma": plat, 
                "Otvoreno": otvoreno, "Zatvoreno": zatvoreno,
                "Avg_Vreme": avg_vreme, "Broj_Akcija": broj_akcija
            })
            
    df_novo = pd.DataFrame(istorija_podaci)
    fajl_str = str(HISTORY_FILE)
    if os.path.exists(fajl_str):
        df_kombinovano = pd.concat([pd.read_csv(fajl_str), df_novo], ignore_index=True)
    else: df_kombinovano = df_novo
    try: df_kombinovano.to_csv(fajl_str, index=False)
    except: pass
    st.session_state.df_history = df_kombinovano
    return df_kombinovano

# ================= MODERNI UI GRAFIKONI (PLOTLY) =================
def kreiraj_grafikon_status_ui(df_sub, naslov):
    wolt_o = len(df_sub[(df_sub["Platforma"] == "Wolt") & (df_sub["Status"] == "Otvoreno")])
    wolt_z = len(df_sub[(df_sub["Platforma"] == "Wolt") & (df_sub["Status"] == "Zatvoreno")])
    glovo_o = len(df_sub[(df_sub["Platforma"] == "Glovo") & (df_sub["Status"] == "Otvoreno")])
    glovo_z = len(df_sub[(df_sub["Platforma"] == "Glovo") & (df_sub["Status"] == "Zatvoreno")])
    
    data = [
        {"Kategorija": "Ukupno", "Platforma": "Wolt", "Broj": wolt_o+wolt_z},
        {"Kategorija": "Otvoreno", "Platforma": "Wolt", "Broj": wolt_o},
        {"Kategorija": "Zatvoreno", "Platforma": "Wolt", "Broj": wolt_z},
        {"Kategorija": "Ukupno", "Platforma": "Glovo", "Broj": glovo_o+glovo_z},
        {"Kategorija": "Otvoreno", "Platforma": "Glovo", "Broj": glovo_o},
        {"Kategorija": "Zatvoreno", "Platforma": "Glovo", "Broj": glovo_z},
    ]
    fig = px.bar(data, x="Kategorija", y="Broj", color="Platforma", barmode="group",
                 color_discrete_map={"Wolt": "#00c2e8", "Glovo": "#ffc244"}, text="Broj", title=naslov)
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", title_font_size=18)
    fig.update_traces(textposition='outside', textfont_size=14, textfont_weight="bold")
    return fig

def kreiraj_grafikon_vreme_dostave_ui(df_sub, naslov):
    wolt_df = df_sub[(df_sub["Platforma"] == "Wolt") & (df_sub["Vreme_Broj"].notna())]
    glovo_df = df_sub[(df_sub["Platforma"] == "Glovo") & (df_sub["Vreme_Broj"].notna())]
    w_avg = wolt_df["Vreme_Broj"].dropna().mean() if not wolt_df["Vreme_Broj"].dropna().empty else 0
    w_avg = 0 if pd.isna(w_avg) else round(w_avg, 1)
    g_avg = glovo_df["Vreme_Broj"].dropna().mean() if not glovo_df["Vreme_Broj"].dropna().empty else 0
    g_avg = 0 if pd.isna(g_avg) else round(g_avg, 1)
    
    data = [{"Platforma": "Wolt", "Vreme": w_avg}, {"Platforma": "Glovo", "Vreme": g_avg}]
    fig = px.bar(data, x="Platforma", y="Vreme", color="Platforma", 
                 color_discrete_map={"Wolt": "#00c2e8", "Glovo": "#ffc244"}, text="Vreme", title=naslov)
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", yaxis_title="Prosečno vreme (min)", title_font_size=18)
    fig.update_traces(texttemplate='%{text} min', textposition='outside', textfont_size=14, textfont_weight="bold")
    return fig

def kreiraj_grafikon_popusta_ui(df_sub, izabrane_akcije, naslov):
    wolt_count = 0
    glovo_count = 0
    if izabrane_akcije:
        for _, row in df_sub.iterrows():
            akcije_restorana = []
            if pd.notna(row['Akcija']) and row['Akcija'] != "-":
                akcije_restorana = [a.replace("• ", "").strip() for a in str(row['Akcija']).split('\n') if a.strip()]
            if any(akcija in izabrane_akcije for akcija in akcije_restorana):
                if row['Platforma'] == 'Wolt': wolt_count += 1
                elif row['Platforma'] == 'Glovo': glovo_count += 1
                
    data = [{"Platforma": "Wolt", "Broj": wolt_count}, {"Platforma": "Glovo", "Broj": glovo_count}]
    fig = px.bar(data, x="Platforma", y="Broj", color="Platforma", 
                 color_discrete_map={"Wolt": "#00c2e8", "Glovo": "#ffc244"}, text="Broj", title=naslov)
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", yaxis_title="Broj restorana", title_font_size=18)
    fig.update_traces(textposition='outside', textfont_size=14, textfont_weight="bold")
    return fig

def kreiraj_timeline_grafikon_ui(df_hist, adresa=None, custom_naslov=None, metrika="Otvoreno", ylabel="Broj otvorenih restorana"):
    df_sub = df_hist.copy()
    if metrika not in df_sub.columns: df_sub[metrika] = 0

    if adresa:
        df_sub = df_sub[df_sub["Adresa"] == adresa]
        naslov = custom_naslov if custom_naslov else f'Istorijat - {adresa.upper()}'
    else:
        if not df_sub.empty and 'Platforma' in df_sub.columns:
            if 'Datum' in df_sub.columns and 'Vreme' in df_sub.columns:
                if metrika == "Avg_Vreme": df_sub = df_sub.groupby(["Datum", "Vreme", "Platforma"])[metrika].mean().reset_index()
                else: df_sub = df_sub.groupby(["Datum", "Vreme", "Platforma"])[metrika].sum().reset_index()
        naslov = custom_naslov if custom_naslov else 'Zbirni Istorijat'
        
    if len(df_sub) == 0: return go.Figure().update_layout(title="Nema istorijskih podataka", plot_bgcolor="rgba(0,0,0,0)")

    df_sub["Pravi_Datetime"] = pd.to_datetime(df_sub["Datum"] + " " + df_sub["Vreme"])
    df_sub = df_sub.sort_values(by="Pravi_Datetime")
    
    fig = px.line(df_sub, x="Pravi_Datetime", y=metrika, color="Platforma", markers=True,
                  color_discrete_map={"Wolt": "#00c2e8", "Glovo": "#ffc244"}, title=naslov)
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", 
                      xaxis_title="", yaxis_title=ylabel, hovermode="x unified", title_font_size=18)
    fig.update_xaxes(tickformat="%d.%m. u %H:%M") 
    fig.update_traces(line=dict(width=3), marker=dict(size=8))
    return fig

# ================= GRAFICI ZA PDF =================
def kreiraj_timeline_grafikon_pdf(df_hist, adresa=None, custom_naslov=None):
    df_sub = df_hist.copy()
    if adresa:
        df_sub = df_sub[df_sub["Adresa"] == adresa]
        naslov = f'Istorijat aktivnosti - {adresa.upper()}'
    else:
        if not df_sub.empty and 'Platforma' in df_sub.columns:
            if 'Datum' in df_sub.columns and 'Vreme' in df_sub.columns:
                df_sub = df_sub.groupby(["Datum", "Vreme", "Platforma"]).sum(numeric_only=True).reset_index()
        naslov = 'Zbirni Istorijat aktivnosti'
    if custom_naslov: naslov = custom_naslov
    fig, ax = plt.subplots(figsize=(10, 4), facecolor='#ffffff')
    ax.set_facecolor('#f8f9fa')
    if len(df_sub) == 0: ax.axis('off')
    else:
        df_sub = df_sub.sort_values(by=["Datum", "Vreme"])
        jedan_dan = df_sub["Datum"].nunique() <= 1 if 'Datum' in df_sub.columns else True
        if jedan_dan and 'Vreme' in df_sub.columns: df_sub["X_Label"] = df_sub["Vreme"]
        elif 'Datum' in df_sub.columns and 'Vreme' in df_sub.columns: df_sub["X_Label"] = df_sub["Datum"].str[-5:].str.replace('-', '.') + " \n" + df_sub["Vreme"]
        else: df_sub["X_Label"] = "Nepoznato"
        wolt_data = df_sub[df_sub["Platforma"] == "Wolt"].tail(48)
        glovo_data = df_sub[df_sub["Platforma"] == "Glovo"].tail(48)
        if not wolt_data.empty: ax.plot(wolt_data["X_Label"], wolt_data["Otvoreno"], marker='o', color='#00c2e8', linewidth=2.5, label='Wolt')
        if not glovo_data.empty: ax.plot(glovo_data["X_Label"], glovo_data["Otvoreno"], marker='s', color='#ffc244', linewidth=2.5, label='Glovo')
        ax.set_ylabel('Broj otvorenih', fontsize=11, fontweight='bold'); ax.set_title(naslov, fontsize=14, fontweight='bold', color='#2c3e50')
        ax.legend(frameon=True, fontsize=10, loc='lower center', bbox_to_anchor=(0.5, -0.3), ncol=2); ax.grid(True, linestyle='--', alpha=0.6)
        plt.xticks(rotation=45 if not jedan_dan else 0, fontsize=9)
    plt.tight_layout(); imgdata = BytesIO(); fig.savefig(imgdata, format='png', bbox_inches='tight', dpi=150); imgdata.seek(0); plt.close(fig)
    return imgdata

def kreiraj_grafikon_status_pdf(df_sub, naslov):
    wolt_o = len(df_sub[(df_sub["Platforma"] == "Wolt") & (df_sub["Status"] == "Otvoreno")])
    wolt_z = len(df_sub[(df_sub["Platforma"] == "Wolt") & (df_sub["Status"] == "Zatvoreno")])
    glovo_o = len(df_sub[(df_sub["Platforma"] == "Glovo") & (df_sub["Status"] == "Otvoreno")])
    glovo_z = len(df_sub[(df_sub["Platforma"] == "Glovo") & (df_sub["Status"] == "Zatvoreno")])
    fig, ax = plt.subplots(figsize=(5, 4), facecolor='#ffffff')
    labels, x, width = ['Ukupno', 'Otvoreno', 'Zatvoreno'], np.arange(3), 0.35
    ax.bar(x - width/2, [wolt_o+wolt_z, wolt_o, wolt_z], width, color='#00c2e8', label='Wolt')
    ax.bar(x + width/2, [glovo_o+glovo_z, glovo_o, glovo_z], width, color='#ffc244', label='Glovo')
    ax.set_xticks(x); ax.set_xticklabels(labels, fontweight='bold', fontsize=10)
    ax.set_title(naslov, fontsize=12, fontweight='bold', color='#2c3e50'); ax.legend(frameon=False, fontsize=9)
    max_v = max([wolt_o+wolt_z, glovo_o+glovo_z]) if max([wolt_o+wolt_z, glovo_o+glovo_z]) > 0 else 10
    ax.set_ylim(0, max_v * 1.2)
    plt.tight_layout(); imgdata = BytesIO(); fig.savefig(imgdata, format='png', bbox_inches='tight', dpi=150); imgdata.seek(0); plt.close(fig)
    return imgdata

# ---------------- EKSTRAKCIJA PODATAKA ----------------
def ukloni_kvacice(tekst):
    if not tekst: return ""
    for k, v in {'č':'c', 'ć':'c', 'ž':'z', 'š':'s', 'đ':'dj', 'Č':'C', 'Ć':'C', 'Ž':'Z', 'Š':'S', 'Đ':'Dj'}.items(): tekst = tekst.replace(k, v)
    return tekst

def izvuci_ime(tekst):
    if not tekst: return ""
    for line in str(tekst).split('\n'):
        line = line.strip()
        if not line or '%' in line or ("min" in line.lower() and re.search(r'\d+', line.lower())): continue
        if any(x in line.lower() for x in ["rsd", "din", "promo", "novo", "odlično", "besplatna dostava", "artikli", "narudžb", "popust", "off", "discount"]): continue
        if len(line) >= 2: return line
    return ""

def analiziraj_status(text):
    t = text.lower()
    if any(x in t for x in ["uskoro se zatvara", "closing soon", "zatvara se za", "closes in"]): return "Otvoreno"
    if any(k in t for k in ["samo preuzimanje", "samo za preuzimanje", "pickup only", "dostava nije dostupna", "dostava trenutno nije", "samo licno preuzimanje", "zatvoreno", "zakažite", "zakaži", "zakazi", "nedostupno", "otvara se", "otvara", "closed", "schedule"]): return "Zatvoreno"
    return "Otvoreno"

def izvuci_ocenu(tekst, plat):
    try:
        cist_tekst = re.sub(r'<[^>]+>', ' ', str(tekst)).lower()
        if plat == "Glovo":
            for p in re.findall(r'(\d{1,3})\s*%', cist_tekst):
                if int(p) >= 60: return p + "%"
        elif plat == "Wolt":
            m = re.search(r'\b([5-9][.,][0-9]|10[.,]0)\b', cist_tekst)
            if m: return m.group(1).replace(',', '.')
    except: pass
    return "-"

def izvuci_vreme_dostave(tekst):
    try:
        cist = re.sub(r'<[^>]+>', ' ', str(tekst)).lower()
        m1 = re.search(r'(\d{1,3})\s*[-–]\s*(\d{1,3})\s*(?:min|m|\')', cist)
        if m1 and int(m1.group(1)) < 120 and int(m1.group(2)) < 120: return f"{m1.group(1)}-{m1.group(2)} min", (int(m1.group(1)) + int(m1.group(2))) / 2.0
        m2 = re.search(r'\b(\d{1,3})\s*(?:min|m|\')', cist)
        if m2 and int(m2.group(1)) < 120: return f"{m2.group(1)} min", float(m2.group(1))
    except: pass
    return "-", np.nan

def izvuci_akciju(tekst, html, plat):
    cist = str(tekst) + " \n " + re.sub(r'<[^>]+>', ' \n ', str(html))
    akcije, seen, res = [], set(), []
    for line in [l.strip().lower() for l in cist.split('\n') if l.strip()]:
        if len(line) > 80: continue 
        if any(x in line for x in ["besplatna dostava", "free delivery", "dostava 0", "delivery 0"]): akcije.append("Besplatna dostava")
        elif "1+1" in line or "buy 1 get 1" in line: akcije.append("1+1 Gratis")
        elif "%" in line and re.search(r'\d', line):
            if plat == "Glovo" and re.fullmatch(r'\d{1,3}\s*%', line): continue
            akcije.append(line)
        elif any(x in line for x in ["rsd", "din"]) and any(x in line for x in ["-", "off", "discount", "popust", "save", "spend"]): akcije.append(line)
    
    sve_low = (str(tekst) + " " + str(html)).lower()
    if not akcije:
        akcije.extend([p.strip() for p in re.findall(r'(-\s*\d{1,2}\s*%|\b\d{1,2}\s*%\s*popust|\b\d{1,2}\s*%\s*off|\b\d{1,2}\s*%\s*discount)', sve_low)])
    if "wolt+" in sve_low: akcije.append("Wolt+")
    if "prime" in sve_low: akcije.append("Prime")
        
    for a in akcije:
        ac = re.sub(r'<[^>]+>', '', a).strip()
        if not ac: continue
        if "besplatna" in ac.lower() or "free" in ac.lower(): ac = "Besplatna dostava"
        elif ac not in ["Wolt+", "Prime"]: ac = ac[0].upper() + ac[1:].replace("rsd", "RSD").replace("din", "DIN")
        if ac not in seen: seen.add(ac); res.append(f"• {ac}")
    return "\n".join(res) if res else "-"

def normalizuj_ime(ime): return re.sub(r'[^\w]', '', str(ime).lower())

# ---------------- SPARTAN MOD V2: LAŽNI PIKSEL ----------------
TINY_PNG = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'

async def pametni_dijetalni_mod(route):
    if route.request.resource_type in ["image", "media"]:
        await route.fulfill(status=200, content_type="image/png", body=TINY_PNG)
    else:
        await route.continue_()

# ---------------- ORIGINALNO LJUDSKO SKROLOVANJE ----------------
async def pametno_skrolovanje_i_ekstrakcija(page, plat, address, log_ph=None, live_ph=None, live_state=None):
    results_dict = {}
    prethodni_broj = 0
    pokusaji_na_dnu = 0
    
    while True:
        if plat == "Wolt":
            podaci = await page.evaluate('''() => {
                let rez = [];
                // NOVO: Hvatamo i klasične kartice i nove "Carousel" (Shopping) kartice
                // Hvatamo same <a> tagove koji drže restoran da bismo izbegli jela
                document.querySelectorAll("a[data-test-id^='venueCard.'], a[data-test-id^='VenueWindowShoppingCarousel']").forEach(c => {
                    let link = c.href; 
                    let text = c.innerText; // Unutar a taga se nalazi samo info restorana (bez jela)
                    let html = c.innerHTML; 
                    if (link && text && text.trim().length > 0) {
                        rez.push({link, text, html});
                    }
                });
                return rez;
            }''')
        else:
            podaci = await page.evaluate('''() => {
                let rez = [];
                document.querySelectorAll("a:has(h3), a[data-testid='store-card'], .store-card a").forEach(c => {
                    let link = c.href;
                    if (!link.includes('/dostava') && !link.includes('/category')) { rez.push({link: link, text: c.innerText, html: c.innerHTML}); }
                });
                return rez;
            }''')

        for item in podaci:
            link = item['link']
            if not link or link in results_dict: continue
            
            text = item['text']
            html_content = item.get('html', '')
            sve_z = text + " " + html_content
            
            ime = ukloni_kvacice(izvuci_ime(text))
            if len(ime) < 2: continue
            
            ocena = izvuci_ocenu(sve_z, plat)
            vreme_str, vreme_num = izvuci_vreme_dostave(sve_z)
            akcija_str = izvuci_akciju(text, html_content, plat)
            
            is_new = False
            t_low = text.strip().lower()
            if plat == "Wolt":
                is_new = bool(re.search(r'>\s*(novo|new)\s*<', html_content.lower())) or (ocena == "Novo")
            else:
                is_new = t_low.endswith('new') or t_low.endswith('novo') or bool(re.search(r'•.*?new\b', t_low)) or (ocena == "Novo")

            results_dict[link] = {
                "Adresa": address, "Platforma": plat, "Naziv": ime, "Ocena": ocena,
                "Vreme dostave": vreme_str, "Akcija": akcija_str, "Status": analiziraj_status(sve_z),
                "Vreme_Broj": vreme_num, "Is_New": is_new, "Link": link
            }

        trenutni = len(results_dict)
        if trenutni > prethodni_broj:
            log_msg(f"[{plat.upper()} - {address}] Učitano {trenutni} restorana...", log_ph)
            
            if live_ph and live_state is not None:
                live_state[plat] = trenutni
                osvezi_live_ui(live_ph, live_state["Wolt"], live_state["Glovo"], address)
                
            prethodni_broj = trenutni
            pokusaji_na_dnu = 0
            
        await page.evaluate("window.scrollBy(0, 500);")
        await asyncio.sleep(0.5)
        
        h = await page.evaluate("document.body.scrollHeight")
        s = await page.evaluate("window.scrollY + window.innerHeight")
        
        if s >= h - 50:
            pokusaji_na_dnu += 1
            await asyncio.sleep(1.5)
            
            if pokusaji_na_dnu >= 5: 
                break 
        
    return list(results_dict.values())

# ---------------- SCRAPERS SA VIDEO SNIMANJEM ----------------
async def scrape_wolt(context_wolt, address, log_ph=None, live_ph=None, live_state=None, error_screenshots=None):
    page = None
    try:
        page = await context_wolt.new_page()
        
        try:
            v_path = await page.video.path()
            if v_path: error_screenshots.append(v_path)
        except: pass
        
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page.set_default_timeout(10000)
        
        await page.goto("https://wolt.com/sr/srb")
        
        try: await page.locator("[data-test-id='allow-button']").click(timeout=3000)
        except: pass
        
        try:
            input_f = page.get_by_role("combobox").first
            await input_f.wait_for(state="visible", timeout=4000)
            await input_f.click(timeout=3000)
            await input_f.fill(address)
            
            await asyncio.sleep(3)
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.5)
            await page.keyboard.press("Enter")
            
            # --- DODATO: Čekamo i klikćemo na kategoriju "Restorani" ---
            try:
                btn_restorani = page.locator("[data-test-id='tile-restaurants']").first
                await btn_restorani.wait_for(state="visible", timeout=10000)
                await btn_restorani.click()
                await asyncio.sleep(4)
            except PlaywrightTimeoutError:
                pass
            # -----------------------------------------------------------
            
            try: 
                # Promenjeno: sada čekamo i na novu VenueWindowShoppingCarousel klasu
                await page.wait_for_selector("a[data-test-id^='venueCard.'], a[data-test-id^='VenueWindowShoppingCarousel']", timeout=15000)
            except PlaywrightTimeoutError: 
                pass
            
        except PlaywrightTimeoutError:
            log_msg(f"[WOLT] VIP mod. Menjam adresu u header-u za: {address}", log_ph)
            try:
                header_btn = page.locator("[data-test-id='header.address-select-button']")
                if not await header_btn.is_visible():
                    header_btn = page.locator("header [role='button']").first
                    
                await header_btn.wait_for(state="visible", timeout=5000)
                await header_btn.click()
                await asyncio.sleep(1)

                search_modal = page.locator("[data-test-id='address-picker-input']")
                if not await search_modal.is_visible():
                    search_modal = page.get_by_role("combobox").last
                    
                await search_modal.wait_for(state="visible", timeout=5000)
                await search_modal.click()
                await search_modal.fill(address)

                await asyncio.sleep(3)
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.5)
                await page.keyboard.press("Enter")
                
                # --- DODATO: Klik na pločicu "Restorani" u VIP modu ---
                try:
                    btn_restorani = page.locator("[data-test-id='tile-restaurants']").first
                    await btn_restorani.wait_for(state="visible", timeout=10000)
                    await btn_restorani.click()
                    await asyncio.sleep(4)
                except PlaywrightTimeoutError:
                    pass
                # ------------------------------------------------------
                
                try: 
                    await page.wait_for_selector("a[data-test-id^='venueCard.'], a[data-test-id^='VenueWindowShoppingCarousel']", timeout=15000)
                except PlaywrightTimeoutError: 
                    pass
                
            except PlaywrightTimeoutError:
                log_msg(f"[WOLT ODUSTAJEM] Ne mogu da nadjem polje za promenu adrese.", log_ph)
                if page and error_screenshots is not None:
                    try:
                        err_path = str(ERRORS_DIR / f"Wolt_Timeout_{ukloni_kvacice(address).replace(' ', '_')}_{timestamp()}.png")
                        await page.screenshot(path=err_path)
                        error_screenshots.append(err_path)
                    except: pass
                return []
                
        rez = await pametno_skrolovanje_i_ekstrakcija(page, "Wolt", address, log_ph, live_ph, live_state)
        
        if len(rez) < 5:
            if error_screenshots is not None:
                err_path = str(ERRORS_DIR / f"Wolt_Upozorenje_{ukloni_kvacice(address).replace(' ', '_')}_{timestamp()}.png")
                try:
                    await page.screenshot(path=err_path)
                    error_screenshots.append(err_path)
                except: pass

        return rez

    except Exception as e: 
        log_msg(f"[WOLT GREŠKA] {e}", log_ph)
        if page and error_screenshots is not None:
            try:
                err_path = str(ERRORS_DIR / f"Wolt_Error_{ukloni_kvacice(address).replace(' ', '_')}_{timestamp()}.png")
                await page.screenshot(path=err_path)
                error_screenshots.append(err_path)
            except: pass
        return []
    finally:
        if page: await page.close()

async def scrape_glovo(context_glovo, address, log_ph=None, live_ph=None, live_state=None, error_screenshots=None):
    page = None
    try:
        page = await context_glovo.new_page()
        
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page.set_default_timeout(10000)
        
        await page.goto("https://glovoapp.com/sr/rs", wait_until="domcontentloaded")
        
        stranica_tekst = await page.content()
        if "Oh, no!" in stranica_tekst or "It looks like there's a problem" in stranica_tekst:
            log_msg(f"[GLOVO BLOKADA] {address}.", log_ph)
            if error_screenshots is not None:
                try:
                    err_path = str(ERRORS_DIR / f"Glovo_SoftBan_{ukloni_kvacice(address).replace(' ', '_')}_{timestamp()}.png")
                    await page.screenshot(path=err_path)
                    error_screenshots.append(err_path)
                except: pass
            return []
        
        try: await page.get_by_role("button", name=re.compile("Accept|Prihvati", re.I)).click(timeout=3000)
        except: pass
        
        try:
            hero_input = page.locator("#hero-container-input")
            await hero_input.wait_for(state="visible", timeout=4000)
            await hero_input.click()
            search = page.get_by_role("searchbox")
            await search.fill(address)
            
            dropdown_item = page.locator("div[data-actionable='true'][role='button']").first
            await dropdown_item.wait_for(state="visible", timeout=8000)
            await dropdown_item.click()
            
        except PlaywrightTimeoutError:
            log_msg(f"[GLOVO] Ulogovan sam, menjam adresu u header-u za: {address}", log_ph)
            try:
                header_btn = page.locator('header div[role="button"]').first
                await header_btn.wait_for(state="visible", timeout=5000)
                await header_btn.click()
                
                await asyncio.sleep(1)
                search_modal = page.get_by_role("searchbox").last
                await search_modal.wait_for(state="visible", timeout=5000)
                await search_modal.click()
                await search_modal.fill(address)
                
                await asyncio.sleep(2)
                dropdown_item = page.locator("div[data-actionable='true'][role='button']").first
                await dropdown_item.wait_for(state="visible", timeout=8000)
                await dropdown_item.click()
            except PlaywrightTimeoutError:
                log_msg(f"[GLOVO ODUSTAJEM] Ne mogu da promenim adresu za {address}. Slikam...", log_ph)
                if error_screenshots is not None:
                    try:
                        err_path = str(ERRORS_DIR / f"Glovo_Nav_Error_{ukloni_kvacice(address).replace(' ', '_')}_{timestamp()}.png")
                        await page.screenshot(path=err_path)
                        error_screenshots.append(err_path)
                    except: pass
                return []

        try:
            btn_drugo = page.locator("button:has-text('Drugo')")
            await btn_drugo.wait_for(state="visible", timeout=3000)
            await btn_drugo.click()
        except PlaywrightTimeoutError: pass
        
        try:
            btn_potvrdi = page.locator("button:has-text('Potvrdi adresu')")
            await btn_potvrdi.wait_for(state="visible", timeout=3000)
            await btn_potvrdi.click()
        except PlaywrightTimeoutError: pass
        
        await asyncio.sleep(5)
        try:
            btn_pocetna = page.locator("text='Idi na početnu stranicu'")
            if await btn_pocetna.count() > 0 and await btn_pocetna.first.is_visible(timeout=3000):
                await btn_pocetna.first.click()
                await asyncio.sleep(5)
        except: pass
        
        try:
            kat_link = page.get_by_role("link", name=re.compile(r"Restorani|Hrana|Food|Restaurants", re.I)).first
            await kat_link.wait_for(state="visible", timeout=5000)
            await kat_link.click()
        except PlaywrightTimeoutError: pass
        
        await asyncio.sleep(5)
        page.set_default_timeout(60000) 
        rez = await pametno_skrolovanje_i_ekstrakcija(page, "Glovo", address, log_ph, live_ph, live_state)
        
        if len(rez) < 5:
            if error_screenshots is not None:
                err_path = str(ERRORS_DIR / f"Glovo_Upozorenje_{ukloni_kvacice(address).replace(' ', '_')}_{timestamp()}.png")
                try:
                    await page.screenshot(path=err_path)
                    error_screenshots.append(err_path)
                except: pass

        return rez
    except Exception as e: 
        log_msg(f"[GLOVO GREŠKA] {e}", log_ph)
        if page and error_screenshots is not None:
            try:
                err_path = str(ERRORS_DIR / f"Glovo_Error_{ukloni_kvacice(address).replace(' ', '_')}_{timestamp()}.png")
                await page.screenshot(path=err_path)
                error_screenshots.append(err_path)
            except: pass
        return []
    finally:
        if page: await page.close()

# ---------------- SEKVENCIJALNI PROCES SKENIRANJA ----------------
async def proces_skeniranja(adrese, log_ph, live_ph, live_state, generisi_pdf=False, email_primaoca=""):
    sve = []
    error_screenshots = [] 
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage", 
                "--no-sandbox"             
            ]
        ) 
        
        wa = {
            "permissions": ['geolocation'],
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "record_video_dir": str(ERRORS_DIR),
            "record_video_size": {"width": 1280, "height": 720}
        }
        if os.path.exists(WOLT_AUTH_FILE):
            log_msg("🔐 WOLT: Učitana VIP propusnica.", log_ph)
            wa["storage_state"] = WOLT_AUTH_FILE
            
        ga = {
            "permissions": ['geolocation'],
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9,sr;q=0.8"}
        }
        if os.path.exists(GLOVO_AUTH_FILE):
            log_msg("🔐 GLOVO: Učitana VIP propusnica.", log_ph)
            ga["storage_state"] = GLOVO_AUTH_FILE
            
        for i, adr in enumerate(adrese):
            live_state["Wolt"] = 0
            live_state["Glovo"] = 0
            osvezi_live_ui(live_ph, 0, 0, adr)
            
            if i > 0:
                log_msg("⏳ Pauza 5 sekundi izmedju adresa...", log_ph)
                await asyncio.sleep(5)
                
            log_msg(f"\n[SISTEM] Pokrećem skeniranje za: {adr}", log_ph)
            
            log_msg("📱 Skrolujem GLOVO...", log_ph)
            context_glovo = await browser.new_context(**ga)
            await context_glovo.route("**/*", pametni_dijetalni_mod)
            r_glovo = await scrape_glovo(context_glovo, adr, log_ph, live_ph, live_state, error_screenshots)
            sve.extend(r_glovo)
            await context_glovo.close() 
            
            log_msg("🚲 Skrolujem WOLT...", log_ph)
            context_wolt = await browser.new_context(**wa)
            await context_wolt.route("**/*", pametni_dijetalni_mod)
            r_wolt = await scrape_wolt(context_wolt, adr, log_ph, live_ph, live_state, error_screenshots)
            sve.extend(r_wolt)
            await context_wolt.close() 
                
        await browser.close()
            
    if sve:
        df_s = pd.DataFrame(sve)
        df_h = sacuvaj_u_istoriju(df_s)
        
        pdf_fajlovi = []
        if generisi_pdf:
            log_msg("Generišem PDF izveštaje...", log_ph)
            zbirni = napravi_zbirni_pdf(df_s, df_h)
            if zbirni: pdf_fajlovi.append(zbirni)
            
            for adr in df_s["Adresa"].unique():
                df_sub = df_s[df_s["Adresa"] == adr]
                p_fajl = napravi_pdf_za_adresu(df_sub, adr, df_h)
                if p_fajl: pdf_fajlovi.append(p_fajl)
                
            if email_primaoca.strip() and pdf_fajlovi:
                log_msg(f"Šaljem izveštaje na email: {email_primaoca}", log_ph)
                posalji_email(pdf_fajlovi, email_primaoca, log_ph)
        else:
            log_msg("Skeniranje završeno. Opcija za PDF je isključena.", log_ph)
            
        return df_s, df_h, pdf_fajlovi, error_screenshots
    return pd.DataFrame(), pd.DataFrame(), [], error_screenshots

# ================= STREAMLIT UI =================
if 'pokrenuto' not in st.session_state: st.session_state.pokrenuto = False
if 'last_run' not in st.session_state: st.session_state.last_run = 0
if 'df_sve' not in st.session_state: st.session_state.df_sve = pd.DataFrame()
if 'pdf_fajlovi' not in st.session_state: st.session_state.pdf_fajlovi = []
if 'error_screenshots' not in st.session_state: st.session_state.error_screenshots = []
if 'loaded_history' not in st.session_state: st.session_state.loaded_history = False

if 'df_history' not in st.session_state: 
    if os.path.exists(HISTORY_FILE): st.session_state.df_history = pd.read_csv(HISTORY_FILE)
    else: st.session_state.df_history = pd.DataFrame()

st.title("🍔 Nadzor Dostave (Wolt & Glovo)")
with st.sidebar:
    st.header("⚙️ Podešavanja")
    
    adresa_1 = st.text_input("📍 Adresa 1 (Obavezna):", value="", placeholder="Makenzijeva 57, Beograd")
    adresa_2 = st.text_input("📍 Adresa 2 (Opciona):", value="", placeholder="Somborska 5, Niš")
    
    auto_refresh = st.checkbox("🔄 Automatsko osvežavanje", value=False)
    sleep_interval = st.number_input("⏱️ Interval (min):", min_value=1, value=60, disabled=not auto_refresh)
    
    generisi_pdf = st.checkbox("📄 Generiši PDF izveštaje", value=False)
    email_unos = st.text_input("📧 Pošalji na email:", placeholder="tvoj@email.com") if generisi_pdf else ""
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("▶️ POKRENI", type="primary", use_container_width=True): 
            st.session_state.pokrenuto = True
            st.session_state.loaded_history = False
            st.session_state.last_run = 0
            st.rerun()
    with c2:
        if st.button("⏹️ ZAUSTAVI", use_container_width=True): 
            st.session_state.pokrenuto = False
            st.rerun()

    st.markdown("---")
    st.header("📂 Arhiva skeniranja")
    istorija_fajlovi = sorted(list(OUTPUT_DIR.glob("Detaljno_*.csv")), reverse=True)
    opcije = {"--- Izaberi stari izveštaj ---": None}
    for f in istorija_fajlovi:
        ime = f.stem.replace("Detaljno_", "")
        try: opcije[datetime.datetime.strptime(ime, "%Y%m%d_%H%M%S").strftime("%d.%m.%Y u %H:%M:%S")] = f
        except: opcije[ime] = f

    izabrani_fajl = st.selectbox("Prethodna skeniranja:", list(opcije.keys()), label_visibility="collapsed")
    col_ucitaj, col_obrisi = st.columns(2)
    with col_ucitaj:
        if st.button("📂 Učitaj", use_container_width=True) and opcije[izabrani_fajl]:
            st.session_state.df_sve = pd.read_csv(opcije[izabrani_fajl])
            st.session_state.pokrenuto = False
            st.session_state.loaded_history = True
            st.session_state.last_run = os.path.getmtime(opcije[izabrani_fajl])
            st.rerun()
    with col_obrisi:
        if st.button("🗑️ Obriši", type="secondary", use_container_width=True) and opcije[izabrani_fajl]:
            os.remove(opcije[izabrani_fajl])
            if st.session_state.loaded_history: st.session_state.df_sve = pd.DataFrame(); st.session_state.loaded_history = False
            st.rerun()

    st.markdown("---")
    st.header("⚠️ Reset Sistema")
    with st.expander("Opasna Zona (Brisanje svega)"):
        st.warning("Ovo briše SVE stare izveštaje i istoriju aktivnosti!")
        reset_pass = st.text_input("Lozinka:", type="password", key="reset_pass")
        if st.button("🚨 OBRIŠI SVE", use_container_width=True):
            if reset_pass == "zekapeka":
                if os.path.exists(HISTORY_FILE): os.remove(HISTORY_FILE)
                st.session_state.df_history = pd.DataFrame()
                
                for f in OUTPUT_DIR.glob("Detaljno_*.csv"):
                    try: os.remove(f)
                    except: pass
                for f in OUTPUT_DIR.glob("*.pdf"):
                    try: os.remove(f)
                    except: pass
                
                st.session_state.df_sve = pd.DataFrame()
                st.session_state.loaded_history = False
                st.session_state.pokrenuto = False
                
                st.success("✅ Sistem je uspešno resetovan!")
                time.sleep(1.5)
                st.rerun()
            else:
                st.error("❌ Netačna lozinka!")

# ================= GLAVNI INTERFEJS (TABS & LOADING) =================
if st.session_state.pokrenuto or st.session_state.loaded_history:

    if st.session_state.pokrenuto:
        lista_adresa = [cirilica_u_latinicu(a.strip()) for a in [adresa_1, adresa_2] if a.strip()]
        if not lista_adresa: 
            st.warning("⚠️ Unesite bar prvu adresu da biste skenirali!"); st.session_state.pokrenuto = False; st.rerun()

        now = time.time()
        if now - st.session_state.last_run >= sleep_interval * 60 or st.session_state.last_run == 0:
            
            with st.spinner('🔄 Skripta pretražuje restorane, sačekaj...'):
                live_ui_ph = st.empty() 
                sl = st.empty() 
                live_state = {"Wolt": 0, "Glovo": 0}
                
                df, hi, pdf, err_imgs = asyncio.run(proces_skeniranja(lista_adresa, sl, live_ui_ph, live_state, generisi_pdf, email_unos))
                
                if not df.empty:
                    df.to_csv(OUTPUT_DIR / f"Detaljno_{timestamp()}.csv", index=False)

                live_ui_ph.empty()
                st.session_state.df_sve, st.session_state.df_history, st.session_state.pdf_fajlovi, st.session_state.error_screenshots, st.session_state.last_run = df, hi, pdf, err_imgs, time.time()
                sl.empty()
            st.rerun()

    df = st.session_state.df_sve
    if not df.empty:
        for col in ["Vreme_Broj", "Vreme dostave", "Ocena", "Is_New"]:
            if col not in df.columns: df[col] = False if col == "Is_New" else (np.nan if "Broj" in col else "-")

        if st.session_state.loaded_history: st.info("📂 **Pregledate arhivirani izveštaj.**")
        else: st.success(f"✅ Skeniranje završeno u: {datetime.datetime.fromtimestamp(st.session_state.last_run, LOCAL_TZ).strftime('%H:%M:%S')}")
        
        tab_dash, tab_lista, tab_uporedno, tab_akcije = st.tabs([
            "📊 Dashboard", "🔍 Lista Restorana", "⚖️ Uporedni Prikaz", "🎁 Akcije i Popusti"
        ])

        adrese_un = list(df["Adresa"].unique())
        
        with tab_dash:
            for adr in adrese_un:
                st.markdown(f"<h3 style='color: #2c3e50;'>📍 {adr.upper()}</h3>", unsafe_allow_html=True)
                sd = df[df["Adresa"] == adr]
                
                w_total = len(sd[sd["Platforma"] == "Wolt"])
                w_open = len(sd[(sd["Platforma"] == "Wolt") & (sd["Status"] == "Otvoreno")])
                g_total = len(sd[sd["Platforma"] == "Glovo"])
                g_open = len(sd[(sd["Platforma"] == "Glovo") & (sd["Status"] == "Otvoreno")])
                
                html_kpi = f"""
                <div class="kpi-wrapper">
                    <div class="kpi-card kpi-wolt">
                        <div class="kpi-title">Wolt Ukupno</div>
                        <div class="kpi-value">{w_total}</div>
                    </div>
                    <div class="kpi-card kpi-wolt">
                        <div class="kpi-title">Wolt Otvoreno</div>
                        <div class="kpi-value" style="color: #27ae60;">{w_open}</div>
                    </div>
                    <div class="kpi-card kpi-glovo">
                        <div class="kpi-title">Glovo Ukupno</div>
                        <div class="kpi-value">{g_total}</div>
                    </div>
                    <div class="kpi-card kpi-glovo">
                        <div class="kpi-title">Glovo Otvoreno</div>
                        <div class="kpi-value" style="color: #27ae60;">{g_open}</div>
                    </div>
                </div>
                """
                st.markdown(html_kpi, unsafe_allow_html=True)

            st.markdown("---")
            graf_adr = st.selectbox("📍 Filtriraj Grafikone:", ["Sve adrese"] + adrese_un, index=1 if len(adrese_un) == 1 else 0)
            c_df = df if graf_adr == "Sve adrese" else df[df["Adresa"] == graf_adr]
            
            ca, cb = st.columns(2)
            with ca: st.plotly_chart(kreiraj_grafikon_status_ui(c_df, "Uporedni Status"), use_container_width=True)
            with cb: st.plotly_chart(kreiraj_grafikon_vreme_dostave_ui(c_df, "Prosečno vreme dostave"), use_container_width=True)

            st.markdown("---")
            st.markdown("##### 📅 Istorijat Aktivnosti")
            hist_df = st.session_state.df_history.copy()
            
            if not hist_df.empty:
                c_h = hist_df if graf_adr == "Sve adrese" else hist_df[hist_df["Adresa"] == graf_adr]
                if not c_h.empty and 'Datum' in c_h.columns and 'Vreme' in c_h.columns:
                    c_h['Datetime'] = pd.to_datetime(c_h['Datum'] + ' ' + c_h['Vreme'])
                    min_d = c_h['Datetime'].min().date()
                    max_d = c_h['Datetime'].max().date()
                    
                    c_dt1, c_dt2, c_dt3, c_dt4 = st.columns(4)
                    with c_dt1: start_date = st.date_input("Od datuma:", min_d, min_value=min_d, max_value=max_d)
                    with c_dt2: start_time = st.time_input("Od vremena:", datetime.time(0, 0))
                    with c_dt3: end_date = st.date_input("Do datuma:", max_d, min_value=min_d, max_value=max_d)
                    with c_dt4: end_time = st.time_input("Do vremena:", datetime.time(23, 59))
                    
                    start_dt = pd.to_datetime(datetime.datetime.combine(start_date, start_time))
                    end_dt = pd.to_datetime(datetime.datetime.combine(end_date, end_time))
                    mask = (c_h['Datetime'] >= start_dt) & (c_h['Datetime'] <= end_dt)
                    chart_hist = c_h.loc[mask].copy()
                    
                    st.plotly_chart(kreiraj_timeline_grafikon_ui(chart_hist, None, "Istorijat: Broj otvorenih restorana", metrika="Otvoreno", ylabel="Otvoreni restorani"), use_container_width=True)
                    
                    ch1, ch2 = st.columns(2)
                    with ch1: st.plotly_chart(kreiraj_timeline_grafikon_ui(chart_hist, None, "Istorijat: Prosečno vreme dostave", metrika="Avg_Vreme", ylabel="Vreme (min)"), use_container_width=True)
                    with ch2: st.plotly_chart(kreiraj_timeline_grafikon_ui(chart_hist, None, "Istorijat: Broj restorana na akciji", metrika="Broj_Akcija", ylabel="Broj akcija"), use_container_width=True)
                else: st.info("Nema istorije za odabranu adresu.")
            else: st.info("Nema istorijskih podataka.")

        with tab_lista:
            f1, f2, f3 = st.columns(3)
            with f1: fa = st.multiselect("📍 Adresa", df["Adresa"].unique(), df["Adresa"].unique())
            with f2: fp = st.multiselect("📱 Platforma", df["Platforma"].unique(), df["Platforma"].unique())
            with f3: fs = st.multiselect("🚦 Status", ["Otvoreno", "Zatvoreno"], ["Otvoreno", "Zatvoreno"])
            c_filt1, c_filt2 = st.columns(2)
            with c_filt1: filt_new = st.checkbox("✨ Prikaži samo NOVE restorane")
            with c_filt2: filt_promo = st.checkbox("🔥 Prikaži samo restorane SA AKCIJAMA")
            
            f_df = df[(df["Adresa"].isin(fa)) & (df["Platforma"].isin(fp)) & (df["Status"].isin(fs))]
            if filt_new: f_df = f_df[f_df["Is_New"].isin([True, 'True', 'true', 1])]
            if filt_promo: f_df = f_df[f_df["Akcija"] != "-"]

            disp_df = f_df.copy()
            disp_df["Oznaka"] = disp_df["Is_New"].apply(lambda x: "✨ NOVO" if x in [True, 'True', 'true', 1] else "")
            disp_df = disp_df.drop(columns=['Naziv_Norm', 'Vreme_Broj', 'Is_New'], errors='ignore')
            cols = ["Adresa", "Platforma", "Naziv", "Status", "Ocena", "Vreme dostave", "Akcija", "Oznaka", "Link"]
            disp_df = disp_df[cols]

            def style_rows(row):
                styles = [''] * len(row)
                styles[row.index.get_loc('Status')] = 'color: #27ae60; font-weight: bold;' if row['Status'] == 'Otvoreno' else 'color: #e74c3c; font-weight: bold;'
                if row['Akcija'] != '-': styles[row.index.get_loc('Akcija')] = 'color: #8e44ad; font-weight: bold;'
                return styles

            st.dataframe(disp_df.style.apply(style_rows, axis=1), use_container_width=True, hide_index=True, height=800, column_config={"Link": st.column_config.LinkColumn("Link", display_text="Otvori na sajtu"), "Akcija": st.column_config.TextColumn("Akcija", width="large")})

        with tab_uporedno:
            c_up1, c_up2 = st.columns(2)
            with c_up1: filter_wolt_up = st.multiselect("🚦 Prikaz za Wolt:", ["Otvoreno", "Zatvoreno"], default=["Otvoreno", "Zatvoreno"], key="fw")
            with c_up2: filter_glovo_up = st.multiselect("🚦 Prikaz za Glovo:", ["Otvoreno", "Zatvoreno"], default=["Otvoreno", "Zatvoreno"], key="fg")

            df['Naziv_Norm'] = df['Naziv'].apply(normalizuj_ime)
            uporedni_podaci = []
            for adr in adrese_un:
                df_adr = df[df['Adresa'] == adr]
                zajednicki = set(df_adr[df_adr['Platforma'] == 'Wolt']['Naziv_Norm']).intersection(set(df_adr[df_adr['Platforma'] == 'Glovo']['Naziv_Norm']))
                for norm_ime in zajednicki:
                    w_row = df_adr[(df_adr['Platforma'] == 'Wolt') & (df_adr['Naziv_Norm'] == norm_ime)].iloc[0]
                    g_row = df_adr[(df_adr['Platforma'] == 'Glovo') & (df_adr['Naziv_Norm'] == norm_ime)].iloc[0]
                    uporedni_podaci.append({
                        "Adresa": adr, "Naziv (Wolt)": w_row['Naziv'], "Status Wolt": w_row['Status'], "Vreme Wolt": w_row['Vreme dostave'], "Link Wolt": w_row['Link'], "Naziv (Glovo)": g_row['Naziv'], "Status Glovo": g_row['Status'], "Vreme Glovo": g_row['Vreme dostave'], "Link Glovo": g_row['Link']
                    })
            
            if uporedni_podaci:
                df_uporedni = pd.DataFrame(uporedni_podaci)
                df_uporedni = df_uporedni[(df_uporedni['Status Wolt'].isin(filter_wolt_up)) & (df_uporedni['Status Glovo'].isin(filter_glovo_up))]
                if not df_uporedni.empty: st.dataframe(df_uporedni.style.map(lambda val: f'color: {"#27ae60" if val=="Otvoreno" else "#e74c3c"}; font-weight: bold;', subset=['Status Wolt', 'Status Glovo']), use_container_width=True, hide_index=True, height=800, column_config={"Link Wolt": st.column_config.LinkColumn("Link Wolt", display_text="Otvori Wolt"), "Link Glovo": st.column_config.LinkColumn("Link Glovo", display_text="Otvori Glovo")})
                else: st.info("Nema restorana za date filtere.")
            else: st.info("Nema zajedničkih restorana na obe platforme.")

        with tab_akcije:
            unikatne_akcije = set()
            for akcija_str in c_df['Akcija']:
                if pd.notna(akcija_str) and str(akcija_str) != "-":
                    for a in str(akcija_str).split('\n'):
                        cl = a.replace("• ", "").strip()
                        if cl: unikatne_akcije.add(cl)
            unikatne_akcije = sorted(list(unikatne_akcije))
            izabrani_popusti = st.multiselect("Odaberi akcije za prikaz na grafikonu:", unikatne_akcije, default=unikatne_akcije)
            st.plotly_chart(kreiraj_grafikon_popusta_ui(c_df, izabrani_popusti, "Broj restorana sa izabranim akcijama"), use_container_width=True)

        if st.session_state.get('pdf_fajlovi'):
            st.markdown("---"); st.subheader("📥 PDF Izveštaji")
            pc = st.columns(4)
            for i, p in enumerate(st.session_state.pdf_fajlovi):
                with pc[i % 4]:
                    with open(p, "rb") as f: st.download_button(f"Preuzmi {os.path.basename(p)}", f.read(), os.path.basename(p), "application/pdf")
                    
        # PRIKAZ Videa / Slika ZA WOLT DEBUGGING
        if st.session_state.get('error_screenshots'):
            st.markdown("---")
            st.error("⚠️ PAŽNJA: Skripta je zabeležila potencijalne probleme pri skeniranju. Proveri snimke ispod:")
            for media_path in st.session_state.error_screenshots:
                if media_path.endswith('.webm'):
                    st.video(media_path)
                else:
                    st.image(media_path, caption=os.path.basename(media_path), use_container_width=True)

    if st.session_state.pokrenuto:
        if auto_refresh:
            rem = int((sleep_interval * 60) - (time.time() - st.session_state.last_run))
            countdown_ph = st.sidebar.empty()
            while rem > 0:
                countdown_ph.info(f"⏳ Sledeće automatsko skeniranje za: **{rem//60:02d}:{rem%60:02d}**")
                time.sleep(1); rem = int((sleep_interval * 60) - (time.time() - st.session_state.last_run))
            st.rerun()
        else: st.sidebar.success("✅ Skeniranje završeno. Kliknite 'Pokreni' za novo skeniranje.")
        
else: 
    st.info("Sistem je spreman. Unesite parametre u levi meni i kliknite 'Pokreni'.")
