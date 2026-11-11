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
  },
  {
    "type": "ema_pullback",
    "name": "EMA Pullback",
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
        "default": 20,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "slow",
        "default": 50,
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
    "type": "dmi_adx",
    "name": "DMI + ADX",
    "states": [
      "trend_up",
      "trend_down",
      "volatile"
    ],
    "uses": [
      "DMI",
      "ADX",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 14,
        "min": 2,
        "max": 200,
        "step": 1
      },
      {
        "name": "min_adx",
        "default": 20,
        "min": 5,
        "max": 80,
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
        "default": 2.5,
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
    "type": "ichimoku",
    "name": "Ichimoku Cloud",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "Ichimoku",
      "ATR"
    ],
    "params": [
      {
        "name": "tenkan",
        "default": 9,
        "min": 2,
        "max": 200,
        "step": 1
      },
      {
        "name": "kijun",
        "default": 26,
        "min": 2,
        "max": 300,
        "step": 1
      },
      {
        "name": "span_b",
        "default": 52,
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
    "modeDefaults": {}
  },
  {
    "type": "inside_bar",
    "name": "Inside Bar Breakout",
    "states": [
      "trend_up",
      "trend_down",
      "volatile"
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
    "type": "stoch_rsi_trend",
    "name": "Stoch RSI Pullback",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "Stoch RSI",
      "EMA",
      "ATR"
    ],
    "params": [
      {
        "name": "rsi_length",
        "default": 14,
        "min": 2,
        "max": 200,
        "step": 1
      },
      {
        "name": "oversold",
        "default": 20,
        "min": 1,
        "max": 99,
        "step": 1
      },
      {
        "name": "overbought",
        "default": 80,
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
    "type": "volume_breakout",
    "name": "Volume Breakout",
    "states": [
      "trend_up",
      "trend_down",
      "volatile"
    ],
    "uses": [
      "Keltner",
      "Volume",
      "EMA"
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
        "default": 2,
        "min": 0.1,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "volume_mult",
        "default": 2,
        "min": 1,
        "max": 10,
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
    "type": "turtle",
    "name": "Turtle Breakout",
    "states": [
      "trend_up",
      "trend_down",
      "volatile"
    ],
    "uses": [
      "Donchian",
      "EMA",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 55,
        "min": 2,
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
        "name": "atr_mult",
        "default": 2,
        "min": 0.1,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "reward",
        "default": 3,
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
    "type": "keltner_breakout",
    "name": "Keltner Breakout",
    "states": [
      "trend_up",
      "trend_down",
      "volatile"
    ],
    "uses": [
      "Keltner",
      "EMA"
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
        "default": 2,
        "min": 0.1,
        "max": 10,
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
    "type": "bb_breakout",
    "name": "Bollinger Breakout",
    "states": [
      "trend_up",
      "trend_down",
      "volatile"
    ],
    "uses": [
      "BB",
      "EMA"
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
    "type": "ema_ribbon",
    "name": "EMA Ribbon",
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
        "default": 8,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "mid",
        "default": 21,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "slow",
        "default": 55,
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
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "momentum",
    "name": "Momentum Thrust",
    "states": [
      "trend_up",
      "trend_down",
      "volatile"
    ],
    "uses": [
      "Momentum",
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
        "name": "thrust",
        "default": 4,
        "min": 0.5,
        "max": 20,
        "step": 0.5
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
    "type": "macd_zero",
    "name": "MACD Zero Cross",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "MACD",
      "EMA",
      "ATR"
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
        "name": "trend",
        "default": 200,
        "min": 2,
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
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "hma_turn",
    "name": "Hull MA Turn",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "HMA",
      "EMA",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 55,
        "min": 2,
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
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "psar_flip",
    "name": "Parabolic SAR Flip",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "PSAR",
      "EMA"
    ],
    "params": [
      {
        "name": "step",
        "default": 0.02,
        "min": 0.001,
        "max": 0.2,
        "step": 0.001
      },
      {
        "name": "maximum",
        "default": 0.2,
        "min": 0.01,
        "max": 1,
        "step": 0.01
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
    "type": "cci_trend",
    "name": "CCI Trend",
    "states": [
      "trend_up",
      "trend_down",
      "volatile"
    ],
    "uses": [
      "CCI",
      "EMA",
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
        "name": "level",
        "default": 100,
        "min": 10,
        "max": 400,
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
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "aroon_cross",
    "name": "Aroon Cross",
    "states": [
      "trend_up",
      "trend_down",
      "range",
      "volatile"
    ],
    "uses": [
      "Aroon",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 25,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "strong",
        "default": 70,
        "min": 0,
        "max": 100,
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
    "type": "vortex_cross",
    "name": "Vortex Cross",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "Vortex",
      "EMA",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 14,
        "min": 2,
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
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "adx_breakout",
    "name": "ADX Breakout",
    "states": [
      "trend_up",
      "trend_down",
      "volatile"
    ],
    "uses": [
      "Donchian",
      "ADX",
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
        "name": "min_adx",
        "default": 25,
        "min": 5,
        "max": 80,
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
    "type": "obv_breakout",
    "name": "OBV Breakout",
    "states": [
      "trend_up",
      "trend_down",
      "volatile"
    ],
    "uses": [
      "OBV",
      "EMA",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 50,
        "min": 2,
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
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "kama_cross",
    "name": "KAMA Cross",
    "states": [
      "trend_up",
      "trend_down",
      "volatile"
    ],
    "uses": [
      "KAMA",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 10,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "min_er",
        "default": 0.3,
        "min": 0,
        "max": 1,
        "step": 0.05
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
    "type": "structure_break",
    "name": "Structure Break (BOS)",
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
        "name": "pivot",
        "default": 5,
        "min": 1,
        "max": 50,
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
    "type": "nr7_breakout",
    "name": "NR7 Breakout",
    "states": [
      "trend_up",
      "trend_down",
      "range"
    ],
    "uses": [
      "Price action",
      "EMA"
    ],
    "params": [
      {
        "name": "length",
        "default": 7,
        "min": 2,
        "max": 50,
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
    "type": "heikin_ashi",
    "name": "Heikin-Ashi Turn",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "Heikin-Ashi",
      "EMA"
    ],
    "params": [
      {
        "name": "run",
        "default": 3,
        "min": 1,
        "max": 20,
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
    "type": "engulfing",
    "name": "Engulfing",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "Price action",
      "RSI",
      "EMA"
    ],
    "params": [
      {
        "name": "dip",
        "default": 45,
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
    "type": "pin_bar",
    "name": "Pin Bar",
    "states": [
      "trend_up",
      "trend_down",
      "range"
    ],
    "uses": [
      "Price action",
      "EMA"
    ],
    "params": [
      {
        "name": "length",
        "default": 10,
        "min": 2,
        "max": 200,
        "step": 1
      },
      {
        "name": "wick",
        "default": 2,
        "min": 1,
        "max": 10,
        "step": 0.5
      },
      {
        "name": "trend",
        "default": 200,
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
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "rsi2_dip",
    "name": "RSI(2) Dip",
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
        "default": 2,
        "min": 2,
        "max": 50,
        "step": 1
      },
      {
        "name": "oversold",
        "default": 10,
        "min": 1,
        "max": 49,
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
        "name": "atr_mult",
        "default": 2.5,
        "min": 0.1,
        "max": 10,
        "step": 0.1
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
    "type": "williams_pullback",
    "name": "Williams %R Pullback",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "Williams %R",
      "EMA",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 14,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "zone",
        "default": 80,
        "min": 50,
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
    "type": "zscore_reversion",
    "name": "Z-Score Reversion",
    "states": [
      "range"
    ],
    "uses": [
      "SMA",
      "StDev",
      "ADX"
    ],
    "params": [
      {
        "name": "length",
        "default": 50,
        "min": 5,
        "max": 500,
        "step": 1
      },
      {
        "name": "z",
        "default": 2.5,
        "min": 0.5,
        "max": 6,
        "step": 0.1
      },
      {
        "name": "max_adx",
        "default": 20,
        "min": 5,
        "max": 80,
        "step": 1
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
    "type": "mfi_turn",
    "name": "MFI Turn",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "MFI",
      "EMA",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 14,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "zone",
        "default": 20,
        "min": 1,
        "max": 49,
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
    "type": "three_soldiers",
    "name": "Three Soldiers",
    "states": [
      "trend_up",
      "trend_down",
      "volatile"
    ],
    "uses": [
      "Price action",
      "Volume",
      "EMA"
    ],
    "params": [
      {
        "name": "size",
        "default": 0.5,
        "min": 0.1,
        "max": 5,
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
    "type": "contraction",
    "name": "Volatility Contraction",
    "states": [
      "trend_up",
      "trend_down",
      "range"
    ],
    "uses": [
      "ATR",
      "Donchian",
      "EMA"
    ],
    "params": [
      {
        "name": "length",
        "default": 10,
        "min": 2,
        "max": 200,
        "step": 1
      },
      {
        "name": "tight",
        "default": 0.7,
        "min": 0.1,
        "max": 1,
        "step": 0.05
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
    "type": "box_breakout",
    "name": "Box Breakout",
    "states": [
      "range",
      "volatile"
    ],
    "uses": [
      "Price action",
      "Volume",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 20,
        "min": 5,
        "max": 500,
        "step": 1
      },
      {
        "name": "box",
        "default": 4,
        "min": 0.5,
        "max": 20,
        "step": 0.5
      },
      {
        "name": "volume_mult",
        "default": 1.5,
        "min": 1,
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
    "type": "trix_cross",
    "name": "TRIX Cross",
    "states": [
      "trend_up",
      "trend_down"
    ],
    "uses": [
      "TRIX",
      "EMA",
      "ATR"
    ],
    "params": [
      {
        "name": "length",
        "default": 15,
        "min": 2,
        "max": 200,
        "step": 1
      },
      {
        "name": "signal",
        "default": 9,
        "min": 2,
        "max": 100,
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
    "modeDefaults": {
      "trend": {
        "scalping": 50,
        "daily": 200
      }
    }
  },
  {
    "type": "wide_bar",
    "name": "Wide-Range Bar",
    "states": [
      "trend_up",
      "trend_down",
      "range",
      "volatile"
    ],
    "uses": [
      "Price action",
      "Volume",
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
        "name": "size",
        "default": 2.5,
        "min": 1,
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
    "type": "trend_rider",
    "name": "Trend Rider",
    "states": [
      "trend_up",
      "trend_down",
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
        "default": 30,
        "min": 2,
        "max": 200,
        "step": 1
      },
      {
        "name": "enter",
        "default": 0.6,
        "min": 0.2,
        "max": 1,
        "step": 0.2
      },
      {
        "name": "atr_length",
        "default": 84,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "atr_mult",
        "default": 4,
        "min": 0.1,
        "max": 10,
        "step": 0.1
      },
      {
        "name": "reward",
        "default": 4,
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
