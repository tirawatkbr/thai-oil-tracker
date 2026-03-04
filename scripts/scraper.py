
"""
Thai Oil Price Scraper
======================
ดึงราคาน้ำมันจาก api.chnwt.dev/thai-oil-api (primary)
แล้วบันทึกลง Google Sheets + prices.json / price_history.json
"""

import os, json, time, logging
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

TZ        = ZoneInfo("Asia/Bangkok")
TODAY     = datetime.now(TZ).strftime("%Y-%m-%d")
TIMESTAMP = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

SHEET_NAME  = os.environ.get("GOOGLE_SHEET_NAME", "Thai Oil Prices")
PRICES_JSON = "prices.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Oil types ────────────────────────────────────────────────────────────────
OIL_TYPES = [
    "g95", "g91", "e20", "e85", "benzene95", "ngv",
    "diesel_b7", "diesel", "diesel_premium",
    "g95_premium", "g97_premium", "super_power_g95",
    "shell_v_g95", "shell_v_diesel", "shell_fuelsave",
]

OIL_LABEL_TH = {
    "g95":             "แก๊สโซฮอล์ 95",
    "g91":             "แก๊สโซฮอล์ 91",
    "e20":             "แก๊สโซฮอล์ E20",
    "e85":             "แก๊สโซฮอล์ E85",
    "benzene95":       "เบนซิน 95",
    "ngv":             "แก๊ส NGV",
    "diesel_b7":       "ดีเซล B7",
    "diesel":          "ดีเซล",
    "diesel_premium":  "ดีเซลพรีเมียม",
    "g95_premium":     "แก๊สโซฮอล์ 95 พรีเมียม",
    "g97_premium":     "แก๊สโซฮอล์ 97 พรีเมียม",
    "super_power_g95": "ซูเปอร์พาวเวอร์ แก๊สโซฮอล์ 95",
    "shell_v_g95":     "เชลล์ วี-เพาเวอร์ แก๊สโซฮอล์ 95",
    "shell_v_diesel":  "เชลล์ วี-เพาเวอร์ ดีเซล",
    "shell_fuelsave":  "เชลล์ ฟิวเซฟ ดีเซล",
}

BRANDS = ["PTT", "Shell", "Caltex", "Esso", "BCP", "PT", "Susco"]

BRAND_OILS = {
    "PTT":    ["g95","g91","e20","e85","benzene95","ngv","diesel_b7","diesel","diesel_premium","super_power_g95","g95_premium"],
    "BCP":    ["g95","g91","e20","e85","diesel_b7","diesel_premium","g95_premium","g97_premium"],
    "Shell":  ["g95","g91","e20","diesel_b7","diesel_premium","shell_v_g95","shell_fuelsave","shell_v_diesel","g95_premium"],
    "Caltex": ["g95","g91","e20","e85","benzene95","diesel_b7","diesel_premium","g95_premium"],
    "PT":     ["g95","g91","e20","e85","benzene95","diesel_b7","g95_premium"],
    "Susco":  ["g95","g91","e20","benzene95","ngv","diesel_b7"],
    "Esso":   ["g95","g91","e20","diesel_b7","diesel_premium"],
}

# ── Name matching ─────────────────────────────────────────────────────────────
def oil_name_to_id(name: str) -> str | None:
    n = name.lower().strip()

    # Exact map
    exact = {
        "แก๊สโซฮอล์ 95": "g95", "gasohol 95": "g95", "e10 95": "g95",
        "แก๊สโซฮอล์ 91": "g91", "gasohol 91": "g91", "e10 91": "g91",
        "แก๊สโซฮอล์ e20": "e20", "e20": "e20", "gasohol e20": "e20",
        "แก๊สโซฮอล์ e85": "e85", "e85": "e85", "gasohol e85": "e85",
        "เบนซิน 95": "benzene95", "benzene 95": "benzene95", "เบนซิน": "benzene95",
        "แก๊ส ngv": "ngv", "ngv": "ngv",
        "ดีเซล b7": "diesel_b7", "diesel b7": "diesel_b7", "b7": "diesel_b7",
        "ดีเซลหมุนเร็ว b7": "diesel_b7",
        "ดีเซล": "diesel", "diesel": "diesel",
        "ดีเซลพรีเมียม": "diesel_premium", "diesel premium": "diesel_premium",
        "hi diesel": "diesel_premium", "ไฮดีเซล": "diesel_premium",
        "แก๊สโซฮอล์ 95 พรีเมียม": "g95_premium",
        "แก๊สโซฮอล์ 97 พรีเมียม": "g97_premium", "พรีเมียม 97": "g97_premium",
        "ซูเปอร์พาวเวอร์ แก๊สโซฮอล์ 95": "super_power_g95",
        "เชลล์ วี-เพาเวอร์ แก๊สโซฮอล์ 95": "shell_v_g95",
        "เชลล์ วี-เพาเวอร์ ดีเซล": "shell_v_diesel",
        "เชลล์ ฟิวเซฟ ดีเซล": "shell_fuelsave",
    }
    if n in exact:
        return exact[n]

    # Keyword fallback — ลำดับสำคัญมาก (specific ก่อน general)
    if "super" in n or "ซูเปอร์" in n:                                  return "super_power_g95"
    if "v-power" in n and ("diesel" in n or "ดีเซล" in n):              return "shell_v_diesel"
    if "v-power" in n:                                                   return "shell_v_g95"
    if "fuelsave" in n or "ฟิวเซฟ" in n:                                return "shell_fuelsave"
    if "97" in n and ("พรีเมียม" in n or "premium" in n):               return "g97_premium"
    if "95" in n and ("พรีเมียม" in n or "premium" in n):               return "g95_premium"
    if ("diesel" in n or "ดีเซล" in n) and ("พรีเมียม" in n or "premium" in n or "hi" in n): return "diesel_premium"
    if "b7" in n:                                                        return "diesel_b7"
    if "diesel" in n or "ดีเซล" in n:                                   return "diesel"
    if "ngv" in n:                                                       return "ngv"
    if "เบนซิน" in n or "benzene" in n:                                 return "benzene95"
    if "e85" in n:                                                       return "e85"
    if "e20" in n:                                                       return "e20"
    if "91" in n:                                                        return "g91"
    if "95" in n:                                                        return "g95"
    return None


def normalize_brand(name: str) -> str | None:
    n = name.lower().strip()
    for key, val in {
        "ptt": "PTT", "ปตท": "PTT",
        "shell": "Shell", "เชลล์": "Shell",
        "caltex": "Caltex", "คาลเท็กซ์": "Caltex", "chevron": "Caltex",
        "esso": "Esso", "เอสโซ่": "Esso",
        "bcp": "BCP", "บางจาก": "BCP", "bangchak": "BCP",
        "pt energy": "PT", "ptg": "PT", "พีที": "PT",
        "susco": "Susco", "ซัสโก้": "Susco",
    }.items():
        if key in n:
            return val
    # "pt" ต้องเช็คท้ายสุดเพื่อไม่ให้ชน "ptt"
    if n == "pt":
        return "PT"
    return None


# ── Source 1: thai-oil-api ────────────────────────────────────────────────────
# API key map: ชื่อ key ใน API → oil_id ของเรา
API_OIL_KEY_MAP = {
    "gasoline_95":      "benzene95",
    "gasohol_95":       "g95",
    "gasohol_91":       "g91",
    "gasohol_e20":      "e20",
    "gasohol_e85":      "e85",
    "ngv":              "ngv",
    "diesel_b7":        "diesel_b7",
    "diesel":           "diesel",
    "diesel_premium":   "diesel_premium",
    "gasohol_95_premium":    "g95_premium",
    "gasohol_97_premium":    "g97_premium",
    "super_power_gasohol_95":"super_power_g95",
    "v_power_gasohol_95":    "shell_v_g95",
    "v_power_diesel":        "shell_v_diesel",
    "fuelsave_diesel":       "shell_fuelsave",
    # ชื่อสั้น/variant
    "gasohol95":        "g95",
    "gasohol91":        "g91",
    "e20":              "e20",
    "e85":              "e85",
    "b7":               "diesel_b7",
    "premium_diesel":   "diesel_premium",
    "hi_diesel":        "diesel_premium",
}

# API brand key map
API_BRAND_KEY_MAP = {
    "ptt":     "PTT",
    "shell":   "Shell",
    "caltex":  "Caltex",
    "esso":    "Esso",
    "bcp":     "BCP",
    "bangchak":"BCP",
    "pt":      "PT",
    "susco":   "Susco",
}


def fetch_from_thai_oil_api() -> dict | None:
    url = "https://api.chnwt.dev/thai-oil-api/latest"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()

        # โครงสร้างจริง: data["response"]["stations"][brand_key][oil_key]["price"]
        response = data.get("response", {})
        stations = response.get("stations", {})

        if not stations:
            log.warning("  ⚠️  ไม่พบ stations ใน response")
            log.info(f"  [API] keys: {list(data.keys())}, response keys: {list(response.keys())}")
            return None

        log.info(f"  [API] station keys: {list(stations.keys())}")

        prices = {}
        for brand_key, oil_dict in stations.items():
            brand = API_BRAND_KEY_MAP.get(brand_key.lower())
            if not brand:
                log.warning(f"  ⚠️  brand key ไม่รู้จัก: '{brand_key}'")
                continue

            if not isinstance(oil_dict, dict):
                continue

            for oil_key, oil_data in oil_dict.items():
                oil_id = API_OIL_KEY_MAP.get(oil_key.lower())
                if not oil_id:
                    # ลอง flexible match
                    oil_id = oil_name_to_id(oil_key.replace("_"," "))
                if not oil_id:
                    log.warning(f"  ⚠️  oil key ไม่รู้จัก: '{oil_key}'")
                    continue

                # price อาจอยู่ใน {"name":..,"price":..} หรือเป็น float ตรงๆ
                if isinstance(oil_data, dict):
                    price_val = oil_data.get("price") or oil_data.get("value")
                else:
                    price_val = oil_data

                try:
                    p = float(str(price_val).replace(",",""))
                    if oil_id not in prices:
                        prices[oil_id] = {}
                    prices[oil_id][brand] = p
                except (ValueError, TypeError):
                    pass

        log.info(f"✅ thai-oil-api: {len(prices)} ประเภท, ตัวอย่าง: { {k:list(v.keys()) for k,v in list(prices.items())[:3]} }")
        return prices if prices else None
    except Exception as e:
        log.warning(f"⚠️  thai-oil-api ล้มเหลว: {e}")
        return None


# ── Source 2: Kapook ──────────────────────────────────────────────────────────
def fetch_from_kapook() -> dict | None:
    url = "https://gasprice.kapook.com/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        prices = {}
        for section in soup.select(".price-box, .brand-box, [class*='brand']"):
            brand_el = section.select_one(".brand-name, h2, h3")
            if not brand_el:
                continue
            brand = normalize_brand(brand_el.get_text(strip=True))
            if not brand:
                continue
            for row in section.select("tr, .price-row, li"):
                cells = row.select("td, .oil-name, .price")
                if len(cells) < 2:
                    continue
                oil_id = oil_name_to_id(cells[0].get_text(strip=True))
                if not oil_id:
                    continue
                try:
                    p = float(cells[-1].get_text(strip=True).replace(",",""))
                    prices.setdefault(oil_id, {})[brand] = p
                except ValueError:
                    pass
        log.info(f"✅ Kapook: {len(prices)} ประเภท")
        return prices if prices else None
    except Exception as e:
        log.warning(f"⚠️  Kapook ล้มเหลว: {e}")
        return None


# ── Source 3: DOEB ────────────────────────────────────────────────────────────
def fetch_from_doeb() -> dict | None:
    url = "https://www2.doeb.go.th/price/oilprice.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        prices = {}
        for table in soup.find_all("table"):
            headers_row = table.find("tr")
            if not headers_row:
                continue
            col_headers = [th.get_text(strip=True) for th in headers_row.find_all(["th","td"])]
            for row in table.find_all("tr")[1:]:
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if not cols:
                    continue
                oil_id = oil_name_to_id(cols[0])
                if not oil_id:
                    continue
                for i, brand_raw in enumerate(col_headers[1:], start=1):
                    brand = normalize_brand(brand_raw)
                    if brand and i < len(cols):
                        try:
                            prices.setdefault(oil_id, {})[brand] = float(cols[i].replace(",",""))
                        except ValueError:
                            pass
        log.info(f"✅ DOEB: {len(prices)} ประเภท")
        return prices if prices else None
    except Exception as e:
        log.warning(f"⚠️  DOEB ล้มเหลว: {e}")
        return None


# ── Orchestrate ───────────────────────────────────────────────────────────────
def get_oil_prices() -> dict:
    log.info("🔍 เริ่มดึงราคาน้ำมัน...")
    for label, fn in [
        ("thai-oil-api", fetch_from_thai_oil_api),
        ("Kapook",       fetch_from_kapook),
        ("DOEB",         fetch_from_doeb),
    ]:
        data = fn()
        if data and any(data.values()):
            log.info(f"✅ ใช้ข้อมูลจาก: {label}")
            return data
    log.error("❌ ดึงข้อมูลล้มเหลวทุกแหล่ง")
    return {}


def filter_prices_by_brand_oils(prices: dict) -> dict:
    filtered = {}
    for oil_id in OIL_TYPES:
        filtered[oil_id] = {}
        for brand in BRANDS:
            if oil_id in BRAND_OILS.get(brand, []):
                p = prices.get(oil_id, {}).get(brand)
                if p is not None:
                    filtered[oil_id][brand] = p
    return filtered


# ── Save JSON ─────────────────────────────────────────────────────────────────
def save_prices_json(prices: dict):
    output = {"updated": TIMESTAMP, "date": TODAY, "prices": prices}
    history_file = "price_history.json"
    history = {}
    if os.path.exists(history_file):
        with open(history_file, encoding="utf-8") as f:
            try:
                history = json.load(f)
            except Exception:
                history = {}
    history[TODAY] = prices
    sorted_keys = sorted(history.keys())[-90:]
    history = {k: history[k] for k in sorted_keys}
    with open(PRICES_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    log.info(f"✅ บันทึก {PRICES_JSON} และ {history_file}")


# ── Google Sheets ─────────────────────────────────────────────────────────────
def get_gsheet_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("ไม่พบ GOOGLE_CREDENTIALS_JSON")
    creds_dict = json.loads(creds_json)
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def update_google_sheets(prices: dict):
    log.info("📊 กำลังอัปเดต Google Sheets...")
    try:
        gc = get_gsheet_client()
        try:
            sh = gc.open(SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            log.info(f"📋 สร้าง Spreadsheet ใหม่: {SHEET_NAME}")
            sh = gc.create(SHEET_NAME)
            sh.share(None, perm_type="anyone", role="reader")

        try:
            ws = sh.worksheet("ราคาล่าสุด")
            ws.clear()
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet("ราคาล่าสุด", rows=50, cols=20)

        header = ["ประเภทน้ำมัน"] + BRANDS + ["อัปเดต"]
        rows = [header]
        for oil_id in OIL_TYPES:
            row = [OIL_LABEL_TH[oil_id]]
            for brand in BRANDS:
                row.append(prices.get(oil_id, {}).get(brand, "-"))
            row.append(TIMESTAMP)
            rows.append(row)
        ws.update("A1", rows)
        format_header(ws, len(header))
        log.info("  ✅ Sheet 'ราคาล่าสุด' อัปเดตแล้ว")

        for oil_id in OIL_TYPES:
            sheet_name = f"ประวัติ-{OIL_LABEL_TH[oil_id][:15]}"
            try:
                ws_h = sh.worksheet(sheet_name)
            except gspread.WorksheetNotFound:
                ws_h = sh.add_worksheet(sheet_name, rows=500, cols=15)
                ws_h.update("A1", [["วันที่"] + BRANDS])
                format_header(ws_h, len(BRANDS) + 1)
            existing = ws_h.col_values(1)
            if TODAY in existing:
                log.info(f"  ⏭️  {sheet_name}: มีข้อมูลวันนี้แล้ว")
                continue
            new_row = [TODAY] + [prices.get(oil_id, {}).get(b, "") for b in BRANDS]
            ws_h.append_row(new_row)
            log.info(f"  ✅ {sheet_name}: เพิ่ม {TODAY}")
            time.sleep(1)

        log.info("✅ Google Sheets อัปเดตครบ")
    except Exception as e:
        log.error(f"❌ Google Sheets error: {e}")
        raise


def format_header(ws, col_count: int):
    try:
        ws.format(
            f"A1:{chr(64 + min(col_count, 26))}1",
            {"backgroundColor": {"red": 0.13, "green": 0.17, "blue": 0.28},
             "textFormat": {"foregroundColor": {"red": 0.9, "green": 0.75, "blue": 0.2},
                            "bold": True, "fontSize": 11},
             "horizontalAlignment": "CENTER"},
        )
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 50)
    log.info(f"🚀 Thai Oil Price Scraper — {TIMESTAMP}")
    log.info("=" * 50)

    raw_prices = get_oil_prices()
    if not raw_prices:
        log.error("❌ ไม่มีข้อมูลราคา")
        raise SystemExit(1)

    prices = filter_prices_by_brand_oils(raw_prices)

    log.info("\n📋 ราคาน้ำมันวันนี้:")
    for oil_id, bp in prices.items():
        if bp:
            log.info(f"  {OIL_LABEL_TH[oil_id]}: {dict(list(bp.items())[:3])}")

    save_prices_json(prices)

    if os.environ.get("GOOGLE_CREDENTIALS_JSON"):
        update_google_sheets(prices)
    else:
        log.warning("⚠️  ไม่พบ GOOGLE_CREDENTIALS_JSON — ข้าม Sheets")

    log.info("\n🎉 เสร็จสิ้น!")


if __name__ == "__main__":
    main()
