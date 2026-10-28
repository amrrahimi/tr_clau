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
  }
];
