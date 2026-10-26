// Copy of the backend catalog (backend/app/catalog.py) for the sample-data preview only.
// The real app asks the backend. A test checks this copy is not out of date.
import type { CatalogSpec } from "./types.ts";

export const MOCK_CATALOG: CatalogSpec[] = [
  {
    "type": "ema",
    "name": "EMA",
    "pane": "price",
    "params": [
      {
        "name": "length",
        "default": 9,
        "min": 1,
        "max": 500,
        "step": 1
      }
    ],
    "outputs": [
      {
        "key": "value",
        "color": "#f7c948",
        "style": "line"
      }
    ],
    "levels": [],
    "scale": null,
    "candle_colors": false
  },
  {
    "type": "sma",
    "name": "SMA",
    "pane": "price",
    "params": [
      {
        "name": "length",
        "default": 9,
        "min": 1,
        "max": 500,
        "step": 1
      }
    ],
    "outputs": [
      {
        "key": "value",
        "color": "#2196f3",
        "style": "line"
      }
    ],
    "levels": [],
    "scale": null,
    "candle_colors": false
  },
  {
    "type": "wma",
    "name": "WMA",
    "pane": "price",
    "params": [
      {
        "name": "length",
        "default": 9,
        "min": 1,
        "max": 500,
        "step": 1
      }
    ],
    "outputs": [
      {
        "key": "value",
        "color": "#f06292",
        "style": "line"
      }
    ],
    "levels": [],
    "scale": null,
    "candle_colors": false
  },
  {
    "type": "bb",
    "name": "BB",
    "pane": "price",
    "params": [
      {
        "name": "length",
        "default": 20,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "mult",
        "default": 2,
        "min": 0.1,
        "max": 10,
        "step": 0.1
      }
    ],
    "outputs": [
      {
        "key": "basis",
        "color": "#ff6d00",
        "style": "line"
      },
      {
        "key": "upper",
        "color": "#2962ff",
        "style": "line"
      },
      {
        "key": "lower",
        "color": "#2962ff",
        "style": "line"
      }
    ],
    "levels": [],
    "scale": null,
    "candle_colors": false
  },
  {
    "type": "supertrend",
    "name": "SuperTrend",
    "pane": "price",
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
      }
    ],
    "outputs": [
      {
        "key": "up",
        "color": "#089981",
        "style": "line"
      },
      {
        "key": "down",
        "color": "#f23645",
        "style": "line"
      }
    ],
    "levels": [],
    "scale": null,
    "candle_colors": false
  },
  {
    "type": "volume",
    "name": "Vol",
    "pane": "own",
    "params": [],
    "outputs": [
      {
        "key": "volume",
        "color": "#26a69a",
        "style": "histogram"
      }
    ],
    "levels": [],
    "scale": null,
    "candle_colors": true
  },
  {
    "type": "rsi",
    "name": "RSI",
    "pane": "own",
    "params": [
      {
        "name": "length",
        "default": 14,
        "min": 2,
        "max": 500,
        "step": 1
      }
    ],
    "outputs": [
      {
        "key": "rsi",
        "color": "#7e57c2",
        "style": "line"
      }
    ],
    "levels": [
      70,
      30
    ],
    "scale": [
      0,
      100
    ],
    "candle_colors": false
  },
  {
    "type": "macd",
    "name": "MACD",
    "pane": "own",
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
      }
    ],
    "outputs": [
      {
        "key": "hist",
        "color": "#26a69a",
        "style": "histogram"
      },
      {
        "key": "macd",
        "color": "#2962ff",
        "style": "line"
      },
      {
        "key": "signal",
        "color": "#ff6d00",
        "style": "line"
      }
    ],
    "levels": [],
    "scale": null,
    "candle_colors": false
  },
  {
    "type": "stoch",
    "name": "Stoch",
    "pane": "own",
    "params": [
      {
        "name": "k_length",
        "default": 14,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "k_smoothing",
        "default": 1,
        "min": 1,
        "max": 100,
        "step": 1
      },
      {
        "name": "d_smoothing",
        "default": 3,
        "min": 1,
        "max": 100,
        "step": 1
      }
    ],
    "outputs": [
      {
        "key": "k",
        "color": "#2962ff",
        "style": "line"
      },
      {
        "key": "d",
        "color": "#ff6d00",
        "style": "line"
      }
    ],
    "levels": [
      80,
      20
    ],
    "scale": [
      0,
      100
    ],
    "candle_colors": false
  },
  {
    "type": "stochrsi",
    "name": "Stoch RSI",
    "pane": "own",
    "params": [
      {
        "name": "k",
        "default": 3,
        "min": 1,
        "max": 100,
        "step": 1
      },
      {
        "name": "d",
        "default": 3,
        "min": 1,
        "max": 100,
        "step": 1
      },
      {
        "name": "rsi_length",
        "default": 14,
        "min": 2,
        "max": 500,
        "step": 1
      },
      {
        "name": "stoch_length",
        "default": 14,
        "min": 1,
        "max": 500,
        "step": 1
      }
    ],
    "outputs": [
      {
        "key": "k",
        "color": "#2962ff",
        "style": "line"
      },
      {
        "key": "d",
        "color": "#ff6d00",
        "style": "line"
      }
    ],
    "levels": [
      80,
      20
    ],
    "scale": [
      0,
      100
    ],
    "candle_colors": false
  },
  {
    "type": "atr",
    "name": "ATR",
    "pane": "own",
    "params": [
      {
        "name": "length",
        "default": 14,
        "min": 1,
        "max": 500,
        "step": 1
      }
    ],
    "outputs": [
      {
        "key": "atr",
        "color": "#b71c1c",
        "style": "line"
      }
    ],
    "levels": [],
    "scale": null,
    "candle_colors": false
  },
  {
    "type": "dmi",
    "name": "DMI",
    "pane": "own",
    "params": [
      {
        "name": "length",
        "default": 14,
        "min": 1,
        "max": 500,
        "step": 1
      },
      {
        "name": "smoothing",
        "default": 14,
        "min": 1,
        "max": 500,
        "step": 1
      }
    ],
    "outputs": [
      {
        "key": "adx",
        "color": "#ff6d00",
        "style": "line"
      },
      {
        "key": "plus",
        "color": "#2962ff",
        "style": "line"
      },
      {
        "key": "minus",
        "color": "#f23645",
        "style": "line"
      }
    ],
    "levels": [
      25,
      20
    ],
    "scale": null,
    "candle_colors": false
  }
];
