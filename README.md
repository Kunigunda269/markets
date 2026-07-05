# markets

A toolkit of market-data and analytics utilities I use for research across
crypto, equities/ETFs and fixed income. These are the **research and tooling**
side of my work — data pipelines, metrics, and interactive dashboards — not my
live trading strategies.

Everything is Python. API keys and local paths are read from environment
variables (see `.env.example`); nothing sensitive is committed.

## Structure

| Folder | What's inside |
|--------|---------------|
| [`crypto/`](crypto/) | CoinMarketCap data pipelines, market-cap/liquidity analysis, category builders, TVL aggregation, fear & greed / dominance, sentiment heatmaps, and interactive Plotly dashboards |
| [`portfolio/`](portfolio/) | Portfolio volatility analyzer — returns, benchmark beta, Sharpe, and risk stats, with support for option positions |
| [`etfs/`](etfs/) | ETF metric extraction and screening helpers |
| [`bonds/`](bonds/) | Bond pricing / yield calculator |

## Setup

```bash
git clone https://github.com/Kunigunda269/markets.git
cd markets
cp .env.example .env          # then fill in your keys
pip install -r crypto/requirements.txt   # or the folder you need
```

Set `CMC_API_KEY`, `OUTPUT_DIR` and `DATA_DIR` in `.env` before running the
scripts that hit the CoinMarketCap API.

## Stack

Python · pandas · NumPy · aiohttp · Plotly · SciPy · matplotlib
