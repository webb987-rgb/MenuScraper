import streamlit as st
from curl_cffi import requests
import pandas as pd
import time

# --- 1. KONFIGURACIJA ---
st.set_page_config(page_title="Wolt Menu Scraper", page_icon="🍴", layout="wide")

st.title("🍴 Wolt Menu Scraper")
st.markdown("Unesi link restorana (npr. *https://wolt.com/sr/srb/nis/restaurant/toster-bar*) da izvučeš ceo jelovnik sa cenama.")

# --- 2. FUNKCIJA ZA SKREPOVANJE ---
def scrape_wolt_menu(url):
    try:
        # Izvlačenje slug-a iz URL-a
        slug = url.split('/')[-1]
        
        # Wolt API endpoint za menu (v3 je najstabilniji)
        api_url = f"https://restaurant-api.wolt.com/v3/venues/slug/{slug}/menu"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "sr-RS,sr;q=0.9,en-US;q=0.8,en;q=0.7"
        }

        # Koristimo impersonate da nas Wolt ne blokira
        response = requests.get(api_url, headers=headers, impersonate="chrome120", timeout=20)
        
        if response.status_code != 200:
            st.error(f"Greška: API je vratio status {response.status_code}")
            return None

        data = response.json()
        
        # Glavne liste za podatke
        menu_items = []
        
        # Wolt menu struktura: categories -> items
        categories = data.get("categories", [])
        items_dict = {item["id"]: item for item in data.get("items", [])}

        for cat in categories:
            cat_name = cat.get("name", "Bez kategorije")
            item_ids = cat.get("item_ids", [])
            
            for i_id in item_ids:
                item = items_dict.get(i_id)
                if item:
                    # Cena je u API-ju obično u formatu 85000 (za 850.00 din)
                    raw_price = item.get("base_price", 0)
                    formatted_price = raw_price / 100
                    
                    menu_items.append({
                        "Kategorija": cat_name,
                        "Naziv Jela": item.get("name"),
                        "Cena (RSD)": formatted_price,
                        "Opis": item.get("description", "Nema opisa"),
                        "Dostupno": "Da" if not item.get("disabled", False) else "Ne"
                    })
        
        return pd.DataFrame(menu_items)

    except Exception as e:
        st.error(f"Došlo je do greške: {str(e)}")
        return None

# --- 3. UI LOGIKA ---
url_input = st.text_input("Link restorana:", placeholder="https://wolt.com/sr/srb/...")

if st.button("🚀 IZVUCI MENI"):
    if url_input:
        with st.spinner("Povezujem se sa Woltom... (Ovo može potrajati par sekundi)"):
            # Mali delay da simuliramo ljudsko ponašanje
            time.sleep(1.5)
            
            df_menu = scrape_wolt_menu(url_input)
            
            if df_menu is not None and not df_menu.empty:
                st.success(f"Uspešno izvučeno {len(df_menu)} artikala!")
                
                # Statistika menija
                col1, col2, col3 = st.columns(3)
                col1.metric("Ukupno jela", len(df_menu))
                col2.metric("Najskuplje jelo", f"{df_menu['Cena (RSD)'].max()} RSD")
                col3.metric("Prosečna cena", f"{round(df_menu['Cena (RSD)'].mean(), 2)} RSD")
                
                st.divider()
                
                # Prikaz tabele
                st.dataframe(df_menu, use_container_width=True, hide_index=True)
                
                # Download dugme
                csv = df_menu.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Preuzmi Meni kao CSV",
                    data=csv,
                    file_name=f"wolt_menu_{url_input.split('/')[-1]}.csv",
                    mime='text/csv',
                )
            else:
                st.warning("Nije pronađen nijedan artikal. Proveri da li je link ispravan.")
    else:
        st.info("Prvo unesi link restorana.")

# --- 4. DODATNE INFO ---
with st.expander("Uputstvo"):
    st.write("""
    1. Otvori Wolt u svom pretraživaču.
    2. Izaberi restoran i kopiraj ceo URL iz adresne trake.
    3. Nalepi ga ovde i klikni na dugme.
    4. Skripta će automatski razvrstati jela po kategorijama, izvući cene i opise.
    """)
