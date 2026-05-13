def get_page_source_selenium(url):
    options = Options()
    options.add_argument('--headless') # Nevidljivi mod
    options.add_argument('--no-sandbox') 
    options.add_argument('--disable-dev-shm-usage') # NAJVAŽNIJE: Rešava problem sa RAM memorijom na Linuxu
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920x1080')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    
    # --- NOVI TRIKOVI ZA SPAŠAVANJE MEMORIJE ---
    # 1. 'eager' znači: Učitaj HTML i JS, ali ne čekaj slike, stilove i teške elemente
    options.page_load_strategy = 'eager' 
    
    # 2. Skroz zabranjujemo Chrome-u da skida slike (dramatično smanjuje potrošnju RAM-a)
    prefs = {"profile.managed_default_content_settings.images": 2}
    options.add_experimental_option("prefs", prefs)

    # Putanje do Chromiuma na Streamlit Cloud-u
    chromium_path = shutil.which("chromium") or "/usr/bin/chromium"
    options.binary_location = chromium_path
    
    driver_path = shutil.which("chromedriver") or "/usr/bin/chromedriver"
    service = Service(driver_path)
    
    driver = None
    try:
        driver = webdriver.Chrome(service=service, options=options)
        # Smanjujemo na 30s jer bez slika sajt mora da se učita mnogo brže
        driver.set_page_load_timeout(30) 
        driver.get(url)
        
        # Čekamo 3 sekunde da JavaScript popuni cene
        import time
        time.sleep(3)
        
        html_content = driver.page_source
        return html_content
    except Exception as e:
        raise e
    finally:
        if driver:
            driver.quit() # Obavezno gašenje da ne ostane da visi u memoriji
