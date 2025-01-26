# Crypto Category Analysis Tool

A Python-based tool for analyzing cryptocurrency tokens and their categories using the CoinMarketCap API. The tool provides historical data analysis, category comparisons, and interactive visualizations.

## Features

- Asynchronous API requests to CoinMarketCap
- Historical price and market cap data retrieval
- Category-based token analysis
- Interactive visualization with Plotly
- Excel report generation
- Logging system for error tracking

## Prerequisites

- Python 3.8 or higher
- CoinMarketCap API key
- Windows OS (for default file paths)

## Installation

1. Clone the repository:
bash
git clone <repository-url>
cd crypto-category-analysis

2. Install required packages:
bash
pip install -r requirements.txt

3. Configure the environment:
   - Update the API_KEY in the code with your CoinMarketCap API key
   - Adjust file paths in DataProcessor class if needed

## Usage

1. Run the script:
bash
python main.py

2. Follow the interactive prompts:
   - Enter token ID or ticker symbol
   - Input date range for test analysis
   - Confirm full analysis execution

3. Output files:
   - Token data: `token_data_<symbol>_<timestamp>.xlsx`
   - Category analysis: `category_analysis_<symbol>_<timestamp>.xlsx`
   - Interactive visualization: `analysis_<symbol>_<timestamp>.html`
   - Debug data: `categories_debug_<timestamp>.xlsx`
   - Log file: `crypto_api.log`

## File Structure

- `category_tokens_details_2.xlsx`: Master file containing token categories
- `result_<date>_to_<date>.xlsx`: Historical result files for analysis
- Generated files are saved in the specified directory

## Classes

### APIHandler
Manages API connections and data retrieval from CoinMarketCap.

### DataProcessor
Processes and analyzes token and category data.

### Visualizer
Creates interactive visualizations using Plotly.

## Error Handling

- Comprehensive error logging in `crypto_api.log`
- User-friendly error messages in console
- Data validation at multiple stages

## Notes

- API rate limits apply based on your CoinMarketCap subscription
- Large datasets may require additional processing time
- Ensure proper file permissions in the save directory


## Author

https://t.me/kunigunda_productionv

## Acknowledgments

- CoinMarketCap API
- Plotly visualization library
- Python async community

This documentation provides a comprehensive overview of your project, its requirements, and usage instructions. You may want to customize the following sections:
Repository URL
License information
Author details
Specific configuration requirements for your environment
