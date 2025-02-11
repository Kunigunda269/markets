README

Cryptocurrency Historical Data Fetcher

This script fetches historical cryptocurrency trading volume data using the CoinMarketCap API, processes it, visualizes it with a line chart, and saves the data to an Excel file.

Features

Fetch historical trading volume data for any cryptocurrency.

Visualize daily trading volume using interactive Plotly charts.

Export data to an Excel file for further analysis.

Robust logging to track process execution and errors.

Prerequisites

Python 3.7+

A valid CoinMarketCap API key (replace the placeholder in the script).

Required Python libraries listed in requirements.txt.

Installation

Clone the repository or download the script.

Navigate to the project directory.

Install dependencies:

pip install -r requirements.txt

Configuration

Replace the API_KEY variable in the script with your CoinMarketCap API key.

Set the OUTPUT_FOLDER path to a valid directory where you want the output files saved.

Usage

Run the script:

python script_name.py

Input the required details when prompted:

Ticker Symbol (e.g., BTC, ETH)

Start Date (format: YYYY-MM-DD)

End Date (format: YYYY-MM-DD)

Output

Interactive Plotly Line Chart: Displays daily trading volume.

Excel File: Saves trading volume data in .xlsx format.

Log File: Logs execution details and errors in crypto_combined.log.

Example

python crypto_data_fetcher.py
Введите тикер токена (например, BTC): BTC
Введите начальную дату (YYYY-MM-DD): 2023-01-01
Введите конечную дату (YYYY-MM-DD): 2023-12-31

License

This project is licensed under the MIT License.

Disclaimer

This script is for educational purposes only. Use at your own risk.