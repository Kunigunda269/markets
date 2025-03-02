import asyncio
import aiohttp
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import logging
import os
import sys
import time
from datetime import datetime, timedelta
import requests
from functools import lru_cache

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Configuration
API_KEY = "123"
HEADERS = {"X-CMC_PRO_API_KEY": API_KEY}
BASE_URL_HISTORICAL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
SEARCH_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/map"
OUTPUT_PATH = r"C:\Users\Main\Pitonio\crypto_etf"

# Logging setup
logging.basicConfig(
    filename='crypto_analysis.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def log_and_print(message, level="info"):
    """Logging and console output."""
    print(f"[{level.upper()}] {message}")
    getattr(logging, level)(message)


@lru_cache(maxsize=100)
def search_token(token_name):
    """Search token by name and return its ID."""
    log_and_print(f"Searching for token: {token_name}")
    try:
        response = requests.get(
            SEARCH_URL,
            headers=HEADERS,
            params={"symbol": token_name.upper()}
        )
        if response.status_code == 200:
            data = response.json()
            if data["data"]:
                token = next((t for t in data["data"] if t["symbol"].upper() == token_name.upper()), None)
                if token:
                    log_and_print(f"Found token: {token['name']} (ID: {token['id']})")
                    return token["id"], token["name"]
    except Exception as e:
        log_and_print(f"Error searching token: {e}", "error")
    return None, None


@lru_cache(maxsize=1000)
async def fetch_historical_data(session, crypto_id, time_start, time_end):
    """Fetch historical price data."""
    log_and_print(f"Fetching historical data for ID: {crypto_id}")
    params = {
        "id": crypto_id,
        "time_start": time_start,
        "time_end": time_end,
        "interval": "daily",
        "convert": "USD"
    }

    try:
        async with session.get(BASE_URL_HISTORICAL, headers=HEADERS, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return [(quote["timestamp"], quote["quote"]["USD"]["price"])
                        for quote in data["data"]["quotes"]]
            else:
                log_and_print(f"Error fetching historical data: {response.status}", "error")
    except Exception as e:
        log_and_print(f"Exception in historical data fetch: {e}", "error")
    return []


async def retry_with_backoff(func, *args, max_retries=3, base_delay=66):
    """Retry function with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return await func(*args)
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            delay = base_delay * (2 ** attempt)
            log_and_print(f"Attempt {attempt + 1} failed. Retrying in {delay} seconds...", "warning")
            await asyncio.sleep(delay)


@lru_cache(maxsize=1000)
async def fetch_fear_greed_index(start_date, end_date):
    """Fetch Fear & Greed Index data."""
    log_and_print("Fetching Fear & Greed Index data")
    url = "https://api.alternative.me/fng/?limit=0&format=json"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()

                    # Convert dates for comparison - remove time part for comparison
                    start_dt = datetime.strptime(start_date.split("T")[0], "%Y-%m-%d")
                    end_dt = datetime.strptime(end_date.split("T")[0], "%Y-%m-%d")

                    result = []
                    for item in data.get("data", []):
                        try:
                            # Convert timestamp to datetime
                            timestamp = int(item["timestamp"])
                            date = datetime.fromtimestamp(timestamp)

                            # Check if date is in range
                            if start_dt <= date <= end_dt:
                                date_str = date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                                value = int(item["value"])
                                result.append((date_str, value))
                                log_and_print(f"Processed Fear & Greed data: {date_str} - {value}")
                        except (KeyError, ValueError) as e:
                            log_and_print(f"Error processing data point: {e}", "error")

                    # Sort by date
                    result.sort(key=lambda x: x[0])
                    return result
                else:
                    log_and_print(f"Failed to fetch Fear & Greed data: {response.status}", "error")
    except Exception as e:
        log_and_print(f"Error fetching Fear & Greed Index: {e}", "error")
    return []


async def fetch_btc_dominance(session, start_date, end_date):
    """Fetch BTC dominance data."""
    log_and_print("Fetching BTC dominance data")
    url = "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/historical"
    params = {
        "time_start": start_date,
        "time_end": end_date,
        "interval": "daily",
        "convert": "USD"
    }

    try:
        async with session.get(url, headers=HEADERS, params=params) as response:
            if response.status == 200:
                data = await response.json()
                result = []
                if "data" in data and "quotes" in data["data"]:
                    for quote in data["data"]["quotes"]:
                        timestamp = quote.get("timestamp")
                        dominance = quote.get("btc_dominance")
                        if timestamp and dominance is not None:
                            result.append((timestamp, float(dominance)))
                            log_and_print(f"Processed dominance data: {timestamp} - {dominance}%")
                    return result
                else:
                    log_and_print("Invalid dominance data format", "error")
            else:
                log_and_print(f"Failed to fetch dominance data. Status: {response.status}", "error")
    except Exception as e:
        log_and_print(f"Error fetching BTC dominance: {e}", "error")
    return []


async def create_interactive_plot(token_name, price_data, fear_greed_data, dominance_data, start_date, end_date):
    """Create interactive plot with Plotly."""
    log_and_print("Creating interactive plot")

    title = f"{token_name.upper()} Advanced Fear & Greed Index ({start_date} - {end_date})"

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Price data (right y-axis)
    if price_data:
        fig.add_trace(
            go.Scatter(
                x=[x[0] for x in price_data],
                y=[x[1] for x in price_data],
                name="Price (USD)",
                line=dict(color="blue", width=2),
                hovertemplate="<b>Date:</b> %{x}<br><b>Price:</b> $%{y:,.2f}<extra></extra>"
            ),
            secondary_y=True
        )

    # Fear & Greed Index (left y-axis)
    if fear_greed_data:
        fig.add_trace(
            go.Scatter(
                x=[x[0] for x in fear_greed_data],
                y=[x[1] for x in fear_greed_data],
                name="Fear & Greed Index",
                line=dict(color="green", width=2),
                hovertemplate="<b>Date:</b> %{x}<br><b>Fear & Greed:</b> %{y}<extra></extra>"
            ),
            secondary_y=False
        )

    # BTC Dominance (left y-axis)
    if dominance_data:
        fig.add_trace(
            go.Scatter(
                x=[x[0] for x in dominance_data],
                y=[x[1] for x in dominance_data],
                name="BTC Dominance %",
                line=dict(color="purple", width=2),
                hovertemplate="<b>Date:</b> %{x}<br><b>BTC Dominance:</b> %{y:.2f}%<extra></extra>"
            ),
            secondary_y=False
        )

    # Update layout
    fig.update_layout(
        title=title,
        title_x=0.5,
        title_y=0.95,
        plot_bgcolor='white',
        hovermode='closest',  # Changed to closest for better individual trace hovering
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01
        ),
        hoverlabel=dict(
            bgcolor="white",
            font_size=12
        )
    )

    # Update axes
    fig.update_xaxes(
        title_text="Date",
        gridcolor='lightgrey',
        showgrid=True
    )

    # Left Y-axis (Fear & Greed and Dominance)
    fig.update_yaxes(
        title_text="Fear & Greed Index / BTC Dominance %",
        gridcolor='lightgrey',
        showgrid=True,
        range=[0, 100],
        secondary_y=False
    )

    # Right Y-axis (Price)
    fig.update_yaxes(
        title_text="Price (USD)",
        gridcolor='lightgrey',
        showgrid=True,
        secondary_y=True
    )

    return fig


async def main():
    log_and_print("Starting the analysis process")

    # Get token input
    token_name = input("Enter token name: ").strip()
    log_and_print(f"Processing token: {token_name}")
    token_id, token_full_name = search_token(token_name)
    if not token_id:
        log_and_print("Token not found", "error")
        return

    # Get date range
    start_date = input("Enter start date (YYYY-MM-DD): ").strip() + "T00:00:00Z"
    end_date = input("Enter end date (YYYY-MM-DD): ").strip() + "T23:59:59Z"
    log_and_print(f"Date range: {start_date} to {end_date}")

    async with aiohttp.ClientSession() as session:
        log_and_print("Starting data collection...")

        # Fetch data with retries
        price_data = await retry_with_backoff(fetch_historical_data, session, token_id, start_date, end_date)
        log_and_print(f"Collected price data points: {len(price_data)}")
        await asyncio.sleep(2)  # Small delay between API calls

        fear_greed_data = await retry_with_backoff(fetch_fear_greed_index, start_date, end_date)
        log_and_print(f"Collected fear/greed data points: {len(fear_greed_data)}")
        await asyncio.sleep(2)  # Small delay between API calls

        dominance_data = await retry_with_backoff(fetch_btc_dominance, session, start_date, end_date)
        log_and_print(f"Collected dominance data points: {len(dominance_data)}")

        # Create and save the plot
        fig = await create_interactive_plot(
            token_full_name or token_name.upper(),
            price_data,
            fear_greed_data,
            dominance_data,
            start_date[:10],
            end_date[:10]
        )

        output_file = os.path.join(OUTPUT_PATH, f"{token_name}_analysis_{start_date[:10]}_{end_date[:10]}.html")
        fig.write_html(output_file)
        log_and_print(f"Plot saved to: {output_file}")

        log_and_print(f"Analysis completed. Results saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
