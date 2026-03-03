# 🛢️ Thai Oil Price Automation

ระบบดึงราคาน้ำมันไทยรายวันอัตโนมัติ → เก็บใน Google Sheets → แสดงบนเว็บ

---

## 📁 โครงสร้างไฟล์

```
thai-oil-automation/
├── .github/
│   └── workflows/
│       └── daily-oil-price.yml   ← GitHub Actions (รันอัตโนมัติ)
├── scripts/
│   └── scraper.py                ← Python scraper หลัก
├── index.html                    ← เว็บแสดงราคา (GitHub Pages)
├── prices.json                   ← ราคาล่าสุด (auto-generated)
├── price_history.json            ← ประวัติ 90 วัน (auto-generated)
├── requirements.txt              ← Python dependencies
└── README.md
```

---

## 🚀 วิธีติดตั้ง (ทำครั้งเดียว ~15 นาที)

### ขั้นตอนที่ 1 — สร้าง Google Service Account

1. ไปที่ [Google Cloud Console](https://console.cloud.google.com/)
2. สร้าง Project ใหม่ (ตั้งชื่อ เช่น `thai-oil-tracker`)
3. เปิดใช้ **Google Sheets API** และ **Google Drive API**
   - APIs & Services → Enable APIs → ค้นหา "Google Sheets API" → Enable
   - ทำซ้ำสำหรับ "Google Drive API"
4. สร้าง **Service Account**
   - IAM & Admin → Service Accounts → Create Service Account
   - ตั้งชื่อ เช่น `oil-scraper`
5. ดาวน์โหลด **JSON Key**
   - คลิก Service Account → Keys → Add Key → Create new key → JSON
   - เก็บไฟล์ JSON ไว้ (จะใช้ใน GitHub Secrets)

### ขั้นตอนที่ 2 — สร้าง Google Sheets

1. ไปที่ [Google Sheets](https://sheets.google.com/)
2. สร้าง Spreadsheet ใหม่ ตั้งชื่อ: **Thai Oil Prices**
3. แชร์ให้ Service Account email (ดูจากไฟล์ JSON ช่อง `client_email`)
   - Share → ใส่ email → Editor

### ขั้นตอนที่ 3 — ตั้งค่า GitHub Repository

1. Fork หรือสร้าง repo ใหม่บน GitHub
2. Upload ไฟล์ทั้งหมดในโฟลเดอร์นี้
3. ตั้งค่า **Secrets**:
   - Settings → Secrets and variables → Actions → New repository secret

   | Secret Name | ค่า |
   |---|---|
   | `GOOGLE_CREDENTIALS_JSON` | เนื้อหาทั้งหมดของไฟล์ JSON ที่ดาวน์โหลด |
   | `GOOGLE_SHEET_NAME` | `Thai Oil Prices` |

### ขั้นตอนที่ 4 — เปิด GitHub Pages

1. Settings → Pages
2. Source: **Deploy from a branch**
3. Branch: `main` / `root`
4. Save → เว็บจะอยู่ที่ `https://[username].github.io/[repo-name]/`

### ขั้นตอนที่ 5 — ทดสอบรัน

1. Actions tab → "🛢️ Daily Oil Price Update"
2. Run workflow → Run workflow
3. รอ ~2 นาที ตรวจสอบ logs

---

## ⏰ ตาราง Schedule

| เหตุการณ์ | เวลา |
|---|---|
| GitHub Actions รัน scraper | 06:05 น. (ไทย) |
| บันทึกใน Google Sheets | 06:06 น. |
| Commit prices.json | 06:07 น. |
| เว็บแสดงราคาใหม่ | 06:08 น. |

---

## 🔧 รันด้วยตนเอง (Local)

```bash
# ติดตั้ง dependencies
pip install -r requirements.txt

# ตั้งค่า environment
export GOOGLE_CREDENTIALS_JSON='{ ... เนื้อหา JSON ... }'
export GOOGLE_SHEET_NAME='Thai Oil Prices'

# รัน scraper
python scripts/scraper.py
```

---

## 📊 โครงสร้าง Google Sheets

| Sheet | เนื้อหา |
|---|---|
| `ราคาล่าสุด` | ราคาปัจจุบันทุกแบรนด์/ทุกประเภท |
| `ประวัติ-แก๊สโซฮอล์ 95` | ราคารายวัน 95 ย้อนหลัง |
| `ประวัติ-แก๊สโซฮอล์ 91` | ราคารายวัน 91 ย้อนหลัง |
| `ประวัติ-E20` | ราคารายวัน E20 ย้อนหลัง |
| `ประวัติ-ดีเซล B7` | ราคารายวัน ดีเซล ย้อนหลัง |
| ... | ... |

---

## ⚠️ หมายเหตุ

- GitHub Actions ฟรี: **2,000 นาที/เดือน** (ใช้จริงแค่ ~2 นาที/วัน = ~60 นาที/เดือน ✅)
- ข้อมูลราคาจาก `api.chnwt.dev` → DOEB → Kapook (fallback ตามลำดับ)
- `price_history.json` เก็บย้อนหลัง 90 วัน
