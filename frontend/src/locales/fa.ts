// Persian texts. Must have exactly the same keys as en.ts (a test checks this).
import type { MessageKey } from "./en.ts";

export const fa: Record<MessageKey, string> = {
  "app.title": "ربات معامله‌گر",
  "market.spot": "اسپات",
  "market.futures": "فیوچرز",
  "mode.scalping": "نوسان‌گیری",
  "mode.daily": "روزانه",
  "watchlist.title": "۵۰ ارز برتر بر اساس حجم ۲۴ ساعته",
  "watchlist.searchPlaceholder": "جستجوی ارز…",
  "watchlist.searchResults": "نتایج جستجو",
  "watchlist.empty": "ارزی پیدا نشد",
  "watchlist.volume": "حجم ۲۴ س",
  "watchlist.toggle": "فهرست ارزها",
  "chart.loading": "در حال بارگذاری نمودار…",
  "chart.loadingOlder": "در حال بارگذاری کندل‌های قدیمی‌تر…",
  "chart.noMoreHistory": "کندل قدیمی‌تری وجود ندارد",
  "status.live": "زنده",
  "status.connecting": "در حال اتصال",
  "status.stopped": "متوقف",
  "error.backendUnreachable": "موتور برنامه (بک‌اند) در حال اجرا نیست.",
  "error.liveStopped": "به‌روزرسانی زنده متوقف شد: {detail}",
  "error.generic": "خطایی رخ داد: {detail}",
  "action.retry": "تلاش دوباره",
  "language.switch": "EN",
  "language.switchLabel": "تغییر به انگلیسی",
};
