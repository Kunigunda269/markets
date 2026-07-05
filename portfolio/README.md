# portfolio

**`portfolio_volatility.py`** — a portfolio volatility & risk analyzer.

Given a set of positions (equities, ETFs, and option legs with
strike/expiry/type), it pulls price history, then computes return series,
benchmark beta, annualized volatility, Sharpe (configurable risk-free rate),
and drawdown, with Plotly visualizations.

```bash
cp ../.env.example ../.env
pip install -r requirements.txt
python portfolio_volatility.py
```

Data comes from Yahoo Finance via `yfinance`.
