README
Crypto Fear, Greed, and Dominance Analysis
This script analyzes the price, Fear & Greed Index, and Bitcoin dominance data for a given cryptocurrency over a specific date range. It fetches data from the CoinMarketCap and Alternative.me APIs, and generates an interactive plot using Plotly.

Features
Fetches historical price data for any token from CoinMarketCap.
Retrieves Fear & Greed Index data from Alternative.me.
Fetches Bitcoin dominance data.
Generates an interactive plot with price, Fear & Greed Index, and Bitcoin dominance.
Handles retries with exponential backoff for API requests.
Requirements
This script requires the following Python libraries:

aiohttp: for asynchronous HTTP requests.
requests: for synchronous HTTP requests.
pandas: for handling data.
plotly: for plotting interactive charts.
logging: for logging API errors and important messages.
Installation
To install the required libraries, run the following command:
pip install -r requirements.txt

Usage
Clone this repository or download the script.
Install the necessary dependencies by running pip install -r requirements.txt.
Run the script:
python fear_greed_dominance.py

Enter the token name (e.g., "BTC") when prompted.
Enter the start and end date for the analysis in the format YYYY-MM-DD.
The script will generate and save an HTML file containing an interactive plot showing the price, Fear & Greed Index, and Bitcoin dominance.
Configuration
The API keys for CoinMarketCap and Alternative.me are predefined in the script.
You can modify the OUTPUT_PATH variable to change where the output HTML files will be saved.
