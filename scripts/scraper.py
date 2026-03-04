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

# ── Timezone & timestamps ────────────────────────────────────────────────────
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

# ── Oil types (ตรงกับ UI) ────────────────────────────────────────────────────
OIL_TYPES = [
    "g95", "g91", "e20", "e85", "benzene95", "ngv",
    "diesel_b7", "diesel", "diesel_premium",
    "g95_premium", "g97_premium", "super_power_g95",
    "shell_v_g95", "shell_v_diesel", "shell_fuelsave",
]

OIL_LABEL_TH = {
    "g95":            "แก๊สโซฮอล์ 95",
    "g91":            "แก๊สโซฮอล์ 91",
    "e20":            "แก๊สโซฮอล์ E20",
    "e85":            "แก๊สโซฮอล์ E85",
    "benzene95":      "เบนซิน 95",
    "ngv":            "แก๊ส NGV",
    "diesel_b7":      "ดีเซล B7",
    "diesel":         "ดีเซล",
    "diesel_premium": "ดีเซลพรีเมียม",
    "g95_premium":    "แก๊สโซฮอล์ 95 พรีเมียม",
    "g97_premium":    "แก๊สโซฮอล์ 97 พรีเมียม",
    "super_power_g95":"ซูเปอร์พาวเวอร์ แก๊สโซฮอล์ 95",
    "shell_v_g95":    "เชลล์ วี-เพาเวอร์ แก๊สโซฮอล์ 95",
    "shell_v_diesel": "เชลล์ วี-เพาเวอร์ ดีเซล",
    "shell_fuelsave": "เชลล์ ฟิวเซฟ ดีเซล",
}

# ── Brands (ตรงกับ UI) ──────────────────────────────────────────────────────
BRANDS = ["PTT", "Shell", "Caltex", "Esso", "BCP", "PT", "Susco"]

# น้ำมันที่แต่ละแบรนด์จำหน่ายจริง (ตรงกับ UI)
BRAND_OILS = {
    "PTT":    ["g95","g91","e20","e85","benzene95","ngv","diesel_b7","diesel","diesel_premium","super_power_g95","g95_premium"],
    "BCP":    ["g95","g91","e20","e85","diesel_b7","diesel_premium","g95_premium","g97_premium"],
    "Shell":  ["g95","g91","e20","diesel_b7","diesel_premium","shell_v_g95","shell_fuelsave","shell_v_diesel","g95_premium"],
    "Caltex": ["g95","g91","e20","e85","benzene95","diesel_b7","diesel_premium","g95_premium"],
    "PT":     ["g95","g91","e20","e85","benzene95","diesel_b7","g95_premium"],
    "Susco":  ["g95","g91","e20","benzene95","ngv","diesel_b7"],
    "Esso":   ["g95","g91","e20","diesel_b7","diesel_premium"],
}

# ── Name → ID mapping (ครอบคลุมทุกชื่อที่ API ส่งมา) ────────────────────────
NAME_TO_ID = {
    # G95
    "แก๊สโซฮอล์ 95": "g95",
    "gasohol 95": "g95",
    "e10 95": "g95",
    "gasohol95": "g95",
    # G91
    "แก๊สโซฮอล์ 91": "g91",
    "gasohol 91": "g91",
    "e10 91": "g91",
    "gasohol91": "g91",
    # E20
    "แก๊สโซฮอล์ e20": "e20",
    "e20": "e20",
    "gasohol e20": "e20",
    # E85
    "แก๊สโซฮอล์ e85": "e85",
    "e85": "e85",
    "gasohol e85": "e85",
    # Benzene
    "เบนซิน 95": "benzene95",
    "benzene 95": "benzene95",
    "เบนซิน": "benzene95",
    "benzene": "benzene95",
    "เบนซิน95": "benzene95",
    # NGV
    "แก๊ส ngv": "ngv",
    "ngv": "ngv",
    "ก๊าซ ngv": "ngv",
    # Diesel B7
    "ดีเซล b7": "diesel_b7",
    "diesel b7": "diesel_b7",
    "b7": "diesel_b7",
    "ดีเซลหมุนเร็ว b7": "diesel_b7",
    # Diesel plain
    "ดีเซล": "diesel",
    "diesel": "diesel",
    "ดีเซลหมุนเร็ว": "diesel",
    # Diesel premium
    "ดีเซลพรีเมียม": "diesel_premium",
    "diesel premium": "diesel_premium",
    "hi diesel": "diesel_premium",
    "ไฮดีเซล": "diesel_premium",
    # G95 premium
    "แก๊สโซฮอล์ 95 พรีเมียม": "g95_premium",
    "gasohol 95 premium": "g95_premium",
    "พรีเมียม 95": "g95_premium",
    # G97 premium
    "แก๊สโซฮอล์ 97 พรีเมียม": "g97_premium",
    "gasohol 97 premium": "g97_premium",
    "พรีเมียม 97": "g97_premium",
    "premium 97": "g97_premium",
    # Super power
    "ซูเปอร์พาวเวอร์ แก๊สโซฮอล์ 95": "super_power_g95",
    "super power gasohol 95": "super_power_g95",
    # Shell specials
    "เชลล์ วี-เพาเวอร์ แก๊สโซฮอล์ 95": "shell_v_g95",
    "shell v-power gasohol 95": "shell_v_g95",
    "เชลล์ วี-เพาเวอร์ ดีเซล": "shell_v_diesel",
    "shell v-power diesel": "shell_v_diesel",
    "เชลล์ ฟิวเซฟ ดีเซล": "shell_fuelsave",
    "shell fuelsave diesel": "shell_fuelsave",
}

BRAND_NORMALIZE = {
    "ptt": "PTT", "ปตท": "PTT", "ปตท.": "PTT",
    "shell": "Shell", "เชลล์": "Shell",
    "caltex": "Caltex", "คาลเท็กซ์": "Caltex",
    "esso": "Esso", "เอสโซ่": "Esso",
    "bcp": "BCP", "บางจาก": "BCP", "bangchak": "BCP",
    "pt": "PT", "พีที": "PT", "ptg": "PT",
    "susco": "Susco", "ซัสโก้": "Susco",
}


def oil_name_to_id(name: str) -> str | None:
    return NAME_TO_ID.get(name.lower().strip())


def normalize_brand(name: str) -> str | None:
    return BRAND_NORMALIZE.get(name.lower().strip())


# ── Source 1: thai-oil-api (Primary) ────────────────────────────────────────
def fetch_from_thai_oil_api() -> dict | None:
    url = "https://api.chnwt.dev/thai-oil-api/latest"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        prices = {}
        for item in data.get("result", {}).get("price", []):
            name    = item.get("name", "")
            oil_id  = oil_name_to_id(name)
            if not oil_id:
                continue
            prices[oil_id] = {}
            for brand_raw, price_str in item.get("price", {}).items():
                brand = normalize_brand(brand_raw) or brand_raw
                if brand in BRANDS:
                    try:
                        prices[oil_id][brand] = float(price_str)
                    except (ValueError, TypeError):
                        pass
        log.info(f"✅ thai-oil-api: {len(prices)} ประเภท")
        return prices if prices else None
    except Exception as e:
        log.warning(f"⚠️  thai-oil-api ล้มเหลว: {e}")
        return None


# ── Source 2: gasprice.kapook.com (Fallback) ─────────────────────────────────
def fetch_from_kapook() -> dict | None:
    url = "https://gasprice.kapook.com/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        prices = {}

        # โครงสร้าง: แต่ละปั๊มมี section ของตัวเอง
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
                    p = float(cells[-1].get_text(strip=True).replace(",", ""))
                    if oil_id not in prices:
                        prices[oil_id] = {}
                    prices[oil_id][brand] = p
                except ValueError:
                    pass

        log.info(f"✅ Kapook: {len(prices)} ประเภท")
        return prices if prices else None
    except Exception as e:
        log.warning(f"⚠️  Kapook ล้มเหลว: {e}")
        return None


# ── Source 3: DOEB (Fallback) ────────────────────────────────────────────────
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
            cols_headers = [th.get_text(strip=True) for th in headers_row.find_all(["th","td"])]

            for row in table.find_all("tr")[1:]:
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if not cols:
                    continue
                oil_id = oil_name_to_id(cols[0])
                if not oil_id:
                    continue
                if oil_id not in prices:
                    prices[oil_id] = {}
                for i, brand_raw in enumerate(cols_headers[1:], start=1):
                    brand = normalize_brand(brand_raw)
                    if brand and i < len(cols):
                        try:
                            prices[oil_id][brand] = float(cols[i].replace(",",""))
                        except ValueError:
                            pass

        log.info(f"✅ DOEB: {len(prices)} ประเภท")
        return prices if prices else None
    except Exception as e:
        log.warning(f"⚠️  DOEB ล้มเหลว: {e}")
        return None


# ── Orchestrate ──────────────────────────────────────────────────────────────
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


# ── Filter prices ตาม BRAND_OILS ─────────────────────────────────────────────
def filter_prices_by_brand_oils(prices: dict) -> dict:
    """กรองให้เหลือเฉพาะน้ำมันที่แต่ละแบรนด์จำหน่ายจริง"""
    filtered = {}
    for oil_id in OIL_TYPES:
        filtered[oil_id] = {}
        for brand in BRANDS:
            if oil_id in BRAND_OILS.get(brand, []):
                p = prices.get(oil_id, {}).get(brand)
                if p is not None:
                    filtered[oil_id][brand] = p
    return filtered


# ── Save JSON ────────────────────────────────────────────────────────────────
def save_prices_json(prices: dict):
    output = {
        "updated": TIMESTAMP,
        "date":    TODAY,
        "prices":  prices,
    }

    # History
    history_file = "price_history.json"
    history = {}
    if os.path.exists(history_file):
        with open(history_file, encoding="utf-8") as f:
            try:
                history = json.load(f)
            except Exception:
                history = {}

    history[TODAY] = prices
    # เก็บแค่ 90 วัน
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

        # Sheet 1: ราคาล่าสุด
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
                p = prices.get(oil_id, {}).get(brand, "-")
                row.append(p)
            row.append(TIMESTAMP)
            rows.append(row)
        ws.update("A1", rows)
        format_header(ws, len(header))
        log.info("  ✅ Sheet 'ราคาล่าสุด' อัปเดตแล้ว")

        # Sheet 2+: ประวัติรายวันแต่ละน้ำมัน
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
            {
                "backgroundColor": {"red": 0.13, "green": 0.17, "blue": 0.28},
                "textFormat": {
                    "foregroundColor": {"red": 0.9, "green": 0.75, "blue": 0.2},
                    "bold": True, "fontSize": 11,
                },
                "horizontalAlignment": "CENTER",
            },
        )
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 50)
    log.info(f"🚀 Thai Oil Price Scraper — {TIMESTAMP}")
    log.info("=" * 50)

    # 1. ดึงราคา
    raw_prices = get_oil_prices()
    if not raw_prices:
        log.error("❌ ไม่มีข้อมูลราคา")
        raise SystemExit(1)

    # 2. กรองตาม BRAND_OILS
    prices = filter_prices_by_brand_oils(raw_prices)

    # 3. แสดงสรุป
    log.info("\n📋 ราคาน้ำมันวันนี้:")
    for oil_id, bp in prices.items():
        if bp:
            log.info(f"  {OIL_LABEL_TH[oil_id]}: {dict(list(bp.items())[:3])}")

    # 4. บันทึก JSON
    save_prices_json(prices)

    # 5. อัปเดต Google Sheets
    if os.environ.get("GOOGLE_CREDENTIALS_JSON"):
        update_google_sheets(prices)
    else:
        log.warning("⚠️  ไม่พบ GOOGLE_CREDENTIALS_JSON — ข้าม Sheets")

    log.info("\n🎉 เสร็จสิ้น!")


if __name__ == "__main__":
    main()
