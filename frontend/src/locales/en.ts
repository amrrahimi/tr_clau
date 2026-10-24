// English texts. Every key here must also exist in fa.ts (a test checks this).
export const en = {
  "app.title": "Trading Bot",
  "market.spot": "Spot",
  "market.futures": "Futures",
  "mode.scalping": "Scalping",
  "mode.daily": "Daily",
  "watchlist.title": "Top 50 by 24h volume",
  "watchlist.searchPlaceholder": "Search coin…",
  "watchlist.searchResults": "Search results",
  "watchlist.empty": "No coins found",
  "watchlist.volume": "24h vol",
  "watchlist.toggle": "Coin list",
  "chart.loading": "Loading chart…",
  "chart.loadingOlder": "Loading older candles…",
  "chart.noMoreHistory": "No older candles",
  "status.live": "Live",
  "status.connecting": "Connecting",
  "status.stopped": "Stopped",
  "error.backendUnreachable": "The app's engine (backend) is not running.",
  "error.liveStopped": "Live updates stopped: {detail}",
  "error.generic": "Something went wrong: {detail}",
  "action.retry": "Retry",
  "language.switch": "FA",
  "language.switchLabel": "Switch to Persian",
} as const;

export type MessageKey = keyof typeof en;
