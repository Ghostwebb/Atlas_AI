"""Generate the static demo dataset used by ATLAS AI Phase 2.

Usage (from backend/):
    ./.venv/bin/python scripts/generate_demo_dataset.py

PROVENANCE
- Prices are SYNTHETIC. They come from a geometric random walk with a fixed
  per-symbol seed, so the output is identical on every run.
- The drift, volatility and starting prices below are illustrative parameters
  chosen for the demo. They are NOT market data and do not reflect any real
  company's history.
- Fundamentals are hand-written DEMO values, not reported financials.
- Dates are business days (weekends only; exchange holidays are ignored).

The generated file (app/data/demo_dataset.json) is the single source of truth
at runtime. Regenerating with the same script produces the same file.
"""

import json
import math
import random
from datetime import date
from pathlib import Path

import pandas as pd

SEED_PREFIX = "atlas-ai-demo-v1"
BARS_PER_SYMBOL = 120
LAST_DATE = "2026-09-30"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "demo_dataset.json"

# symbol -> generation parameters (synthetic) and demo fundamentals
SYMBOLS: dict[str, dict] = {
    "AAPL": {
        "companyName": "Apple Inc.", "startPrice": 190.0, "dailyDrift": 0.0003,
        "dailyVolatility": 0.014, "baseVolume": 52_000_000,
        "fundamentals": {"revenueGrowth": 0.06, "profitMargin": 0.25, "peRatio": 31.5, "earningsGrowth": 0.09},
    },
    "MSFT": {
        "companyName": "Microsoft Corporation", "startPrice": 410.0, "dailyDrift": 0.0005,
        "dailyVolatility": 0.013, "baseVolume": 22_000_000,
        "fundamentals": {"revenueGrowth": 0.14, "profitMargin": 0.36, "peRatio": 34.2, "earningsGrowth": 0.18},
    },
    "NVDA": {
        "companyName": "NVIDIA Corporation", "startPrice": 180.0, "dailyDrift": 0.0012,
        "dailyVolatility": 0.032, "baseVolume": 240_000_000,
        "fundamentals": {"revenueGrowth": 0.38, "profitMargin": 0.45, "peRatio": 44.0, "earningsGrowth": 0.52},
    },
    "TSLA": {
        "companyName": "Tesla, Inc.", "startPrice": 250.0, "dailyDrift": -0.0002,
        "dailyVolatility": 0.040, "baseVolume": 110_000_000,
        "fundamentals": {"revenueGrowth": 0.04, "profitMargin": 0.07, "peRatio": 58.0, "earningsGrowth": -0.12},
    },
    "AMZN": {
        "companyName": "Amazon.com, Inc.", "startPrice": 185.0, "dailyDrift": 0.0006,
        "dailyVolatility": 0.018, "baseVolume": 45_000_000,
        "fundamentals": {"revenueGrowth": 0.10, "profitMargin": 0.09, "peRatio": 48.0, "earningsGrowth": 0.22},
    },
    "GOOGL": {
        "companyName": "Alphabet Inc.", "startPrice": 150.0, "dailyDrift": 0.0004,
        "dailyVolatility": 0.016, "baseVolume": 28_000_000,
        "fundamentals": {"revenueGrowth": 0.11, "profitMargin": 0.27, "peRatio": 24.0, "earningsGrowth": 0.14},
    },
    "META": {
        "companyName": "Meta Platforms, Inc.", "startPrice": 500.0, "dailyDrift": 0.0007,
        "dailyVolatility": 0.020, "baseVolume": 16_000_000,
        "fundamentals": {"revenueGrowth": 0.15, "profitMargin": 0.34, "peRatio": 27.0, "earningsGrowth": 0.20},
    },
}


def generate_bars(symbol: str, params: dict) -> list[dict]:
    # str seeds are hashed deterministically by Python's random module,
    # independent of PYTHONHASHSEED.
    rng = random.Random(f"{SEED_PREFIX}-{symbol}")
    dates = pd.bdate_range(end=LAST_DATE, periods=BARS_PER_SYMBOL)

    bars: list[dict] = []
    previous_close = params["startPrice"]
    for index, timestamp in enumerate(dates):
        if index == 0:
            open_price = params["startPrice"]
            close_price = params["startPrice"]
        else:
            open_price = previous_close * (1 + rng.gauss(0, 0.003))
            log_return = params["dailyDrift"] + params["dailyVolatility"] * rng.gauss(0, 1)
            close_price = previous_close * math.exp(log_return)

        high = max(open_price, close_price) * (1 + abs(rng.gauss(0, 0.006)))
        low = min(open_price, close_price) * (1 - abs(rng.gauss(0, 0.006)))
        volume = int(params["baseVolume"] * rng.uniform(0.8, 1.2))

        bars.append(
            {
                "date": timestamp.date().isoformat(),
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close_price, 2),
                "volume": volume,
            }
        )
        previous_close = close_price
    return bars


def build_dataset() -> dict:
    symbols_block = {}
    for symbol, params in SYMBOLS.items():
        symbols_block[symbol] = {
            "companyName": params["companyName"],
            "fundamentals": params["fundamentals"],
            "bars": generate_bars(symbol, params),
        }

    return {
        "meta": {
            "dataSource": "demo_dataset",
            "isSimulated": True,
            "description": (
                "SYNTHETIC demo data for ATLAS AI. Prices are generated from a "
                "seeded random walk and are not real market data. Fundamentals "
                "are demo values. Do not use for investment decisions."
            ),
            "generator": "backend/scripts/generate_demo_dataset.py",
            "seedPrefix": SEED_PREFIX,
            "barsPerSymbol": BARS_PER_SYMBOL,
            "lastDate": LAST_DATE,
            "calendar": "business days (weekends excluded, holidays ignored)",
        },
        "symbols": symbols_block,
    }


def main() -> None:
    dataset = build_dataset()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(dataset, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(dataset['symbols'])} symbols, {BARS_PER_SYMBOL} bars each)")


if __name__ == "__main__":
    main()
