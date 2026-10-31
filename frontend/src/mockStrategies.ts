// Copy of the backend strategy cards (backend/app/strategies.py) for the sample-data preview only.
// The real app asks the backend. A test checks this copy is not out of date.
import type { StrategyCard } from "./types.ts";

export const MOCK_STRATEGIES: StrategyCard[] = [
  {
    "type": "ema_cross",
    "name": "EMA Cross",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "EMA",
      "ATR"
    ],
    "params": [
      {
        "name": "fast",
        "default": 9,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "slow",
        "default": 21,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "trend",
        "default": 200,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "atr_length",
        "default": 14,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "atr_mult",
        "default": 1.5,
        "min": 0.1,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "reward",
        "default": 2,
        "min": 0.5,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "state_filter",
        "default": 1,
        "min": 0,
        "max": 1,
        "step": 1
      },
      {
        "name": "breakeven",
        "default": 0.5,
        "min": 0,
        "max": 0.95,
        "step": 0.05
      },
      {
        "name": "max_candles",
        "default": 0,
        "min": 0,
        "max": 1000,
        "step": 1
      },
      {
        "name": "fee_ratio",
        "default": 0.33,
        "min": 0,
        "max": 1,
        "step": 0.01
      }
    ],
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "macd_ema",
    "name": "MACD + EMA",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "MACD",
      "EMA"
    ],
    "params": [
      {
        "name": "fast",
        "default": 12,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "slow",
        "default": 26,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "signal",
        "default": 9,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "trend",
        "default": 200,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "swing",
        "default": 10,
        "min": 2,
        "max": 100,
        "step": 1
      },
      {
        "name": "reward",
        "default": 1.5,
        "min": 0.5,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "state_filter",
        "default": 1,
        "min": 0,
        "max": 1,
        "step": 1
      },
      {
        "name": "breakeven",
        "default": 0.5,
        "min": 0,
        "max": 0.95,
        "step": 0.05
      },
      {
        "name": "max_candles",
        "default": 0,
        "min": 0,
        "max": 1000,
        "step": 1
      },
      {
        "name": "fee_ratio",
        "default": 0.33,
        "min": 0,
        "max": 1,
        "step": 0.01
      }
    ],
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "rsi_pullback",
    "name": "RSI Pullback",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "RSI",
      "EMA",
      "ATR"
    ],
    "params": [
      {
        "name": "rsi_length",
        "default": 14,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "oversold",
        "default": 40,
        "min": 1,
        "max": 99,
        "step": 1
      },
      {
        "name": "overbought",
        "default": 60,
        "min": 1,
        "max": 99,
        "step": 1
      },
      {
        "name": "trend",
        "default": 200,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "atr_length",
        "default": 14,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "atr_mult",
        "default": 1.5,
        "min": 0.1,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "reward",
        "default": 2,
        "min": 0.5,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "state_filter",
        "default": 1,
        "min": 0,
        "max": 1,
        "step": 1
      },
      {
        "name": "breakeven",
        "default": 0.5,
        "min": 0,
        "max": 0.95,
        "step": 0.05
      },
      {
        "name": "max_candles",
        "default": 0,
        "min": 0,
        "max": 1000,
        "step": 1
      },
      {
        "name": "fee_ratio",
        "default": 0.33,
        "min": 0,
        "max": 1,
        "step": 0.01
      }
    ],
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "bb_reversion",
    "name": "Bollinger Reversion",
    "states": [
      "range"
    ],
    "uses": [
      "BB"
    ],
    "params": [
      {
        "name": "length",
        "default": 20,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "mult",
        "default": 2,
        "min": 0.1,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "state_filter",
        "default": 1,
        "min": 0,
        "max": 1,
        "step": 1
      },
      {
        "name": "breakeven",
        "default": 0.5,
        "min": 0,
        "max": 0.95,
        "step": 0.05
      },
      {
        "name": "max_candles",
        "default": 0,
        "min": 0,
        "max": 1000,
        "step": 1
      },
      {
        "name": "fee_ratio",
        "default": 0.33,
        "min": 0,
        "max": 1,
        "step": 0.01
      }
    ],
    "modeDefaults": {}
  },
  {
    "type": "supertrend",
    "name": "SuperTrend",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "SuperTrend",
      "EMA"
    ],
    "params": [
      {
        "name": "atr_length",
        "default": 10,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "factor",
        "default": 3,
        "min": 0.1,
        "max": 20,
        "step": 0.1
      },
      {
        "name": "trend",
        "default": 200,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "reward",
        "default": 2,
        "min": 0.5,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "state_filter",
        "default": 1,
        "min": 0,
        "max": 1,
        "step": 1
      },
      {
        "name": "breakeven",
        "default": 0.5,
        "min": 0,
        "max": 0.95,
        "step": 0.05
      },
      {
        "name": "max_candles",
        "default": 0,
        "min": 0,
        "max": 1000,
        "step": 1
      },
      {
        "name": "fee_ratio",
        "default": 0.33,
        "min": 0,
        "max": 1,
        "step": 0.01
      }
    ],
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "donchian",
    "name": "Channel Breakout",
    "states": [
      "range",
      "volatile"
    ],
    "uses": [
      "Donchian",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 20,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "atr_length",
        "default": 14,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "atr_mult",
        "default": 2,
        "min": 0.1,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "reward",
        "default": 2,
        "min": 0.5,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "state_filter",
        "default": 1,
        "min": 0,
        "max": 1,
        "step": 1
      },
      {
        "name": "breakeven",
        "default": 0.5,
        "min": 0,
        "max": 0.95,
        "step": 0.05
      },
      {
        "name": "max_candles",
        "default": 0,
        "min": 0,
        "max": 1000,
        "step": 1
      },
      {
        "name": "fee_ratio",
        "default": 0.33,
        "min": 0,
        "max": 1,
        "step": 0.01
      }
    ],
    "modeDefaults": {}
  },
  {
    "type": "liquidity_sweep",
    "name": "Liquidity Sweep",
    "states": [
      "trend_up",
      "trend_down",
      "range",
      "volatile"
    ],
    "uses": [
      "Price action",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 20,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "buffer",
        "default": 0.2,
        "min": 0,
        "max": 5,
        "step": 0.05
      },
      {
        "name": "reward",
        "default": 2,
        "min": 0.5,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "state_filter",
        "default": 1,
        "min": 0,
        "max": 1,
        "step": 1
      },
      {
        "name": "breakeven",
        "default": 0.5,
        "min": 0,
        "max": 0.95,
        "step": 0.05
      },
      {
        "name": "max_candles",
        "default": 0,
        "min": 0,
        "max": 1000,
        "step": 1
      },
      {
        "name": "fee_ratio",
        "default": 0.33,
        "min": 0,
        "max": 1,
        "step": 0.01
      }
    ],
    "modeDefaults": {}
  },
  {
    "type": "fvg_retest",
    "name": "FVG Retest",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "Price action",
      "EMA"
    ],
    "params": [
      {
        "name": "trend",
        "default": 200,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "max_wait",
        "default": 30,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "buffer",
        "default": 0.2,
        "min": 0,
        "max": 5,
        "step": 0.05
      },
      {
        "name": "reward",
        "default": 2,
        "min": 0.5,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "state_filter",
        "default": 1,
        "min": 0,
        "max": 1,
        "step": 1
      },
      {
        "name": "breakeven",
        "default": 0.5,
        "min": 0,
        "max": 0.95,
        "step": 0.05
      },
      {
        "name": "max_candles",
        "default": 0,
        "min": 0,
        "max": 1000,
        "step": 1
      },
      {
        "name": "fee_ratio",
        "default": 0.33,
        "min": 0,
        "max": 1,
        "step": 0.01
      }
    ],
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "order_block",
    "name": "Order Block",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "Price action",
      "EMA"
    ],
    "params": [
      {
        "name": "swing",
        "default": 10,
        "min": 2,
        "max": 200,
        "step": 1
      },
      {
        "name": "trend",
        "default": 200,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "max_wait",
        "default": 30,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "buffer",
        "default": 0.2,
        "min": 0,
        "max": 5,
        "step": 0.05
      },
      {
        "name": "reward",
        "default": 2,
        "min": 0.5,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "state_filter",
        "default": 1,
        "min": 0,
        "max": 1,
        "step": 1
      },
      {
        "name": "breakeven",
        "default": 0.5,
        "min": 0,
        "max": 0.95,
        "step": 0.05
      },
      {
        "name": "max_candles",
        "default": 0,
        "min": 0,
        "max": 1000,
        "step": 1
      },
      {
        "name": "fee_ratio",
        "default": 0.33,
        "min": 0,
        "max": 1,
        "step": 0.01
      }
    ],
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "sd_zone",
    "name": "Supply & Demand (RTM)",
    "states": [
      "trend_up",
      "trend_down",
      "range",
      "volatile"
    ],
    "uses": [
      "Price action",
      "ATR"
    ],
    "params": [
      {
        "name": "leg",
        "default": 2,
        "min": 0.5,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "max_wait",
        "default": 50,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "buffer",
        "default": 0.2,
        "min": 0,
        "max": 5,
        "step": 0.05
      },
      {
        "name": "reward",
        "default": 2,
        "min": 0.5,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "state_filter",
        "default": 1,
        "min": 0,
        "max": 1,
        "step": 1
      },
      {
        "name": "breakeven",
        "default": 0.5,
        "min": 0,
        "max": 0.95,
        "step": 0.05
      },
      {
        "name": "max_candles",
        "default": 0,
        "min": 0,
        "max": 1000,
        "step": 1
      },
      {
        "name": "fee_ratio",
        "default": 0.33,
        "min": 0,
        "max": 1,
        "step": 0.01
      }
    ],
    "modeDefaults": {}
  },
  {
    "type": "squeeze",
    "name": "Squeeze Breakout",
    "states": [
      "range",
      "volatile"
    ],
    "uses": [
      "BB",
      "Keltner",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 20,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "kc_mult",
        "default": 1.5,
        "min": 0.1,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "min_quiet",
        "default": 5,
        "min": 1,
        "max": 200,
        "step": 1
      },
      {
        "name": "atr_mult",
        "default": 1.5,
        "min": 0.1,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "reward",
        "default": 2,
        "min": 0.5,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "state_filter",
        "default": 1,
        "min": 0,
        "max": 1,
        "step": 1
      },
      {
        "name": "breakeven",
        "default": 0.5,
        "min": 0,
        "max": 0.95,
        "step": 0.05
      },
      {
        "name": "max_candles",
        "default": 0,
        "min": 0,
        "max": 1000,
        "step": 1
      },
      {
        "name": "fee_ratio",
        "default": 0.33,
        "min": 0,
        "max": 1,
        "step": 0.01
      }
    ],
    "modeDefaults": {}
  },
  {
    "type": "vwap_reversion",
    "name": "VWAP Reversion",
    "states": [
      "range"
    ],
    "uses": [
      "VWAP",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 96,
        "min": 5,
        "max": 2000,
        "step": 1
      },
      {
        "name": "band",
        "default": 2,
        "min": 0.5,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "state_filter",
        "default": 1,
        "min": 0,
        "max": 1,
        "step": 1
      },
      {
        "name": "breakeven",
        "default": 0.5,
        "min": 0,
        "max": 0.95,
        "step": 0.05
      },
      {
        "name": "max_candles",
        "default": 0,
        "min": 0,
        "max": 1000,
        "step": 1
      },
      {
        "name": "fee_ratio",
        "default": 0.33,
        "min": 0,
        "max": 1,
        "step": 0.01
      }
    ],
    "modeDefaults": {}
  }
];
