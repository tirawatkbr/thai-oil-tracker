"""
Thai Oil Price Scraper
======================
ดึงราคาน้ำมันจาก 3 แหล่ง:
  1. api.chnwt.dev/thai-oil-api  (primary - JSON API)
  2. DOEB เว็บกรมธุรกิจพลังงาน  (fallback)
  3. PTT SOAP API               (PTT เฉพาะ)

แล้วบันทึกลง Google Sheets + prices.json
"""

import os
import json
import time
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

# ── Config ──────────────────────────────────────────────────────────────────
TZ = ZoneInfo("Asia/Bangkok")
TODAY = datetime.now(TZ).strftime("%Y-%m-%d")
TIMESTAMP = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "Thai Oil Prices")
PRICES_JSON = "prices.json"  # output file สำหรับ GitHub Pages

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

OIL_TYPES = ["g95", "g91", "e20", "e85", "diesel", "diesel_premium", "premium"]

OIL_LABEL_TH = {
    "g95": "แก๊สโซฮอล์ 95",
    "g91": "แก๊สโซฮอล์ 91",
    "e20": "E20",
    "e85": "E85",
    "diesel": "ดีเซล B7",
    "diesel_premium": "ดีเซลพรีเมียม",
    "premium": "พรีเมียม 97",
}

BRANDS = ["PTT", "Shell", "Caltex", "Esso", "BCP", "Susco"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Source 1: thai-oil-api (Primary) ────────────────────────────────────────
def fetch_from_thai_oil_api() -> dict | None:
    """
    ดึงจาก https://api.chnwt.dev/thai-oil-api/latest
    Response structure:
    {
      "result": {
        "date": "2024-01-15",
        "price": [
          { "name": "แก๊สโซฮอล์ 95",
            "price": { "PTT": "39.95", "Shell": "40.05", ... }
          },
          ...
        ]
      }
    }
    """
    url = "https://api.chnwt.dev/thai-oil-api/latest"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        prices = {}
        for item in data.get("result", {}).get("price", []):
            name = item.get("name", "")
            oil_id = thai_name_to_id(name)
            if oil_id:
                prices[oil_id] = {}
                for brand, price_str in item.get("price", {}).items():
                    try:
                        prices[oil_id][brand] = float(price_str)
                    except (ValueError, TypeError):
                        pass
        log.info(f"✅ thai-oil-api: ดึงข้อมูลสำเร็จ {len(prices)} ประเภท")
        return prices
    except Exception as e:
        log.warning(f"⚠️  thai-oil-api ล้มเหลว: {e}")
        return None


def thai_name_to_id(name: str) -> str | None:
    mapping = {
        "แก๊สโซฮอล์ 95": "g95",
        "gasohol 95": "g95",
        "e10 95": "g95",
        "แก๊สโซฮอล์ 91": "g91",
        "gasohol 91": "g91",
        "e10 91": "g91",
        "e20": "e20",
        "e85": "e85",
        "ดีเซล": "diesel",
        "diesel b7": "diesel",
        "b7": "diesel",
        "ดีเซลพรีเมียม": "diesel_premium",
        "hi diesel": "diesel_premium",
        "พรีเมียม 97": "premium",
        "premium 97": "premium",
    }
    return mapping.get(name.lower().strip())


# ── Source 2: DOEB Scraper (Fallback) ───────────────────────────────────────
def fetch_from_doeb() -> dict | None:
    """
    Scrape จาก www2.doeb.go.th/price/oilprice.html
    ตารางราคาน้ำมันจากกรมธุรกิจพลังงาน (แหล่งทางการ)
    """
    url = "https://www2.doeb.go.th/price/oilprice.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        prices = {oil: {} for oil in OIL_TYPES}
        tables = soup.find_all("table")

        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if len(cols) < 3:
                    continue
                oil_id = thai_name_to_id(cols[0])
                if not oil_id:
                    continue
                for i, brand in enumerate(BRANDS, start=1):
                    if i < len(cols):
                        try:
                            prices[oil_id][brand] = float(cols[i].replace(",", ""))
                        except ValueError:
                            pass

        log.info("✅ DOEB: ดึงข้อมูลสำเร็จ (fallback)")
        return prices
    except Exception as e:
        log.warning(f"⚠️  DOEB scraper ล้มเหลว: {e}")
        return None


# ── Source 3: Kapook Gas Price (Secondary Fallback) ─────────────────────────
def fetch_from_kapook() -> dict | None:
    """
    Scrape จาก gasprice.kapook.com
    แสดงราคาน้ำมันรายแบรนด์แบบ real-time
    """
    url = "https://gasprice.kapook.com/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        prices = {oil: {} for oil in OIL_TYPES}

        # หา section ราคาแต่ละปั๊ม
        brand_sections = soup.find_all(class_=lambda c: c and "brand" in c.lower())
        for section in brand_sections:
            brand_name = section.find(class_="brand-name")
            if not brand_name:
                continue
            bname = normalize_brand(brand_name.get_text(strip=True))

            oil_rows = section.find_all(class_=lambda c: c and "oil" in c.lower())
            for row in oil_rows:
                name_el = row.find(class_="oil-name")
                price_el = row.find(class_="price")
                if not name_el or not price_el:
                    continue
                oil_id = thai_name_to_id(name_el.get_text(strip=True))
                if oil_id and bname:
                    try:
                        prices[oil_id][bname] = float(
                            price_el.get_text(strip=True).replace(",", "")
                        )
                    except ValueError:
                        pass

        log.info("✅ Kapook: ดึงข้อมูลสำเร็จ (secondary fallback)")
        return prices
    except Exception as e:
        log.warning(f"⚠️  Kapook scraper ล้มเหลว: {e}")
        return None


def normalize_brand(name: str) -> str | None:
    mapping = {
        "ptt": "PTT", "ปตท": "PTT",
        "shell": "Shell", "เชลล์": "Shell",
        "caltex": "Caltex", "คาลเท็กซ์": "Caltex",
        "esso": "Esso", "เอสโซ่": "Esso",
        "bcp": "BCP", "บางจาก": "BCP",
        "susco": "Susco", "ซัสโก้": "Susco",
    }
    return mapping.get(name.lower().strip())


# ── Orchestrate Sources ──────────────────────────────────────────────────────
def get_oil_prices() -> dict:
    log.info("🔍 เริ่มดึงราคาน้ำมัน...")

    # ลอง Source ตามลำดับจนได้ข้อมูล
    for name, fn in [
        ("thai-oil-api", fetch_from_thai_oil_api),
        ("DOEB", fetch_from_doeb),
        ("Kapook", fetch_from_kapook),
    ]:
        data = fn()
        if data and any(data.values()):
            log.info(f"✅ ใช้ข้อมูลจาก: {name}")
            return data

    log.error("❌ ดึงข้อมูลล้มเหลวทุกแหล่ง")
    return {}


# ── Google Sheets ────────────────────────────────────────────────────────────
def get_gsheet_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("ไม่พบ GOOGLE_CREDENTIALS_JSON ใน environment")

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
        sh = gc.open(SHEET_NAME)
    except gspread.SpreadsheetNotFound:
        log.info(f"📋 สร้าง Spreadsheet ใหม่: {SHEET_NAME}")
        gc = get_gsheet_client()
        sh = gc.create(SHEET_NAME)
        sh.share(None, perm_type="anyone", role="reader")  # อ่านได้โดยไม่ต้อง login

    # ── Sheet 1: ราคาล่าสุด (Latest Prices) ─────────────────────────────
    try:
        ws_latest = sh.worksheet("ราคาล่าสุด")
        ws_latest.clear()
    except gspread.WorksheetNotFound:
        ws_latest = sh.add_worksheet("ราคาล่าสุด", rows=50, cols=20)

    # Header
    header = ["ประเภทน้ำมัน"] + BRANDS + ["อัปเดต"]
    rows = [header]
    for oil_id in OIL_TYPES:
        row = [OIL_LABEL_TH[oil_id]]
        for brand in BRANDS:
            p = prices.get(oil_id, {}).get(brand, "-")
            row.append(p if p != "-" else "-")
        row.append(TIMESTAMP)
        rows.append(row)

    ws_latest.update("A1", rows)
    format_header(ws_latest, len(header))
    log.info("  ✅ Sheet 'ราคาล่าสุด' อัปเดตแล้ว")

    # ── Sheet 2: ประวัติรายวัน (Daily History) ───────────────────────────
    for oil_id in OIL_TYPES:
        sheet_name = f"ประวัติ-{OIL_LABEL_TH[oil_id]}"
        try:
            ws = sh.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(sheet_name, rows=500, cols=20)
            ws.update("A1", [["วันที่"] + BRANDS])
            format_header(ws, len(BRANDS) + 1)

        # เช็คว่าวันนี้มีข้อมูลแล้วหรือยัง
        existing = ws.col_values(1)  # column วันที่
        if TODAY in existing:
            log.info(f"  ⏭️  {sheet_name}: มีข้อมูลวันนี้แล้ว (skip)")
            continue

        new_row = [TODAY]
        for brand in BRANDS:
            p = prices.get(oil_id, {}).get(brand, "")
            new_row.append(p)

        ws.append_row(new_row)
        log.info(f"  ✅ {sheet_name}: เพิ่มข้อมูลวันที่ {TODAY}")
        time.sleep(1)  # rate limit

    log.info("✅ Google Sheets อัปเดตครบทุก sheet")


def format_header(ws, col_count: int):
    """จัดรูปแบบ header row ให้สวยงาม"""
    try:
        ws.format(
            f"A1:{chr(64+col_count)}1",
            {
                "backgroundColor": {"red": 0.13, "green": 0.17, "blue": 0.28},
                "textFormat": {
                    "foregroundColor": {"red": 0.9, "green": 0.75, "blue": 0.2},
                    "bold": True,
                    "fontSize": 11,
                },
                "horizontalAlignment": "CENTER",
            },
        )
    except Exception:
        pass  # formatting ไม่ critical


# ── Save JSON for GitHub Pages ───────────────────────────────────────────────
def save_prices_json(prices: dict):
    """
    บันทึก prices.json สำหรับให้เว็บ HTML อ่าน
    Structure:
    {
      "updated": "2024-01-15 06:05:00",
      "date": "2024-01-15",
      "prices": {
        "g95": { "PTT": 39.95, "Shell": 40.05, ... },
        ...
      }
    }
    """
    output = {
        "updated": TIMESTAMP,
        "date": TODAY,
        "prices": prices,
    }

    # ต่อยอดกับ history ที่มีอยู่
    history_file = "price_history.json"
    history = {}
    if os.path.exists(history_file):
        with open(history_file) as f:
            history = json.load(f)

    history[TODAY] = prices

    # เก็บแค่ 90 วันล่าสุด
    sorted_keys = sorted(history.keys())[-90:]
    history = {k: history[k] for k in sorted_keys}

    with open(PRICES_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    log.info(f"✅ บันทึก {PRICES_JSON} และ {history_file} แล้ว")


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 50)
    log.info(f"🚀 Thai Oil Price Scraper — {TIMESTAMP}")
    log.info("=" * 50)

    # 1. ดึงราคาน้ำมัน
    prices = get_oil_prices()
    if not prices:
        log.error("❌ ไม่มีข้อมูลราคา หยุดทำงาน")
        raise SystemExit(1)

    # 2. แสดงผลสรุป
    log.info("\n📋 ราคาน้ำมันวันนี้:")
    for oil_id, brand_prices in prices.items():
        if brand_prices:
            sample = list(brand_prices.items())[:3]
            log.info(f"  {OIL_LABEL_TH.get(oil_id, oil_id)}: {sample}")

    # 3. บันทึก JSON
    save_prices_json(prices)

    # 4. อัปเดต Google Sheets
    if os.environ.get("GOOGLE_CREDENTIALS_JSON"):
        update_google_sheets(prices)
    else:
        log.warning("⚠️  ไม่พบ GOOGLE_CREDENTIALS_JSON — ข้าม Google Sheets")

    log.info("\n🎉 เสร็จสิ้น!")


if __name__ == "__main__":
    main()
