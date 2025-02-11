Crypto ETF Data Processor

This script is designed to fetch and visualize cryptocurrency data using the CoinMarketCap API.

Features

Retrieve token metadata by ticker

Download historical data on market cap and liquidity

Validate and adjust date ranges

Visualize data with interactive Plotly charts

Export data to Excel

Installation

Clone the repository or copy the code.

Install dependencies:

pip install -r requirements.txt

Configuration

Ensure you have a CoinMarketCap API key.

Set the variables in the code:

API_KEY — your API key.

OUTPUT_FOLDER — the path for saving files.

Usage

Run the script:

python script.py

Enter the token ticker (e.g., BTC).

Specify the date range in the YYYY-MM-DD format.

Results will be saved in the specified directory:

Interactive HTML chart

Excel file with data

Example

Enter ETH and the date range 2023-01-01 — 2023-01-31.

Get a chart showing market cap and liquidity for January 2023.

Important

Request limit: no more than 30 requests per minute (configurable).

The script automatically adjusts dates if invalid values are provided.

Dependencies

aiohttp — asynchronous HTTP requests

pandas — data processing

plotly — data visualization

Feedback

For questions and suggestions, please open an issue or create a pull request.