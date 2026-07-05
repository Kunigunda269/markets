# crypto

Market-data pipelines and analytics built on the CoinMarketCap Pro API
(plus on-chain / TVL sources). Async where it pays off (`aiohttp`), Plotly for
the interactive output.

## Highlights

- **Interactive dashboards** — `crypto_ultimate_dashboard.py`,
  `crypto_comprehensive_dashboard.py`: multi-metric Plotly dashboards over the
  CMC universe.
- **ETF-style basket analysis** — `crypto_etf.py`, `crypto_etf_dynamic.py`:
  build and analyze weighted baskets of tokens by category.
- **Category tooling** — `cmc_category_builder.py`,
  `cmc_category_downloader.py`: pull and assemble category-level datasets.
- **Market structure** — `cmc_market_cap_liquidity.py`,
  `cmc_volume_monthly.py`, `combined_tvl_all_chains.py`.
- **Sentiment / regime** — `fear_greed_dominance.py`,
  `market_sentiment_heatmap.py`, `heatmap.py`, `heatmap_v2.py`,
  `category_heatmap.py`.
- **Misc** — `blockchain_report_api.py`, `mexc_assessments.py`.

## Run

```bash
cp ../.env.example ../.env      # set CMC_API_KEY, OUTPUT_DIR, DATA_DIR
pip install -r requirements.txt
python cmc_market_cap_liquidity.py
```
