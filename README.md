# Leon

A personal desktop app (Windows, macOS and Android) for the Toobit exchange: live crypto charts, indicators, strategy history tests, a scanner and a paper-trading bot (virtual money).

**Current state:** live charts for spot and futures, 47 strategies with history tests after fees, a scanner, and a paper bot on 1m-4h with a memory of every signal, an optional learning filter ("brain") and optional AI approval (Gemini, the owner's own key kept on his computer). Persian and English. **No real orders are ever sent to the exchange.** By default the bot trades the "proven set": breakout / momentum strategies on 1h and 4h, tuned per timeframe and taken in a fixed priority order, with many small trades. "Trend Rider" (a 4h trend-following engine) is a second mode behind a switch: `docs/RESEARCH-2026-11-11.md`. Details and the latest findings: `docs/HANDOFF.md`.

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
python -m unittest discover -s tests -t .   # uses its own temporary data folder, never ~/.trading-bot
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

برنامه‌ی شخصی (ویندوز، مک و اندروید) برای صرافی توبیت: نمودار زنده، اندیکاتورها، آزمون تاریخی استراتژی‌ها، اسکنر و ربات پیپر (پول مجازی).

**وضعیت فعلی:** نمودار زنده‌ی اسپات و فیوچرز، ۴۷ استراتژی با آزمون تاریخی بعد از کارمزد، اسکنر، و ربات پیپر روی تایم‌فریم‌های ۱ دقیقه تا ۴ ساعت با حافظه‌ی همه‌ی سیگنال‌ها، فیلتر یادگیرنده («مغز») و تأیید اختیاری هوش مصنوعی (Gemini، با کلید خود صاحب برنامه که فقط روی کامپیوتر او می‌ماند). فارسی و انگلیسی. **هیچ سفارش واقعی به صرافی فرستاده نمی‌شود.** به‌طور پیش‌فرض ربات «مجموعه‌ی آزموده» را معامله می‌کند: استراتژی‌های شکست / مومنتوم روی ۱ ساعته و ۴ ساعته، تنظیم‌شده برای هر تایم‌فریم و با ترتیب اولویت ثابت، با معامله‌های کوچک و پرتعداد. «روندسوار» (موتور روندی ۴ ساعته) حالت دوم است و با یک کلید روشن می‌شود: `docs/RESEARCH-2026-11-11.md`. جزئیات و آخرین یافته‌ها: `docs/HANDOFF.md`.

**دریافت برنامه:** در زبانه‌ی **Actions** گزینه‌ی **Build desktop apps** و سپس **Run workflow** را بزنید. بعد از پایان، فایل `windows` یا `macos-intel` را از بخش **Artifacts** دانلود کنید. برنامه امضای دیجیتال ندارد؛ هشدار ویندوز و مک در اجرای اول طبیعی است.

**قانون امنیتی:** این مخزن عمومی است. **هرگز کلید API، رمز یا اطلاعات حساب را در آن قرار ندهید.**
