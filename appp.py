import streamlit as st
import requests
try:
    from curl_cffi import requests as cf_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False
import pandas as pd
import io
import zipfile
import re
import uuid
import json
import os
import concurrent.futures
import google.generativeai as genai
import time

# 1. Page Configuration
st.set_page_config(page_title="Menu Scraper PRO", page_icon="🍔", layout="wide")

# --- SECURE LOADING OF MULTIPLE API KEYS ---
def get_gemini_keys():
    raw_keys = ""
    try:
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                config = json.load(f)
                raw_keys = config.get("GEMINI_API_KEY", "")
    except:
        pass
    if raw_keys:
        return [k.strip() for k in raw_keys.split(",") if k.strip()]
    return []

GEMINI_KEYS_LIST = get_gemini_keys()

# CSS for UI Customization
st.markdown("""
    <style>
    .stExpander { border: none !important; margin-bottom: -10px !important; }
    .stExpander [data-testid="stExpanderDetails"] { padding-top: 0px !important; padding-left: 25px !important; }
    .stMarkdown p { font-size: 14px !important; margin-bottom: 2px !important; }
    .stDataFrame { border: 1px solid #e6e9ef; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🍔 Menu Scraper PRO")

# --- HELPER: Apply Markup, Fixed Amount, and Rounding Logic ---
def apply_price_logic(price, markup_percent, fixed_amount, round_up, curr):
    new_price = price * (1 + markup_percent / 100)
    new_price += fixed_amount

    if curr == "RSD":
        final_price = int(new_price)
        if round_up and final_price > 0:
            final_price = ((final_price + 9) // 10) * 10
        return final_price
    else:
        return round(new_price, 2)

# --- HELPER: HIGH-SPEED IMAGE DOWNLOAD ---
def download_single_image(url, product_name):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            name = re.sub(r'[^\w\s-]', '', str(product_name)).strip().replace(' ', '_')
            name = f"{name}_{str(uuid.uuid4())[:4]}.jpg"
            return name, res.content
    except:
        pass
    return None, None

# --- WOLT SCRAPER LOGIC ---
WOLT_COUNTRY_CURRENCY_MAP = {
    "srb": "RSD", "bgr": "EUR", "hrv": "EUR", "svn": "EUR", "deu": "EUR",
    "aut": "EUR", "cyp": "EUR", "grc": "EUR", "fin": "EUR", "est": "EUR",
    "lva": "EUR", "ltu": "EUR", "prt": "EUR", "esp": "EUR", "mlt": "EUR",
    "svk": "EUR", "nld": "EUR", "irl": "EUR", "lux": "EUR", "ita": "EUR",
    "bel": "EUR", "isr": "ILS", "cze": "CZK", "dnk": "DKK", "pol": "PLN",
    "swe": "SEK", "gbr": "GBP", "nor": "NOK", "hun": "HUF", "aze": "AZN",
    "kwt": "KWD", "geo": "GEL", "arm": "AMD", "usa": "USD",
}

WOLT_ZERO_DECIMAL_CURRENCIES = {"RSD", "HUF", "JPY", "ISK", "KRW", "CLP"}

def detect_wolt_currency(data, restaurant_url):
    found = _find_key_recursive(data, "currency")
    if found:
        return str(found).upper()
    match = re.search(r'wolt\.com/[a-z]{2}/([a-z]{3})/', restaurant_url)
    if match:
        return WOLT_COUNTRY_CURRENCY_MAP.get(match.group(1).lower(), "")
    return ""

def fetch_data(slug):
    api_url = f"https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/{slug}/assortment"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(api_url, headers=headers, timeout=15)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def process_all_data(data, restaurant_url):
    detected_curr = detect_wolt_currency(data, restaurant_url) or "EUR"
    zero_decimal = detected_curr in WOLT_ZERO_DECIMAL_CURRENCIES

    ordered_sections = []
    item_to_section = {}
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Menu")
        ordered_sections.append(cat_name)
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

            attr_price = val.get("price", 0) / 100
            attr_price = int(attr_price) if zero_decimal else round(attr_price, 2)

            attrs_raw.append({
                "External_ID": new_aid, "Group_ID_Internal": new_gid,
                "Name": val.get("name", ""), "Price": attr_price,
                "Enabled": "YES", "Selected_by_Default": "NO"
            })
        groups_raw.append({
            "External_ID": new_gid, "Max": 10, "Min": 0, "Name": group.get("name", "Option"),
            "Multiple_Selection": "NO", "Collapse_by_Default": "NO", "Attributes": ",".join(a_ids)
        })

    items_list = []
    seen_ids = set()
    for cat in data.get("categories", []):
        cat_name = cat.get("name", "Menu")
        for w_id in cat.get("item_ids", []):
            if w_id in seen_ids: continue
            item = next((i for i in data.get("items", []) if i.get("id") == w_id), None)
            if not item: continue
            seen_ids.add(w_id)
            new_iid = str(uuid.uuid4())

            raw_price = (item.get("base_price") or item.get("price") or 0) / 100
            puna_cena = int(raw_price) if zero_decimal else round(raw_price, 2)

            img_url = ""
            main_img = item.get("main_image")
            if isinstance(main_img, dict) and main_img.get("id"):
                img_url = f"https://imageproxy.wolt.com/assets/{main_img['id']}?w=960"
            elif item.get("images") and len(item.get("images")) > 0:
                first_img = item['images'][0]
                if isinstance(first_img, dict):
                    img_id = first_img.get('id')
                    if img_id:
                        img_url = f"https://imageproxy.wolt.com/assets/{img_id}?w=960"
                    elif first_img.get('url'):
                        img_url = first_img.get('url')

            gids = [wolt_group_to_new_id[o.get("option_id")] for o in item.get("options", []) if o.get("option_id") in wolt_group_to_new_id]
            items_list.append({
                "External_ID": new_iid, "Product_Name": item.get("name", ""), "Collection": "MENU",
                "Section": cat_name, "Price": puna_cena, "Image_1": img_url,
                "Description": item.get("description", "").replace("\n", " ").strip(),
                "Attribute_Groups": ",".join(gids), "Is_Alcoholic": "NO", "Is_Tobacco": "NO",
                "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
            })
    return pd.DataFrame(items_list), pd.DataFrame(groups_raw), pd.DataFrame(attrs_raw), ordered_sections, detected_curr

# --- BOLT FOOD SCRAPER LOGIC ---
BOLT_CITY_COORDS = {
    "sofia": (42.6977, 23.3219),
    "plovdiv": (42.1354, 24.7453),
    "varna": (43.2141, 27.9147),
    "burgas": (42.5048, 27.4626),
    "ruse": (43.8564, 25.9709),
    "stara-zagora": (42.4258, 25.6345),
    "pleven": (43.4170, 24.6067),
    "bucuresti": (44.4268, 26.1025),
    "cluj-napoca": (46.7712, 23.6236),
    "timisoara": (45.7489, 21.2087),
    "iasi": (47.1585, 27.6014),
    "constanta": (44.1598, 28.6348),
    "brasov": (45.6427, 25.5887),
    "alba-iulia": (46.0731, 23.5805),
    "sibiu": (45.7983, 24.1256),
    "craiova": (44.3302, 23.7949),
}

def guess_bolt_coords(url):
    m = re.search(r'/en/\d+-([a-z0-9\-]+)/p/', url.strip())
    if m and m.group(1) in BOLT_CITY_COORDS:
        return BOLT_CITY_COORDS[m.group(1)], m.group(1)
    return None, None

def fetch_bolt_data(provider_id, lat, lng):
    url = "https://deliveryuser.live.boltsvc.net/deliveryClient/public/getMenuCategories"
    device_uuid = str(uuid.uuid4())
    params = {
        "provider_id": provider_id,
        "delivery_lat": lat,
        "delivery_lng": lng,
        "version": "FW.1.113",
        "language": "en-US",
        "session_id": f"{device_uuid}eater{int(time.time())}",
        "distinct_id": f"$device:{str(uuid.uuid4())}",
        "country": "rs",
        "device_name": "web",
        "device_os_version": "web",
        "deviceId": device_uuid,
        "deviceType": "web",
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def _bolt_get_name(node):
    n = node.get("name")
    if isinstance(n, dict):
        return n.get("value", "")
    return n or ""

def process_bolt_data(raw):
    if not raw or raw.get("code") != 0:
        return None
    data = raw.get("data", {})
    items = data.get("items", {})
    root_id = str(data.get("root_id", ""))
    root = items.get(root_id)
    if not root:
        return None

    ordered_sections = []
    section_dish_ids = {}
    for cid in root.get("child_ids", []):
        cat = items.get(str(cid))
        if not cat or cat.get("type") != "category":
            continue
        cat_name = _bolt_get_name(cat)
        if not cat_name:
            continue
        ordered_sections.append(cat_name)
        section_dish_ids[cat_name] = cat.get("child_ids", [])

    groups_raw, attrs_raw, items_list = [], [], []
    seen_dishes = set()
    detected_currency = [None]

    def process_option_group(group_id):
        group = items.get(str(group_id))
        if not group or "group" not in group.get("type", ""):
            return None
        new_gid = str(uuid.uuid4())
        a_ids = []
        for opt_id in group.get("child_ids", []):
            opt = items.get(str(opt_id))
            if not opt:
                continue
            new_aid = str(uuid.uuid4())
            a_ids.append(new_aid)
            opt_price = opt.get("price") or {}
            attrs_raw.append({
                "External_ID": new_aid, "Group_ID_Internal": new_gid,
                "Name": _bolt_get_name(opt), "Price": opt_price.get("value", 0),
                "Enabled": "YES", "Selected_by_Default": "NO"
            })
        groups_raw.append({
            "External_ID": new_gid, "Max": 10, "Min": 0, "Name": _bolt_get_name(group) or "Option",
            "Multiple_Selection": "NO", "Collapse_by_Default": "NO", "Attributes": ",".join(a_ids)
        })
        return new_gid

    for cat_name in ordered_sections:
        for dish_id in section_dish_ids.get(cat_name, []):
            if dish_id in seen_dishes:
                continue
            dish = items.get(str(dish_id))
            if not dish or dish.get("type") != "dish":
                continue
            seen_dishes.add(dish_id)

            price_obj = dish.get("price") or {}
            price_val = price_obj.get("value", 0)
            currency = price_obj.get("currency", "")
            if currency and not detected_currency[0]:
                detected_currency[0] = currency.upper()

            desc_obj = dish.get("description") or {}
            desc = desc_obj.get("value", "") if isinstance(desc_obj, dict) else ""

            img_url = ""
            try:
                orig = dish.get("images", {}).get("menu_item_list_v1", {}).get("aspect_ratio_map", {}).get("original", {})
                img_url = orig.get("3x") or orig.get("2x") or orig.get("1x") or ""
            except:
                pass

            gids = [g for g in (process_option_group(cid) for cid in dish.get("child_ids", [])) if g]

            items_list.append({
                "External_ID": str(uuid.uuid4()), "Product_Name": _bolt_get_name(dish),
                "Collection": "MENU", "Section": cat_name, "Price": price_val,
                "Image_1": img_url, "Description": desc.replace("\n", " ").strip() if desc else "",
                "Attribute_Groups": ",".join(gids), "Is_Alcoholic": "NO", "Is_Tobacco": "NO",
                "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
            })

    return pd.DataFrame(items_list), pd.DataFrame(groups_raw), pd.DataFrame(attrs_raw), ordered_sections, detected_currency[0]

# --- TAKEAWAY.COM SCRAPER LOGIC ---
# Menu data is fetched DIRECTLY from the public JET menu CDN (no bot protection).
# File names are fully derivable from the restaurant URL:
#   manifest: {slug}_{country}_manifest_{lang}.json  -> categories + country
#   items:    {slug}_{country}_items_{lang}.json     -> all items with prices
TAKEAWAY_CDN = "https://globalmenucdn.eu-central-1.production.jet-external.com/"

TAKEAWAY_CURRENCY_MAP = {
    "bg": "BGN", "ro": "RON", "hu": "HUF", "pl": "PLN", "cz": "CZK",
    "nl": "EUR", "at": "EUR", "de": "EUR", "lu": "EUR", "fr": "EUR",
    "it": "EUR", "pt": "EUR", "es": "EUR", "ie": "EUR", "gr": "EUR",
}

TAKEAWAY_FIXED_EUR_RATE = {
    "BGN": 1.95583,
}

def convert_takeaway_price_to_eur(price, source_currency):
    rate = TAKEAWAY_FIXED_EUR_RATE.get(source_currency)
    if rate and price:
        return round(price / rate, 2)
    return price

def _find_key_recursive(obj, target_key):
    if isinstance(obj, dict):
        if target_key in obj:
            return obj[target_key]
        for v in obj.values():
            result = _find_key_recursive(v, target_key)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_key_recursive(item, target_key)
            if result is not None:
                return result
    return None

def parse_takeaway_url(url):
    """URL format: takeaway.com/{country}(-{lang})?/menu/{slug}"""
    m = re.search(r'takeaway\.com/([a-z]{2})(?:-([a-z]{2}))?/menu/([^/?#]+)', url)
    if not m:
        return None, None, None
    return m.group(1), m.group(2) or "", m.group(3)

def fetch_takeaway_data(restaurant_url, debug=False):
    """Fetch menu directly from the public JET menu CDN — works on Streamlit Cloud."""
    def _log(msg):
        if debug:
            st.write(f"🔎 DEBUG: {msg}")

    country, lang, slug = parse_takeaway_url(restaurant_url)
    if not slug:
        if debug:
            st.session_state['takeaway_last_error'] = "URL not recognized — expected .../{country}/menu/{slug}"
        return None

    _log(f"Parsed URL -> country={country}, lang={lang or '(default)'}, slug={slug}")
    headers = {"User-Agent": "Mozilla/5.0"}

    # 1) Manifest (categories + country + items file name)
    manifest = None
    manifest_candidates = ([f"{slug}_{country}_manifest_{lang}.json"] if lang else []) + [f"{slug}_{country}_manifest.json"]
    for name in manifest_candidates:
        try:
            r = requests.get(TAKEAWAY_CDN + name, headers=headers, timeout=20)
            _log(f"manifest {name} -> {r.status_code}")
            if r.status_code == 200:
                manifest = r.json()
                break
        except Exception as e:
            _log(f"manifest {name} failed: {e}")
    if not manifest:
        if debug:
            st.session_state['takeaway_last_error'] = "Manifest not found on CDN — check the link/slug."
        return None

    # 2) Items (names, descriptions, prices, images)
    items_data = None
    items_candidates = []
    if manifest.get("ItemsUrl"):
        items_candidates.append(manifest["ItemsUrl"])
    if lang:
        items_candidates.append(f"{slug}_{country}_items_{lang}.json")
    items_candidates.append(f"{slug}_{country}_items.json")
    for name in items_candidates:
        try:
            r = requests.get(TAKEAWAY_CDN + name, headers=headers, timeout=20)
            _log(f"items {name} -> {r.status_code}")
            if r.status_code == 200:
                items_data = r.json()
                break
        except Exception as e:
            _log(f"items {name} failed: {e}")
    if not items_data:
        if debug:
            st.session_state['takeaway_last_error'] = "Items file not found on CDN."
        return None

    # 3) Categories from all menus (delivery/pickup), dedupe by category Id
    categories, seen = [], set()
    for menu in manifest.get("Menus", []):
        for cat in menu.get("Categories", []):
            cid = cat.get("Id")
            if cid in seen:
                continue
            seen.add(cid)
            categories.append({"name": cat.get("Name", ""), "itemIds": cat.get("ItemIds", [])})

    country_code = (manifest.get("CountryCode") or country or "").lower()
    _log(f"Loaded {len(categories)} categories, {len(items_data.get('Items', []))} items, country={country_code}")
    return {"categories": categories, "items": items_data, "country_code": country_code}

def process_takeaway_data(raw, force_eur=False, debug=False):
    if not raw:
        return None
    categories = raw.get("categories", [])
    items_by_id = {it["Id"]: it for it in raw.get("items", {}).get("Items", [])}

    ordered_sections = []
    section_item_ids = {}
    for cat in categories:
        name = cat.get("name")
        if not name:
            continue
        ordered_sections.append(name)
        section_item_ids[name] = cat.get("itemIds", [])

    items_list = []
    seen = set()
    source_currency = TAKEAWAY_CURRENCY_MAP.get((raw.get("country_code") or "").lower(), "")
    output_currency = source_currency

    debug_shown = False

    for section in ordered_sections:
        for item_id in section_item_ids.get(section, []):
            if item_id in seen:
                continue
            item = items_by_id.get(item_id)
            if not item:
                continue
            seen.add(item_id)
            variations = item.get("Variations", [])
            if not variations:
                continue
            for var in variations:
                if debug and not debug_shown:
                    st.write("🔎 DEBUG raw variation:", dict(var))
                    debug_shown = True
                price = var.get("BasePrice", 0)
                if force_eur and source_currency in TAKEAWAY_FIXED_EUR_RATE:
                    price = convert_takeaway_price_to_eur(price, source_currency)
                    output_currency = "EUR"
                var_name = var.get("Name", "")
                item_name = item.get("Name", "")
                display_name = item_name if (not var_name or var_name == item_name) else f"{item_name} ({var_name})"
                img = ""
                img_sources = item.get("ImageSources", [])
                if img_sources:
                    img = img_sources[0].get("Path", "")
                    # Cloudinary path contains a {transformations} placeholder
                    img = img.replace("{transformations}", "w_960,c_limit,f_auto,q_auto")

                items_list.append({
                    "External_ID": str(uuid.uuid4()), "Product_Name": display_name,
                    "Collection": "MENU", "Section": section, "Price": price,
                    "Image_1": img, "Description": (item.get("Description") or "").strip(),
                    "Attribute_Groups": "", "Is_Alcoholic": "NO", "Is_Tobacco": "NO",
                    "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
                })

    return pd.DataFrame(items_list), pd.DataFrame(), pd.DataFrame(), ordered_sections, output_currency

# --- GEMINI AI FUNCTION ---
def extract_menu_with_gemini_core(content_to_send, api_keys_list, curr):
    if curr == "RSD":
        price_rule = "Prices must be whole numbers (integers) in RSD."
    else:
        price_rule = "Prices must be numbers (can contain decimal values) in EUR."

    prompt = f"""Analyze the attached content (images, PDF, or website text) and extract all items and prices.
    Return EXCLUSIVELY a JSON object with this exact structure:
    {{"sections": [{{"name": "Section Name", "items": [{{"name": "Item Name", "price": 100, "description": "Item description if available"}}]}}]}}
    Rules: {price_rule} If there is no description, leave it as an empty string. Return only raw JSON without markdown code blocks."""

    full_request = content_to_send + [prompt]
    last_error = None
    for idx, key in enumerate(api_keys_list):
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(full_request)
            clean_json = re.sub(r'```json|```', '', response.text).strip()
            return json.loads(clean_json)
        except Exception as e:
            last_error = e
            if idx < len(api_keys_list) - 1:
                st.warning(f"API Key {idx+1} reached its limit. Switching...")
                continue
            else:
                raise Exception(f"All API keys are blocked or exhausted. Last error: {last_error}")

# --- TABLE DATA GENERATION HELPERS ---
def build_dataframes_from_ai(menu_data, markup, fixed_amount, round_up, curr):
    items_list, ordered_sections = [], []
    for section in menu_data.get("sections", []):
        sec_name = section.get("name", "Other").strip()
        if sec_name not in ordered_sections: ordered_sections.append(sec_name)
        for item in section.get("items", []):
            p = apply_price_logic(item.get("price", 0), markup, fixed_amount, round_up, curr)
            items_list.append({
                "External_ID": str(uuid.uuid4()), "Product_Name": str(item.get("name", "")).strip(),
                "Collection": "MENU", "Section": sec_name, "Price": p,
                "Description": str(item.get("description", "")).strip(), "Image_1": "",
                "Attribute_Groups": "", "Is_Alcoholic": "NO", "Is_Tobacco": "NO",
                "SuperCollection": "", "Section_Order": 1, "Collection_Order": 1
            })
    df_p = pd.DataFrame(items_list)
    df_g = pd.DataFrame(columns=["External_ID", "Max", "Min", "Name", "Multiple_Selection", "Collapse_by_Default", "Attributes"])
    df_a = pd.DataFrame(columns=["External_ID", "Group_ID_Internal", "Name", "Price", "Enabled", "Selected_by_Default"])
    return df_p, df_g, df_a, ordered_sections

def build_excel(df_p, df_g, df_a):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df_p.to_excel(w, index=False, sheet_name='Products')
        df_g.to_excel(w, index=False, sheet_name='Attribute Groups')
        if not df_a.empty:
            cols_to_save = [c for c in df_a.columns if c != 'Group_ID_Internal']
            df_a[cols_to_save].to_excel(w, index=False, sheet_name='Attributes')
        else:
            df_a.to_excel(w, index=False, sheet_name='Attributes')
    return out.getvalue()

def render_menu_preview(df_p, df_g, df_a, ordered_sections, curr):
    for s in ordered_sections:
        prods = df_p[df_p['Section'] == s]
        if not prods.empty:
            st.markdown(f"**{s}**")
            for _, p in prods.iterrows():
                with st.expander(f"{p['Product_Name']} — {p['Price']} {curr}"):
                    if p['Description']: st.write(f"_{p['Description']}_")
                    if 'Attribute_Groups' in p and p['Attribute_Groups']:
                        g_ids = [gid for gid in str(p['Attribute_Groups']).split(",") if gid]
                        for gid in g_ids:
                            if not df_g.empty:
                                g_i = df_g[df_g['External_ID'] == gid]
                                if not g_i.empty:
                                    st.write(f"└ Option: {g_i.iloc[0]['Name']}")

# ============================================================
# UI TABS CONFIGURATION
# ============================================================
tab_wolt, tab_bolt, tab_takeaway, tab_photo, tab_link_ai, tab_edit = st.tabs(["🌐 Wolt Scraper", "🟢 Bolt Food Scraper", "🟠 Takeaway Scraper", "📄 Photo/PDF AI Menu", "🔗 Link AI Menu", "📈 Price Markup"])

# --- TAB 1: WOLT SCRAPER ---
with tab_wolt:
    st.info('💡 Paste the restaurant link: `https://wolt.com/en/srb/nis/restaurant/nn-chicken`', icon="ℹ️")
    link_input = st.text_input("Paste Wolt link:", placeholder="https://wolt.com/en/srb/nis/restaurant/...")

    if st.button("🚀 RUN", help="Extract structure, items, choices, and images from Wolt API"):
        match = re.search(r'/(?:restaurant|venue)/([^/]+)', link_input.strip())
        if match:
            slug = match.group(1)
            raw = fetch_data(slug)
            if raw:
                p, g, a, o_s, w_curr = process_all_data(raw, link_input.strip())
                st.session_state['w_df_p'], st.session_state['w_df_g'], st.session_state['w_df_a'] = p, g, a
                st.session_state['w_ordered_sections'], st.session_state['w_slug'] = o_s, slug
                st.success(f"✅ Loaded: {slug} ({w_curr})")
            else:
                st.error("Could not fetch data from Wolt API — check the link")
        else:
            st.error("Link format not recognized — must contain /restaurant/ or /venue/")

    if 'w_df_p' in st.session_state:
        with st.expander("👀 VIEW DATA TABLE"):
            st.dataframe(st.session_state['w_df_p'], height=600, use_container_width=True)

        st.markdown("### 📥 Download Output")
        col_ex, col_zip, _ = st.columns([1, 1.2, 4])
        with col_ex:
            excel_bytes = build_excel(st.session_state['w_df_p'], st.session_state['w_df_g'], st.session_state['w_df_a'])
            st.download_button("📊 DOWNLOAD EXCEL", excel_bytes, f"wolt_menu_{st.session_state['w_slug']}.xlsx")

        with col_zip:
            if st.button("🖼️ PREPARE IMAGES"):
                with st.spinner("Downloading images..."):
                    img_df = st.session_state['w_df_p'][st.session_state['w_df_p']['Image_1'] != ""]
                    z_io = io.BytesIO()
                    img_count = 0
                    tasks = [(r['Image_1'], r['Product_Name']) for _, r in img_df.iterrows()]
                    with zipfile.ZipFile(z_io, "w") as zf:
                        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                            future_to_img = {executor.submit(download_single_image, url, name): name for url, name in tasks}
                            for future in concurrent.futures.as_completed(future_to_img):
                                filename, content = future.result()
                                if filename and content:
                                    zf.writestr(filename, content)
                                    img_count += 1
                    st.session_state['zip_ready'] = z_io.getvalue()
                    st.session_state['zip_count'] = img_count

            if 'zip_ready' in st.session_state:
                st.download_button(f"🔥 DOWNLOAD ZIP ({st.session_state['zip_count']} images)", st.session_state['zip_ready'], f"images_{st.session_state['w_slug']}.zip")

# --- TAB: BOLT FOOD SCRAPER ---
with tab_bolt:
    st.info('💡 Paste: `https://food.bolt.eu/en/328-sofia/p/152105-kfc-garibaldi/`', icon="ℹ️")
    link_input_bolt = st.text_input("Paste Bolt Food link:", placeholder="https://food.bolt.eu/en/...")

    if st.button("🚀 RUN", key="bolt_run", help="Extract structure, items, and images from Bolt Food API"):
        match = re.search(r'/p/(\d+)-', link_input_bolt.strip())
        if match:
            provider_id = match.group(1)
            coords, city_name = guess_bolt_coords(link_input_bolt)
            if coords:
                use_lat, use_lng = coords
            else:
                st.warning("City not recognized — using default Sofia coordinates")
                use_lat, use_lng = 42.6977, 23.3219

            raw = fetch_bolt_data(provider_id, use_lat, use_lng)
            if raw and raw.get("code") == 0:
                result = process_bolt_data(raw)
                if result:
                    p, g, a, o_s, curr = result
                    st.session_state['b_df_p'], st.session_state['b_df_g'], st.session_state['b_df_a'] = p, g, a
                    st.session_state['b_ordered_sections'], st.session_state['b_slug'] = o_s, provider_id
                    st.success(f"✅ Loaded provider {provider_id} ({curr})")
                else:
                    st.error("Could not parse menu structure")
            else:
                st.error("Request failed — check the link")
        else:
            st.error("Link format not recognized — must contain '/p/<numbers>-'")

    if 'b_df_p' in st.session_state:
        with st.expander("👀 VIEW DATA TABLE"):
            st.dataframe(st.session_state['b_df_p'], height=600, use_container_width=True)

        st.markdown("### 📥 Download Output")
        col_ex, col_zip, _ = st.columns([1, 1.2, 4])
        with col_ex:
            excel_bytes = build_excel(st.session_state['b_df_p'], st.session_state['b_df_g'], st.session_state['b_df_a'])
            st.download_button("📊 DOWNLOAD EXCEL", excel_bytes, f"bolt_menu_{st.session_state['b_slug']}.xlsx", key="bolt_excel_dl")

        with col_zip:
            if st.button("🖼️ PREPARE IMAGES", key="bolt_img_btn"):
                with st.spinner("Downloading images..."):
                    img_df = st.session_state['b_df_p'][st.session_state['b_df_p']['Image_1'] != ""]
                    z_io = io.BytesIO()
                    img_count = 0
                    tasks = [(r['Image_1'], r['Product_Name']) for _, r in img_df.iterrows()]
                    with zipfile.ZipFile(z_io, "w") as zf:
                        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                            future_to_img = {executor.submit(download_single_image, url, name): name for url, name in tasks}
                            for future in concurrent.futures.as_completed(future_to_img):
                                filename, content = future.result()
                                if filename and content:
                                    zf.writestr(filename, content)
                                    img_count += 1
                    st.session_state['bolt_zip_ready'] = z_io.getvalue()
                    st.session_state['bolt_zip_count'] = img_count

            if 'bolt_zip_ready' in st.session_state:
                st.download_button(f"🔥 DOWNLOAD ZIP ({st.session_state['bolt_zip_count']} images)", st.session_state['bolt_zip_ready'], f"images_bolt_{st.session_state['b_slug']}.zip", key="bolt_zip_dl")

# --- TAB: TAKEAWAY SCRAPER ---
with tab_takeaway:
    st.info('💡 Paste: `https://www.takeaway.com/bg/menu/leo-s-pizza-n-trattoria`', icon="ℹ️")
    link_input_takeaway = st.text_input("Paste Takeaway.com link:", placeholder="https://www.takeaway.com/...")
    col_dbg, col_eur = st.columns(2)
    with col_dbg:
        debug_takeaway = st.checkbox("Show debug info", key="takeaway_debug")
    with col_eur:
        force_eur_takeaway = st.checkbox("Convert to EUR (e.g. Bulgaria)", key="takeaway_force_eur", value=True)

    if st.button("🚀 RUN", key="takeaway_run", help="Extract structure and items directly from the Takeaway menu CDN"):
        if link_input_takeaway.strip():
            raw = fetch_takeaway_data(link_input_takeaway.strip(), debug=debug_takeaway)
            if raw:
                result = process_takeaway_data(raw, force_eur=force_eur_takeaway, debug=debug_takeaway)
                if result and not result[0].empty:
                    p, g, a, o_s, curr = result
                    st.session_state['t_df_p'], st.session_state['t_df_g'], st.session_state['t_df_a'] = p, g, a
                    st.session_state['t_ordered_sections'] = o_s
                    slug_match = re.search(r'/menu/([^/?]+)', link_input_takeaway.strip())
                    st.session_state['t_slug'] = slug_match.group(1) if slug_match else "restaurant"
                    st.success(f"✅ Loaded ({curr})")
                else:
                    st.error("Could not parse menu items")
            else:
                err_detail = st.session_state.get('takeaway_last_error', '')
                if err_detail:
                    st.error(f"Error: {err_detail}")
                else:
                    st.error("Could not fetch menu — check link. Enable 'Show debug info' for details")
        else:
            st.error("Paste a link first")

    if 't_df_p' in st.session_state:
        with st.expander("👀 VIEW DATA TABLE"):
            st.dataframe(st.session_state['t_df_p'], height=600, use_container_width=True)

        st.markdown("### 📥 Download Output")
        col_ex, col_zip, _ = st.columns([1, 1.2, 4])
        with col_ex:
            excel_bytes = build_excel(st.session_state['t_df_p'], st.session_state['t_df_g'], st.session_state['t_df_a'])
            st.download_button("📊 DOWNLOAD EXCEL", excel_bytes, f"takeaway_menu_{st.session_state['t_slug']}.xlsx", key="takeaway_excel_dl")

        with col_zip:
            if st.button("🖼️ PREPARE IMAGES", key="takeaway_img_btn"):
                with st.spinner("Downloading images..."):
                    img_df = st.session_state['t_df_p'][st.session_state['t_df_p']['Image_1'] != ""]
                    z_io = io.BytesIO()
                    img_count = 0
                    tasks = [(r['Image_1'], r['Product_Name']) for _, r in img_df.iterrows()]
                    with zipfile.ZipFile(z_io, "w") as zf:
                        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                            future_to_img = {executor.submit(download_single_image, url, name): name for url, name in tasks}
                            for future in concurrent.futures.as_completed(future_to_img):
                                filename, content = future.result()
                                if filename and content:
                                    zf.writestr(filename, content)
                                    img_count += 1
                    st.session_state['takeaway_zip_ready'] = z_io.getvalue()
                    st.session_state['takeaway_zip_count'] = img_count

            if 'takeaway_zip_ready' in st.session_state:
                st.download_button(f"🔥 DOWNLOAD ZIP ({st.session_state['takeaway_zip_count']} images)", st.session_state['takeaway_zip_ready'], f"images_takeaway_{st.session_state['t_slug']}.zip", key="takeaway_zip_dl")

# --- TAB 2: PHOTO/PDF AI ---
with tab_photo:
    st.subheader("AI Image & PDF Menu Analysis")

    st.markdown("**API Key Setup:**")
    st.markdown("• Uses Gemini API keys from `config.json` (comma-separated)")
    st.markdown("• If not configured, input your key below:")

    active_keys = GEMINI_KEYS_LIST if GEMINI_KEYS_LIST else [st.text_input("Your API Key:", type="password")]

    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1: rest_name_p = st.text_input("Restaurant Name:", key="rest_p")
    with col2: markup_p = st.number_input("Markup %:", min_value=0, value=0, step=5, key="mark_p")
    with col3: fixed_p = st.number_input("Fixed Add-on (RSD):", min_value=0.0, value=0.0, step=10.0, key="fix_p")
    with col4:
        st.write("")
        round_p = st.checkbox("Round to 10", value=False, key="round_p_1")

    files = st.file_uploader("Upload Images/PDF:", type=["jpg","jpeg","png","webp","pdf"], accept_multiple_files=True)

    if st.button("🤖 ANALYZE FILES", type="primary"):
        if files and active_keys:
            with st.spinner("AI is reading..."):
                try:
                    content = []
                    for f in files:
                        d = f.read(); f.seek(0)
                        content.append({"mime_type": f.type, "data": d})
                    res = extract_menu_with_gemini_core(content, active_keys, "RSD")
                    st.session_state['ai_res_photo'] = res
                    st.session_state['ai_name_photo'] = rest_name_p if rest_name_p else "Menu"
                except Exception as e: st.error(str(e))

    if 'ai_res_photo' in st.session_state:
        df_p, df_g, df_a, sects = build_dataframes_from_ai(st.session_state['ai_res_photo'], markup_p, fixed_p, round_p, "RSD")
        with st.expander("👀 VIEW DATA TABLE"):
            st.dataframe(df_p, height=600, use_container_width=True)

        st.download_button("📊 DOWNLOAD EXCEL", build_excel(df_p, df_g, df_a), f"menu_{st.session_state['ai_name_photo']}.xlsx")

# --- TAB 3: LINK AI ---
with tab_link_ai:
    st.subheader("AI Website Analysis (Jina Reader)")
    link_input_ai = st.text_input("Enter website link:", placeholder="https://www.restaurant.com/menu/")

    col_l1, col_l2, col_l3, col_l4 = st.columns([2, 1, 1, 1])
    with col_l1: rest_name_l = st.text_input("Restaurant Name:", key="rest_l")
    with col_l2: markup_l = st.number_input("Markup %:", min_value=0, value=0, step=5, key="mark_l")
    with col_l3: fixed_l = st.number_input("Fixed Add-on (RSD):", min_value=0.0, value=0.0, step=10.0, key="fix_l")
    with col_l4:
        st.write("")
        round_l = st.checkbox("Round to 10", value=False, key="round_l_2")

    if st.button("🌐 ANALYZE LINK", type="primary"):
        if link_input_ai and GEMINI_KEYS_LIST:
            with st.spinner("Reading website..."):
                try:
                    jina_url = f"https://r.jina.ai/{link_input_ai}"
                    r = requests.get(jina_url, headers={"Accept": "application/json"}, timeout=45)
                    if r.status_code == 200:
                        text_only = r.json().get("data", {}).get("content", "")
                        content = [f"Extract the complete menu:\n\n {text_only[:35000]}"]
                        res = extract_menu_with_gemini_core(content, GEMINI_KEYS_LIST, "RSD")
                        st.session_state['ai_res_link'] = res
                        st.session_state['ai_name_link'] = rest_name_l if rest_name_l else "Link_Menu"
                except Exception as e: st.error(f"Error: {e}")
        else:
            st.error("Need link and configured API keys")

    if 'ai_res_link' in st.session_state:
        df_l, df_gl, df_al, sects_l = build_dataframes_from_ai(st.session_state['ai_res_link'], markup_l, fixed_l, round_l, "RSD")
        with st.expander("👀 VIEW DATA TABLE"):
            st.dataframe(df_l, height=600, use_container_width=True)

        st.download_button("📊 DOWNLOAD EXCEL", build_excel(df_l, df_gl, df_al), f"menu_{st.session_state['ai_name_link']}_link.xlsx")

# --- TAB 4: PRICE MARKUP ENGINE ---
with tab_edit:
    st.subheader("📈 Bulk Price Increase in Excel")
    uploaded_edit_file = st.file_uploader("Upload Excel file (.xlsx):", type=["xlsx"], key="edit_uploader")

    if uploaded_edit_file:
        try:
            sheets = pd.read_excel(uploaded_edit_file, sheet_name=None)
            df_p_edit = sheets.get('Products', pd.DataFrame())
            df_g_edit = sheets.get('Attribute Groups', pd.DataFrame())
            df_a_edit = sheets.get('Attributes', pd.DataFrame())

            with st.expander("👀 VIEW UPLOADED TABLE"):
                st.dataframe(df_p_edit, height=600, use_container_width=True)

            st.markdown("---")
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                st.markdown("### 🍔 Main Dishes (Products)")
                mark_p_edit = st.number_input("Products: Markup %:", min_value=0, value=0, step=5, key="mpe")
                fix_p_edit = st.number_input("Products: Fixed Add-on (RSD):", min_value=0.0, value=0.0, step=10.0, key="fpe")
            with col_e2:
                st.markdown("### 🧩 Modifiers (Attributes)")
                mark_a_edit = st.number_input("Attributes: Markup %:", min_value=0, value=0, step=5, key="mae")
                fix_a_edit = st.number_input("Attributes: Fixed Add-on (RSD):", min_value=0.0, value=0.0, step=10.0, key="fae")

            round_edit = st.checkbox("Round new prices to 10 (RSD)", value=False, key="re")

            if st.button("🔄 RECALCULATE", type="primary"):
                res_p = df_p_edit.copy()
                res_a = df_a_edit.copy()
                if not res_p.empty and 'Price' in res_p.columns:
                    res_p['Price'] = res_p['Price'].apply(lambda x: apply_price_logic(x, mark_p_edit, fix_p_edit, round_edit, "RSD"))
                if not res_a.empty and 'Price' in res_a.columns:
                    res_a['Price'] = res_a['Price'].apply(lambda x: apply_price_logic(x, mark_a_edit, fix_a_edit, round_edit, "RSD"))

                st.session_state['edited_excel'] = build_excel(res_p, df_g_edit, res_a)
                st.session_state['edited_df_p'] = res_p
                st.success("✅ Prices recalculated!")

            if 'edited_excel' in st.session_state and 'edited_df_p' in st.session_state:
                with st.expander("👀 VIEW NEW PRICES", expanded=True):
                    st.dataframe(st.session_state['edited_df_p'], height=600, use_container_width=True)

                st.download_button("📥 DOWNLOAD UPDATED EXCEL", st.session_state['edited_excel'], "updated_price_list.xlsx")

        except Exception as e:
            st.error(f"Error: {e}")
