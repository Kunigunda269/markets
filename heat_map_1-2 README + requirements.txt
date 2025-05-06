Crypto Market Heatmap
This Python script allows you to create a heatmap visualizing the top 100 cryptocurrencies based on their market capitalization and percentage price change over a specific date range. It fetches historical data using the CoinMarketCap API and generates an interactive heatmap using Plotly.

Features
Fetches data from CoinMarketCap API: Retrieves the latest data on the top 100 cryptocurrencies.
Calculates percentage price change: Calculates the percentage change in price from the start to the end of a specified time period.
Generates a dynamic heatmap: Visualizes the cryptocurrencies with the largest market caps and their price change over the selected period.
Adaptive visual representation: The heatmap uses logarithmic scaling and custom color coding for price changes.
Requirements
To run this script, you need to have Python 3.7 or higher installed, along with the necessary dependencies.

Installation
Clone the repository or download the script.

Install the required libraries:
pip install -r requirements.txt

Run the script:
python heat_map.py

The script will prompt for the following inputs:

Whether to run a test query.
The cryptocurrency symbol (e.g., BTC, ETH).
The start and end dates for the historical data.
After obtaining the data, the script will generate a heatmap and save it as an HTML file (heatmap.html).

Usage
Once the data is fetched, the script creates a heatmap using Plotly, which shows:

The market cap of each cryptocurrency.
The percentage change in price over the selected period.
Market dominance (calculated based on the market cap).
Sample Output
The heatmap will be saved as an interactive HTML file that you can open in any browser.

License
This project is licensed under the MIT License.