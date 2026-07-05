# -*- coding: utf-8 -*-
"""
Crypto Market Sentiment Analyzer
Practical implementation using CoinMarketCap API
"""

import asyncio
import aiohttp
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.offline as pyo
import numpy as np
from datetime import datetime, timedelta
import os
import sys
import logging

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# === CONFIGURATION ===
API_KEY = os.getenv("CMC_API_KEY", "")
HEADERS = {"X-CMC_PRO_API_KEY": API_KEY}
BASE_URL = "https://pro-api.coinmarketcap.com"
OUTPUT_FOLDER = os.getenv("OUTPUT_DIR", "output")

# Create directory
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Logging
logging.basicConfig(
    filename=os.path.join(OUTPUT_FOLDER, "market_sentiment.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

class MarketSentimentAnalyzer:
    """Crypto Market Sentiment Analyzer"""
    
    def __init__(self):
        self.session = None
        
    async def get_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    async def fetch_market_data(self, limit=100):
        """Get current market data"""
        session = await self.get_session()
        endpoint = f"{BASE_URL}/v1/cryptocurrency/listings/latest"
        params = {"limit": limit, "convert": "USD"}
        
        async with session.get(endpoint, headers=HEADERS, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data['data']
            else:
                logging.error(f"API Error: {response.status}")
                return None
    
    async def fetch_global_metrics(self):
        """Get global market metrics"""
        session = await self.get_session()
        endpoint = f"{BASE_URL}/v1/global-metrics/quotes/latest"
        params = {"convert": "USD"}
        
        async with session.get(endpoint, headers=HEADERS, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data['data']
            else:
                logging.error(f"Global metrics fetch error: {response.status}")
                return None
    
    def calculate_sentiment_score(self, market_data):
        """Calculate market sentiment index"""
        if not market_data:
            return None
            
        sentiment_factors = {
            'green_coins': 0,  # Number of growing coins
            'red_coins': 0,    # Number of falling coins
            'high_volume': 0,  # High trading volume
            'volatility': 0    # Average volatility
        }
        
        changes_24h = []
        volumes = []
        market_caps = []
        valid_coins = 0
        
        print(f"\n=== DEBUG: Processing {len(market_data)} coins ===")
        
        for i, crypto in enumerate(market_data[:10]):  # Debug first 10 coins
            change_24h = crypto['quote']['USD']['percent_change_24h']
            volume_24h = crypto['quote']['USD']['volume_24h']
            market_cap = crypto['quote']['USD']['market_cap']
            symbol = crypto['symbol']
            
            print(f"{symbol}: Change={change_24h:.2f}%, Volume=${volume_24h/1e9:.1f}B, Cap=${market_cap/1e9:.1f}B")
            
            if change_24h is not None:
                changes_24h.append(change_24h)
                valid_coins += 1
                if change_24h > 0:
                    sentiment_factors['green_coins'] += 1
                elif change_24h < 0:
                    sentiment_factors['red_coins'] += 1
                # Note: coins with exactly 0% change are neither green nor red
            
            if volume_24h:
                volumes.append(volume_24h)
            
            if market_cap:
                market_caps.append(market_cap)
        
        # Process all remaining coins (without debug output)
        for crypto in market_data[10:]:
            change_24h = crypto['quote']['USD']['percent_change_24h']
            volume_24h = crypto['quote']['USD']['volume_24h']
            market_cap = crypto['quote']['USD']['market_cap']
            
            if change_24h is not None:
                changes_24h.append(change_24h)
                valid_coins += 1
                if change_24h > 0:
                    sentiment_factors['green_coins'] += 1
                elif change_24h < 0:
                    sentiment_factors['red_coins'] += 1
            
            if volume_24h:
                volumes.append(volume_24h)
            
            if market_cap:
                market_caps.append(market_cap)
        
        # Calculate index components
        total_coins = len(changes_24h)
        if total_coins > 0:
            green_ratio = sentiment_factors['green_coins'] / total_coins
            avg_change = np.mean(changes_24h)
            volatility = np.std(changes_24h)
            
            print(f"\n=== SENTIMENT CALCULATION ===")
            print(f"Total valid coins: {total_coins}")
            print(f"Green coins: {sentiment_factors['green_coins']}")
            print(f"Red coins: {sentiment_factors['red_coins']}")
            print(f"Green ratio: {green_ratio:.3f}")
            print(f"Average change: {avg_change:.3f}%")
            print(f"Volatility: {volatility:.3f}%")
            
            # Improved sentiment calculation
            # Component 1: Green ratio (0-40 points)
            green_component = green_ratio * 40
            
            # Component 2: Average change (-10% to +10% mapped to 0-30 points)
            change_component = max(0, min(30, (avg_change + 10) * 1.5))
            
            # Component 3: Inverse volatility (0-20% volatility mapped to 30-0 points)
            volatility_component = max(0, min(30, (20 - volatility) * 1.5))
            
            # Total sentiment score (0-100)
            sentiment_score = green_component + change_component + volatility_component
            
            print(f"Green component: {green_component:.1f}/40")
            print(f"Change component: {change_component:.1f}/30") 
            print(f"Volatility component: {volatility_component:.1f}/30")
            print(f"FINAL SENTIMENT SCORE: {sentiment_score:.1f}/100")
            
            return {
                'sentiment_score': sentiment_score,
                'green_coins': sentiment_factors['green_coins'],
                'red_coins': sentiment_factors['red_coins'],
                'green_ratio': green_ratio,
                'avg_change_24h': avg_change,
                'volatility': volatility,
                'total_market_cap': sum(market_caps),
                'total_volume_24h': sum(volumes),
                'total_valid_coins': total_coins
            }
        
        return None
    
    async def create_sentiment_dashboard(self):
        """Create market sentiment dashboard"""
        print("Fetching market data...")
        market_data = await self.fetch_market_data(100)
        global_data = await self.fetch_global_metrics()
        
        if not market_data:
            print("Failed to fetch market data")
            return None
        
        # Calculate sentiment index
        sentiment = self.calculate_sentiment_score(market_data)
        
        if not sentiment:
            print("Failed to calculate sentiment index")
            return None
        
        # Create subplot
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=[
                "",  # Remove title to avoid overlap with gauge
                "Price Change Distribution (24h performance spread)",
                "Rising/Falling Coins Ratio",
                "Top-20 by Market Cap"
            ],
            specs=[
                [{"type": "indicator"}, {"type": "histogram"}],
                [{"type": "pie"}, {"type": "bar"}]
            ],
            vertical_spacing=0.15,
            horizontal_spacing=0.1
        )
        
        # 1. Sentiment indicator (gauge)
        sentiment_score = sentiment['sentiment_score']
        
        # Define color and mood with clearer boundaries
        if sentiment_score >= 80:
            color = "#00CC00"  # Bright green
            mood = "FOMO"
        elif sentiment_score >= 60:
            color = "#66FF66"  # Light green
            mood = "Positive"
        elif sentiment_score >= 40:
            color = "#FFFF00"  # Yellow
            mood = "Neutral"
        elif sentiment_score >= 20:
            color = "#FF6600"  # Orange
            mood = "Stress"
        else:
            color = "#CC0000"  # Red
            mood = "Terror"
        
        fig.add_trace(
            go.Indicator(
                mode="gauge+number",
                value=sentiment_score,
                domain={'x': [0, 1], 'y': [0.1, 1]},  # Adjust positioning
                title={'text': f"Market Sentiment Index<br>Mood: {mood}", 'font': {'size': 14}},
                gauge={
                    'axis': {'range': [None, 100], 'tickwidth': 1, 'tickcolor': "darkblue"},
                    'bar': {'color': color, 'thickness': 0.25},
                    'bgcolor': "white",
                    'borderwidth': 2,
                    'bordercolor': "gray",
                    'steps': [
                        {'range': [0, 20], 'color': "#FFE6E6"},    # Light red
                        {'range': [20, 40], 'color': "#FFE6CC"},   # Light orange
                        {'range': [40, 60], 'color': "#FFFFCC"},   # Light yellow
                        {'range': [60, 80], 'color': "#E6FFE6"},   # Light light green
                        {'range': [80, 100], 'color': "#CCFFCC"}   # Light bright green
                    ],
                    'threshold': {
                        'line': {'color': "black", 'width': 4},
                        'thickness': 0.75,
                        'value': 50
                    }
                },
                number={'suffix': "", 'font': {'size': 18}}
            ),
            row=1, col=1
        )
        
        # 2. Price changes histogram
        changes_24h = [crypto['quote']['USD']['percent_change_24h'] 
                      for crypto in market_data 
                      if crypto['quote']['USD']['percent_change_24h'] is not None]
        
        fig.add_trace(
            go.Histogram(
                x=changes_24h,
                nbinsx=25,
                marker_color='rgba(0,100,80,0.7)',
                marker_line_color='rgba(0,100,80,1)',
                marker_line_width=1,
                name="Price Changes Distribution",
                hovertemplate="Range: %{x}%<br>Count: %{y}<extra></extra>"
            ),
            row=1, col=2
        )
        
        # 3. Rising/falling coins pie chart
        fig.add_trace(
            go.Pie(
                labels=['Rising', 'Falling'],
                values=[sentiment['green_coins'], sentiment['red_coins']],
                marker_colors=['#00CC00', '#CC0000'],
                name="Coins Ratio",
                textinfo='label+percent',  # Only show label and percent, not value
                textposition='auto',
                hovertemplate="<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>"
            ),
            row=2, col=1
        )
        
        # 4. Top-20 by market cap
        top_20 = market_data[:20]
        symbols = [crypto['symbol'] for crypto in top_20]
        changes = [crypto['quote']['USD']['percent_change_24h'] for crypto in top_20]
        colors = ['#00CC00' if change > 0 else '#CC0000' for change in changes]
        
        fig.add_trace(
            go.Bar(
                x=symbols,
                y=changes,
                marker_color=colors,
                name="Top-20 Changes",
                hovertemplate="<b>%{x}</b><br>24h Change: %{y:.2f}%<extra></extra>"
            ),
            row=2, col=2
        )
        
        # Update layout
        fig.update_layout(
            height=800,
            title_text=f"Crypto Market Sentiment Analysis - {datetime.now().strftime('%Y-%m-%d')}",
            showlegend=False,
            font=dict(family="Arial, sans-serif", size=12)
        )
        
        # Update x-axis for histogram
        fig.update_xaxes(title_text="24h Price Change (%)", row=1, col=2)
        fig.update_yaxes(title_text="Number of Coins", row=1, col=2)
        
        # Update x-axis for top-20 chart
        fig.update_xaxes(title_text="Cryptocurrency", row=2, col=2, tickangle=45)
        fig.update_yaxes(title_text="24h Change (%)", row=2, col=2)
        
        # Add market metrics annotation (top-right corner, smaller)
        fig.add_annotation(
            text=f"Market Cap: ${sentiment['total_market_cap']/1e12:.2f}T<br>" +
                 f"Volume 24h: ${sentiment['total_volume_24h']/1e9:.1f}B<br>" +
                 f"Avg Change: {sentiment['avg_change_24h']:.2f}%<br>" +
                 f"Volatility: {sentiment['volatility']:.2f}%",
            xref="paper", yref="paper",
            x=0.98, y=0.98,
            xanchor="right", yanchor="top",
            showarrow=False,
            font=dict(size=10, color="darkblue"),
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="lightgray",
            borderwidth=1,
            borderpad=4
        )
        
        return fig, sentiment
    
    async def create_market_treemap(self):
        """Create market treemap"""
        print("Creating market treemap...")
        market_data = await self.fetch_market_data(50)
        
        if not market_data:
            return None
        
        symbols = []
        market_caps = []
        changes_24h = []
        prices = []
        
        for crypto in market_data:
            symbols.append(crypto['symbol'])
            market_caps.append(crypto['quote']['USD']['market_cap'])
            prices.append(crypto['quote']['USD']['price'])
            change = crypto['quote']['USD']['percent_change_24h']
            changes_24h.append(change if change is not None else 0)
        
        # Create custom text for each cell
        custom_text = []
        for i in range(len(symbols)):
            symbol = symbols[i]
            price = prices[i]
            market_cap = market_caps[i]
            change = changes_24h[i]
            
            # Format price based on its value
            if price >= 1:
                price_str = f"${price:,.2f}"
            elif price >= 0.01:
                price_str = f"${price:.4f}"
            else:
                price_str = f"${price:.6f}"
            
            # Format market cap
            if market_cap >= 1e12:
                cap_str = f"${market_cap/1e12:.1f}T"
            elif market_cap >= 1e9:
                cap_str = f"${market_cap/1e9:.1f}B"
            elif market_cap >= 1e6:
                cap_str = f"${market_cap/1e6:.1f}M"
            else:
                cap_str = f"${market_cap/1e3:.1f}K"
            
            # Format change
            change_str = f"{change:+.2f}%" if change != 0 else "0.00%"
            
            # Combine all info
            cell_text = f"{symbol}<br>{price_str}<br>{cap_str}<br>{change_str}"
            custom_text.append(cell_text)
        
        fig = go.Figure(go.Treemap(
            labels=symbols,
            values=market_caps,
            parents=[""] * len(symbols),
            textinfo="text",  # Only show custom text
            text=custom_text,
            textposition="middle center",
            textfont_size=10,
            marker=dict(
                colorscale='RdYlGn',
                cmid=0,
                colorbar=dict(title="24h Change (%)"),
                line=dict(width=2, color="white"),
                colors=changes_24h
            ),
            customdata=list(zip(prices, market_caps, changes_24h)),
            hovertemplate="<b>%{label}</b><br>" +
                         "Price: $%{customdata[0]:,.6f}<br>" +
                         "Market Cap: $%{customdata[1]:,.0f}<br>" +
                         "24h Change: %{customdata[2]:+.2f}%<br>" +
                         "<extra></extra>"
        ))
        
        fig.update_layout(
            title="Crypto Market Treemap (size = market cap, color = 24h change)",
            font_size=12
        )
        
        return fig

async def main():
    """Main function"""
    analyzer = MarketSentimentAnalyzer()
    
    try:
        print("=== Crypto Market Sentiment Analyzer ===\n")
        
        # Create sentiment dashboard
        dashboard_result = await analyzer.create_sentiment_dashboard()
        
        if dashboard_result:
            fig, sentiment_data = dashboard_result
            
            # Save dashboard
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            dashboard_file = os.path.join(OUTPUT_FOLDER, f'market_sentiment_dashboard_{timestamp}.html')
            pyo.plot(fig, filename=dashboard_file, auto_open=True)
            print(f"Sentiment dashboard saved: {dashboard_file}")
            
            # Output key metrics
            print(f"\n=== Key Metrics ===")
            print(f"Sentiment Index: {sentiment_data['sentiment_score']:.1f}/100")
            print(f"Total valid coins processed: {sentiment_data['total_valid_coins']}")
            print(f"Rising coins: {sentiment_data['green_coins']}")
            print(f"Falling coins: {sentiment_data['red_coins']}")
            print(f"Rising ratio: {sentiment_data['green_ratio']*100:.1f}%")
            print(f"Average 24h change: {sentiment_data['avg_change_24h']:.2f}%")
            print(f"Market volatility: {sentiment_data['volatility']:.2f}%")
            print(f"Total market cap: ${sentiment_data['total_market_cap']/1e12:.2f}T")
            print(f"Total volume 24h: ${sentiment_data['total_volume_24h']/1e9:.1f}B")
        
        # Create market treemap
        treemap_fig = await analyzer.create_market_treemap()
        if treemap_fig:
            treemap_file = os.path.join(OUTPUT_FOLDER, f'market_treemap_{timestamp}.html')
            pyo.plot(treemap_fig, filename=treemap_file, auto_open=False)
            print(f"Market treemap saved: {treemap_file}")
        
        print("\n=== Analysis Complete ===")
        
    except Exception as e:
        logging.error(f"Error in main: {e}")
        print(f"An error occurred: {e}")
        
    finally:
        await analyzer.close_session()

if __name__ == "__main__":
    asyncio.run(main()) 
