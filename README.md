# Trading Bot

A personal desktop app (Windows and macOS) for watching crypto charts on the Toobit exchange. Later phases add analysis, backtesting and paper trading.

**Current state: phase 1.** Live candle charts for spot and futures, top 50 coins by 24h volume, search, Persian and English. No API keys, no trading.

## How it is built

| Part | Language | Job |
|---|---|---|
| `backend/` | Python (ccxt, FastAPI) | Gets market data from the exchange; serves it on this computer only (`127.0.0.1:8765`) |
| `frontend/` | TypeScript (Lightweight Charts) | The screen and the chart |
| `frontend/src-tauri/` | Rust (Tauri) | The desktop window; starts the backend and stops it on exit |

## Download the app

1. Open the **Actions** tab → **Build desktop apps** → **Run workflow**.
2. When it finishes, download `windows` or `macos-intel` from the run's **Artifacts** section.

The app is not digitally signed:
- **Windows** shows "Windows protected your PC": choose **More info → Run anyway**.
- **macOS** blocks the first launch: open **System Settings → Privacy & Security** and choose **Open Anyway**.

## Develop

```bash
# backend
cd backend
pip install -r requirements.txt
python -m unittest discover -s tests -t .
python run.py                      # starts the local server

# frontend (in another terminal)
cd frontend
npm install
npm test
npm run dev                        # opens the screen at http://localhost:1420
```

## Security rule

This repository is public. **Never commit API keys, passwords or account details.** `.gitignore` blocks common secret files, but the rule is yours to keep.

---

# ربات معامله‌گر

برنامه‌ی شخصی دسکتاپ (ویندوز و مک) برای دیدن نمودار ارزهای دیجیتال در صرافی توبیت. فازهای بعدی تحلیل، بک‌تست و پیپر تریدینگ را اضافه می‌کنند.

**وضعیت فعلی: فاز ۱.** نمودار زنده‌ی اسپات و فیوچرز، ۵۰ ارز برتر بر اساس حجم ۲۴ ساعته، جستجو، فارسی و انگلیسی. بدون کلید API و بدون معامله.

**دریافت برنامه:** در زبانه‌ی **Actions** گزینه‌ی **Build desktop apps** و سپس **Run workflow** را بزنید. بعد از پایان، فایل `windows` یا `macos-intel` را از بخش **Artifacts** دانلود کنید. برنامه امضای دیجیتال ندارد؛ هشدار ویندوز و مک در اجرای اول طبیعی است.

**قانون امنیتی:** این مخزن عمومی است. **هرگز کلید API، رمز یا اطلاعات حساب را در آن قرار ندهید.**
