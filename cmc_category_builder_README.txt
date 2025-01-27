# Crypto Category Analysis Tool

A Python script for analyzing and visualizing cryptocurrency data across different categories.

## Features

- Excel data processing
- Category-based analysis
- Average price calculation
- Market cap analysis
- Interactive visualization
- Data export functionality

## Prerequisites

- Python 3.8+
- Excel files with cryptocurrency data
- Windows OS (for default file paths)

## Installation

1. Clone the repository:
bash
git clone <repository-url>
cd crypto-category-analysis

2. Install dependencies:
bash
pip install -r requirements.txt

3. Configure input files:
   - Place category details file (`category_tokens_details_2.xlsx`)
   - Add result files with naming pattern: `result_YYYY-MM-DD_to_YYYY-MM-DD.xlsx`

## File Structure

### Input Files

1. Category File (`category_tokens_details_2.xlsx`):
   - Required columns: `Symbol`, `Category`

2. Result Files:
   - Naming pattern: `result_YYYY-MM-DD_to_YYYY-MM-DD.xlsx`
   - Required columns: `Symbol`, `Price (USD)`, `Market Cap`

### Output Files

- `balanced_data_output_avg.xlsx`: Contains processed data with averages

## Usage

1. Update file paths in the script:
python
category_file = "path/to/category_file.xlsx"
result_files = ["path/to/result_files.xlsx"]


2. Run the script:
bash
python main.py


3. View results:
   - Excel output file with processed data
   - Interactive price chart in browser

## Data Processing

The script performs the following operations:
1. Reads category and token data
2. Processes multiple result files
3. Calculates average prices per category
4. Generates time series analysis
5. Creates interactive visualization

## Visualization

The tool generates an interactive line chart showing:
- Average price trends by category
- Time-based price evolution
- Category comparisons

## Error Handling

- File existence validation
- Date extraction verification
- Data format checking
- Empty data handling

## Notes

- Ensure consistent file naming
- Check file permissions
- Verify Excel file formats
- Monitor memory usage with large datasets


## Author

https://t.me/kunigunda_production

## Acknowledgments

- Plotly visualization library
- Pandas development team
