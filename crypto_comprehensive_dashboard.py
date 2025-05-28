# -*- coding: utf-8 -*-
"""
Comprehensive Crypto Market Analysis Dashboard
Combines all analysis types into a single interactive HTML file
"""

import asyncio
import aiohttp
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
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
API_KEY = "831812bd-1186-43d4-b0d3-b71f0d61074e"
HEADERS = {"X-CMC_PRO_API_KEY": API_KEY}
BASE_URL = "https://pro-api.coinmarketcap.com"
OUTPUT_FOLDER = r"C:\Users\Main\Pitonio\crypto_etf"

# Create directory
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Logging
logging.basicConfig(
    filename=os.path.join(OUTPUT_FOLDER, "comprehensive_dashboard.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

class ComprehensiveCryptoDashboard:
    """Comprehensive Crypto Market Analysis Dashboard"""
    
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
    
    def calculate_sentiment_score(self, market_data):
        """Calculate market sentiment index"""
        if not market_data:
            return None
            
        green_coins = 0
        red_coins = 0
        changes_24h = []
        volumes = []
        market_caps = []
        
        for crypto in market_data:
            change_24h = crypto['quote']['USD']['percent_change_24h']
            volume_24h = crypto['quote']['USD']['volume_24h']
            market_cap = crypto['quote']['USD']['market_cap']
            
            if change_24h is not None:
                changes_24h.append(change_24h)
                if change_24h > 0:
                    green_coins += 1
                elif change_24h < 0:
                    red_coins += 1
            
            if volume_24h:
                volumes.append(volume_24h)
            
            if market_cap:
                market_caps.append(market_cap)
        
        total_coins = len(changes_24h)
        if total_coins > 0:
            green_ratio = green_coins / total_coins
            avg_change = np.mean(changes_24h)
            volatility = np.std(changes_24h)
            
            # Sentiment calculation
            green_component = green_ratio * 40
            change_component = max(0, min(30, (avg_change + 10) * 1.5))
            volatility_component = max(0, min(30, (20 - volatility) * 1.5))
            sentiment_score = green_component + change_component + volatility_component
            
            return {
                'sentiment_score': sentiment_score,
                'green_coins': green_coins,
                'red_coins': red_coins,
                'green_ratio': green_ratio,
                'avg_change_24h': avg_change,
                'volatility': volatility,
                'total_market_cap': sum(market_caps),
                'total_volume_24h': sum(volumes)
            }
        
        return None
    
    async def create_sentiment_gauge(self, sentiment):
        """Create sentiment gauge"""
        sentiment_score = sentiment['sentiment_score']
        
        if sentiment_score >= 80:
            color = "#00CC00"
            mood = "FOMO"
        elif sentiment_score >= 60:
            color = "#66FF66"
            mood = "Positive"
        elif sentiment_score >= 40:
            color = "#FFFF00"
            mood = "Neutral"
        elif sentiment_score >= 20:
            color = "#FF6600"
            mood = "Stress"
        else:
            color = "#CC0000"
            mood = "Terror"
        
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=sentiment_score,
            title={'text': f"Market Sentiment<br>Mood: {mood}", 'font': {'size': 14}},
            gauge={
                'axis': {'range': [None, 100], 'tickwidth': 1, 'tickcolor': "darkblue"},
                'bar': {'color': color, 'thickness': 0.25},
                'bgcolor': "white",
                'borderwidth': 2,
                'bordercolor': "gray",
                'steps': [
                    {'range': [0, 20], 'color': "#FFE6E6"},
                    {'range': [20, 40], 'color': "#FFE6CC"},
                    {'range': [40, 60], 'color': "#FFFFCC"},
                    {'range': [60, 80], 'color': "#E6FFE6"},
                    {'range': [80, 100], 'color': "#CCFFCC"}
                ],
                'threshold': {
                    'line': {'color': "black", 'width': 4},
                    'thickness': 0.75,
                    'value': 50
                }
            },
            number={'suffix': "", 'font': {'size': 18}}
        ))
        
        fig.update_layout(title="Market Sentiment Index", height=400)
        return fig
    
    async def create_market_cap_pie(self, market_data, limit=10):
        """Create market cap distribution pie chart"""
        symbols = [crypto['symbol'] for crypto in market_data[:limit]]
        market_caps = [crypto['quote']['USD']['market_cap'] for crypto in market_data[:limit]]
        
        fig = go.Figure(data=[go.Pie(
            labels=symbols,
            values=market_caps,
            textinfo='label+percent',
            textposition='auto',
            hovertemplate="<b>%{label}</b><br>Market Cap: $%{value:,.0f}<br>Share: %{percent}<extra></extra>"
        )])
        
        fig.update_layout(
            title=f"Market Cap Distribution (Top-{limit})",
            height=400
        )
        
        return fig
    
    async def create_price_change_histogram(self, market_data):
        """Create price change distribution histogram"""
        changes_24h = [crypto['quote']['USD']['percent_change_24h'] 
                      for crypto in market_data 
                      if crypto['quote']['USD']['percent_change_24h'] is not None]
        
        fig = go.Figure(data=[go.Histogram(
            x=changes_24h,
            nbinsx=25,
            marker_color='rgba(0,100,80,0.7)',
            marker_line_color='rgba(0,100,80,1)',
            marker_line_width=1,
            hovertemplate="Range: %{x}%<br>Count: %{y}<extra></extra>"
        )])
        
        fig.update_layout(
            title="24h Price Change Distribution",
            xaxis_title="24h Price Change (%)",
            yaxis_title="Number of Coins",
            height=400
        )
        
        return fig
    
    async def create_volatility_vs_volume_scatter(self, market_data):
        """Create volatility vs volume scatter plot"""
        symbols = []
        volumes = []
        volatilities = []
        market_caps = []
        
        for crypto in market_data:
            if crypto['quote']['USD']['percent_change_24h'] is not None:
                volatility = abs(crypto['quote']['USD']['percent_change_24h'])
                symbols.append(crypto['symbol'])
                volumes.append(crypto['quote']['USD']['volume_24h'])
                volatilities.append(volatility)
                market_caps.append(crypto['quote']['USD']['market_cap'])
        
        fig = go.Figure(data=go.Scatter(
            x=volumes,
            y=volatilities,
            mode='markers',
            marker=dict(
                size=[np.log10(mc) * 2 for mc in market_caps],
                sizemode='diameter',
                sizemin=4,
                color=volatilities,
                colorscale='Viridis',
                showscale=True,
                colorbar=dict(title="Volatility (%)")
            ),
            text=symbols,
            hovertemplate="<b>%{text}</b><br>" +
                         "Volume: $%{x:,.0f}<br>" +
                         "Volatility: %{y:.2f}%<br>" +
                         "<extra></extra>"
        ))
        
        fig.update_layout(
            title="Volatility vs Volume (bubble size = market cap)",
            xaxis_title="24h Volume (USD)",
            yaxis_title="Volatility (%)",
            xaxis_type="log",
            height=400
        )
        
        return fig
    
    async def create_top_performers_bar(self, market_data, limit=20):
        """Create top performers bar chart"""
        # Sort by 24h change
        sorted_data = sorted(market_data[:50], 
                           key=lambda x: x['quote']['USD']['percent_change_24h'] or 0, 
                           reverse=True)
        
        symbols = [crypto['symbol'] for crypto in sorted_data[:limit]]
        changes = [crypto['quote']['USD']['percent_change_24h'] or 0 for crypto in sorted_data[:limit]]
        colors = ['#00CC00' if change > 0 else '#CC0000' for change in changes]
        
        fig = go.Figure(data=[go.Bar(
            x=symbols,
            y=changes,
            marker_color=colors,
            hovertemplate="<b>%{x}</b><br>24h Change: %{y:.2f}%<extra></extra>"
        )])
        
        fig.update_layout(
            title=f"Top-{limit} Performers (24h)",
            xaxis_title="Cryptocurrency",
            yaxis_title="24h Change (%)",
            xaxis_tickangle=45,
            height=400
        )
        
        return fig
    
    async def create_liquidity_histogram(self, market_data):
        """Create liquidity distribution histogram"""
        liquidity_ratios = []
        
        for crypto in market_data:
            volume = crypto['quote']['USD']['volume_24h']
            market_cap = crypto['quote']['USD']['market_cap']
            
            if market_cap > 0 and volume:
                liquidity_ratio = (volume / market_cap) * 100
                if liquidity_ratio < 100:  # Filter extreme values
                    liquidity_ratios.append(liquidity_ratio)
        
        fig = go.Figure(data=[go.Histogram(
            x=liquidity_ratios,
            nbinsx=20,
            marker_color='skyblue',
            opacity=0.7,
            hovertemplate="Liquidity Range: %{x}%<br>Count: %{y}<extra></extra>"
        )])
        
        fig.update_layout(
            title="Liquidity Distribution (Volume/Market Cap %)",
            xaxis_title="Liquidity Ratio (%)",
            yaxis_title="Number of Coins",
            height=400
        )
        
        return fig
    
    async def create_market_treemap(self, market_data, limit=30):
        """Create market treemap"""
        symbols = []
        market_caps = []
        changes_24h = []
        prices = []
        
        for crypto in market_data[:limit]:
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
            
            # Format price
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
            
            change_str = f"{change:+.2f}%" if change != 0 else "0.00%"
            cell_text = f"{symbol}<br>{price_str}<br>{cap_str}<br>{change_str}"
            custom_text.append(cell_text)
        
        fig = go.Figure(go.Treemap(
            labels=symbols,
            values=market_caps,
            parents=[""] * len(symbols),
            textinfo="text",
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
            title=f"Market Treemap (Top-{limit})",
            height=500
        )
        
        return fig
    
    async def create_comprehensive_dashboard(self):
        """Create comprehensive dashboard with all analyses"""
        print("Fetching market data...")
        market_data = await self.fetch_market_data(100)
        
        if not market_data:
            print("Failed to fetch market data")
            return None
        
        print("Calculating sentiment...")
        sentiment = self.calculate_sentiment_score(market_data)
        
        if not sentiment:
            print("Failed to calculate sentiment")
            return None
        
        print("Creating individual charts...")
        
        # Create all individual charts
        sentiment_gauge = await self.create_sentiment_gauge(sentiment)
        market_cap_pie = await self.create_market_cap_pie(market_data)
        price_histogram = await self.create_price_change_histogram(market_data)
        volatility_scatter = await self.create_volatility_vs_volume_scatter(market_data)
        top_performers = await self.create_top_performers_bar(market_data)
        liquidity_hist = await self.create_liquidity_histogram(market_data)
        market_treemap = await self.create_market_treemap(market_data)
        
        # Create main dashboard with subplots (without treemap)
        print("Creating comprehensive dashboard...")
        fig = make_subplots(
            rows=2, cols=3,
            subplot_titles=[
                "Market Sentiment Index",
                "Market Cap Distribution", 
                "Price Change Distribution",
                "Volatility vs Volume",
                "Top-20 Performers",
                "Liquidity Distribution"
            ],
            specs=[
                [{"type": "indicator"}, {"type": "pie"}, {"type": "histogram"}],
                [{"type": "scatter"}, {"type": "bar"}, {"type": "histogram"}]
            ],
            vertical_spacing=0.12,
            horizontal_spacing=0.08
        )
        
        # Add sentiment gauge
        sentiment_trace = sentiment_gauge.data[0]
        sentiment_trace.domain = {'x': [0, 1], 'y': [0, 1]}
        fig.add_trace(sentiment_trace, row=1, col=1)
        
        # Add market cap pie
        pie_trace = market_cap_pie.data[0]
        fig.add_trace(pie_trace, row=1, col=2)
        
        # Add price histogram
        hist_trace = price_histogram.data[0]
        fig.add_trace(hist_trace, row=1, col=3)
        
        # Add volatility scatter
        scatter_trace = volatility_scatter.data[0]
        fig.add_trace(scatter_trace, row=2, col=1)
        
        # Add top performers bar
        bar_trace = top_performers.data[0]
        fig.add_trace(bar_trace, row=2, col=2)
        
        # Add liquidity histogram
        liq_trace = liquidity_hist.data[0]
        fig.add_trace(liq_trace, row=2, col=3)
        
        # Update layout
        fig.update_layout(
            height=800,
            title_text=f"Comprehensive Crypto Market Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            showlegend=False,
            font=dict(family="Arial, sans-serif", size=10)
        )
        
        # Add market summary annotation
        fig.add_annotation(
            text=f"Market Summary:<br>" +
                 f"Sentiment Score: {sentiment['sentiment_score']:.1f}/100<br>" +
                 f"Rising/Falling: {sentiment['green_coins']}/{sentiment['red_coins']}<br>" +
                 f"Total Market Cap: ${sentiment['total_market_cap']/1e12:.2f}T<br>" +
                 f"Total Volume 24h: ${sentiment['total_volume_24h']/1e9:.1f}B<br>" +
                 f"Avg Change: {sentiment['avg_change_24h']:.2f}%<br>" +
                 f"Volatility: {sentiment['volatility']:.2f}%",
            xref="paper", yref="paper",
            x=0.98, y=0.98,
            xanchor="right", yanchor="top",
            showarrow=False,
            font=dict(size=11, color="darkblue"),
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="lightgray",
            borderwidth=1,
            borderpad=8
        )
        
        return fig, market_treemap, sentiment

async def main():
    """Main function"""
    dashboard = ComprehensiveCryptoDashboard()
    
    try:
        print("=== Comprehensive Crypto Market Analysis Dashboard ===\n")
        
        # Create comprehensive dashboard
        result = await dashboard.create_comprehensive_dashboard()
        
        if result:
            main_fig, treemap_fig, sentiment_data = result
            
            # Save main dashboard
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            
            # Create HTML content with both charts
            main_html = pyo.plot(main_fig, output_type='div', include_plotlyjs=False)
            treemap_html = pyo.plot(treemap_fig, output_type='div', include_plotlyjs=False)
            
            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Comprehensive Crypto Market Analysis</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            text-align: center;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
        }}
        .dashboard-container {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .summary-stats {{
            display: flex;
            justify-content: space-around;
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
        }}
        .stat-item {{
            text-align: center;
        }}
        .stat-value {{
            font-size: 1.5em;
            font-weight: bold;
            color: #2c3e50;
        }}
        .stat-label {{
            color: #7f8c8d;
            font-size: 0.9em;
        }}
        .footer {{
            text-align: center;
            color: #7f8c8d;
            font-size: 0.9em;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🚀 Comprehensive Crypto Market Analysis Dashboard</h1>
        <p>Real-time market insights and sentiment analysis</p>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
    
    <div class="summary-stats">
        <div class="stat-item">
            <div class="stat-value">{sentiment_data['sentiment_score']:.1f}/100</div>
            <div class="stat-label">Sentiment Score</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${sentiment_data['total_market_cap']/1e12:.2f}T</div>
            <div class="stat-label">Total Market Cap</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${sentiment_data['total_volume_24h']/1e9:.1f}B</div>
            <div class="stat-label">24h Volume</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">{sentiment_data['green_coins']}/{sentiment_data['red_coins']}</div>
            <div class="stat-label">Rising/Falling</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">{sentiment_data['avg_change_24h']:+.2f}%</div>
            <div class="stat-label">Avg Change 24h</div>
        </div>
    </div>
    
    <div class="dashboard-container">
        <h2>📊 Main Dashboard</h2>
        {main_html}
    </div>
    
    <div class="dashboard-container">
        <h2>🗺️ Market Treemap Overview</h2>
        {treemap_html}
    </div>
    
    <div class="footer">
        <p>Data provided by CoinMarketCap API | Analysis generated by Crypto Market Analyzer</p>
        <p><strong>Disclaimer:</strong> This is for informational purposes only and should not be considered financial advice.</p>
    </div>
</body>
</html>
"""
            
            dashboard_file = os.path.join(OUTPUT_FOLDER, f'comprehensive_crypto_dashboard_{timestamp}.html')
            
            with open(dashboard_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            print(f"Comprehensive dashboard saved: {dashboard_file}")
            
            # Output summary
            print(f"\n=== Dashboard Summary ===")
            print(f"Sentiment Index: {sentiment_data['sentiment_score']:.1f}/100")
            print(f"Total market cap: ${sentiment_data['total_market_cap']/1e12:.2f}T")
            print(f"Total volume 24h: ${sentiment_data['total_volume_24h']/1e9:.1f}B")
            print(f"Charts included: 7 different analysis types")
            print(f"Market overview: Comprehensive view in single HTML file")
            
            # Open the file
            import webbrowser
            webbrowser.open(f'file:///{dashboard_file.replace(chr(92), "/")}')
        
        print("\n=== Analysis Complete ===")
        
    except Exception as e:
        logging.error(f"Error in main: {e}")
        print(f"An error occurred: {e}")
        
    finally:
        await dashboard.close_session()

if __name__ == "__main__":
    asyncio.run(main()) 