# Crypto ETF Heatmap

This project generates a heatmap for tokens in cryptocurrency categories using historical price and market cap data from the CoinMarketCap API.

## Description

This script creates a heatmap (treemap) for tokens in a selected category. The map displays market capitalization and price percentage changes for tokens over a specified period. The program excludes stablecoins and limits the display to the top 50 tokens by market capitalization.

## Features

- Uses the CoinMarketCap API to fetch cryptocurrency data.
- Retrieves historical price and market cap data.
- Excludes stablecoins (e.g., USDT, USDC) from analysis.
- Displays data in a heatmap with two decimal places for percentage change.
- Limits the display to the top 50 tokens by market capitalization in the selected category.
- Generates an HTML file with the visualization, which can be opened in a browser.

## Installation

1. Clone the repository or download the project files.
2. Install the required dependencies:

```bash
pip install -r requirements.txt
