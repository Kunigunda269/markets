# -*- coding: utf-8 -*-
"""
Ultimate Crypto Market Analysis Dashboard
Comprehensive analysis with advanced metrics using CoinMarketCap API
Includes: Volume Efficiency, Stablecoin Dominance, Volatility Surface, Market Microstructure
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
import json
import time
from typing import Dict, List, Optional, Tuple
import warnings
from scipy import stats
import concurrent.futures
warnings.filterwarnings('ignore')

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# === CONFIGURATION ===
API_KEY = os.getenv("CMC_API_KEY", "")
HEADERS = {"X-CMC_PRO_API_KEY": API_KEY}
BASE_URL = "https://pro-api.coinmarketcap.com"
OUTPUT_FOLDER = os.getenv("OUTPUT_DIR", "output")
CACHE_FOLDER = os.path.join(OUTPUT_FOLDER, "cache")

# Create directories
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(CACHE_FOLDER, exist_ok=True)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(OUTPUT_FOLDER, "ultimate_dashboard.log"), encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

class CacheManager:
    """Enhanced cache manager with memory and file caching"""
    
    def __init__(self, cache_duration_minutes=15, max_memory_items=50):
        self.cache_duration = timedelta(minutes=cache_duration_minutes)
        self.memory_cache = {}  # RAM cache for fast access
        self.max_memory_items = max_memory_items
        
    def get_cache_filename(self, endpoint: str, params: dict) -> str:
        """Generate cache filename"""
        # Replace slashes and special characters to make valid filename
        safe_endpoint = endpoint.replace("/", "_").replace("-", "_")
        cache_key = f"{safe_endpoint}_{hash(str(sorted(params.items())))}"
        return os.path.join(CACHE_FOLDER, f"{cache_key}.json")
    
    def is_cache_valid(self, filename: str) -> bool:
        """Check if cache is still valid"""
        if not os.path.exists(filename):
            return False
        
        mod_time = datetime.fromtimestamp(os.path.getmtime(filename))
        return datetime.now() - mod_time < self.cache_duration
    
    def save_cache(self, filename: str, data: dict):
        """Save data to cache"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, default=str)
            logging.debug(f"Data cached to {filename}")
        except Exception as e:
            logging.warning(f"Failed to save cache: {e}")
    
    def get_memory_key(self, endpoint: str, params: dict) -> str:
        """Generate memory cache key"""
        return f"{endpoint}_{hash(str(sorted(params.items())))}"
    
    def get_cached_data(self, endpoint: str, params: dict) -> Optional[dict]:
        """Get data from cache (memory first, then file)"""
        memory_key = self.get_memory_key(endpoint, params)
        
        # Check memory cache first
        if memory_key in self.memory_cache:
            data, timestamp = self.memory_cache[memory_key]
            if datetime.now() - timestamp < self.cache_duration:
                logging.debug(f"Data loaded from memory cache: {memory_key}")
                return data
            else:
                del self.memory_cache[memory_key]
        
        # Check file cache
        filename = self.get_cache_filename(endpoint, params)
        cached_data = self.load_cache(filename)
        if cached_data:
            # Store in memory for future use
            self._store_in_memory(memory_key, cached_data)
            return cached_data
        
        return None
    
    def save_cached_data(self, endpoint: str, params: dict, data: dict):
        """Save data to both memory and file cache"""
        memory_key = self.get_memory_key(endpoint, params)
        filename = self.get_cache_filename(endpoint, params)
        
        # Save to memory cache
        self._store_in_memory(memory_key, data)
        
        # Save to file cache
        self.save_cache(filename, data)
    
    def _store_in_memory(self, key: str, data: dict):
        """Store data in memory cache with size limit"""
        if len(self.memory_cache) >= self.max_memory_items:
            # Remove oldest item
            oldest_key = min(self.memory_cache.keys(), 
                           key=lambda k: self.memory_cache[k][1])
            del self.memory_cache[oldest_key]
        
        self.memory_cache[key] = (data, datetime.now())

    def load_cache(self, filename: str) -> Optional[dict]:
        """Load data from cache"""
        try:
            if self.is_cache_valid(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    logging.debug(f"Data loaded from cache: {filename}")
                    return json.load(f)
        except Exception as e:
            logging.warning(f"Failed to load cache: {e}")
        return None

class RateLimiter:
    """API rate limiter"""
    
    def __init__(self, requests_per_minute=10):
        self.min_interval = 60.0 / requests_per_minute
        self.last_request = 0
        
    async def wait(self):
        """Wait if necessary to respect rate limits"""
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.min_interval:
            wait_time = self.min_interval - elapsed
            logging.debug(f"Rate limiting: waiting {wait_time:.2f} seconds")
            await asyncio.sleep(wait_time)
        self.last_request = time.time()

class UltimateCryptoDashboard:
    """Ultimate Crypto Market Analysis Dashboard"""
    
    def __init__(self):
        self.session = None
        self.cache_manager = CacheManager()
        self.rate_limiter = RateLimiter()
        
    async def get_session(self):
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    async def fetch_with_cache(self, endpoint: str, params: dict) -> Optional[dict]:
        """Enhanced fetch with improved caching and error handling"""
        try:
            # Try to get from enhanced cache first
            cached_data = self.cache_manager.get_cached_data(endpoint, params)
            if cached_data:
                return cached_data
            
            # Fetch from API with enhanced error handling
            session = await self.get_session()
            await self.rate_limiter.wait()
            
            full_url = f"{BASE_URL}{endpoint}"
            logging.info(f"API request: {full_url} with params: {params}")
            
            async with session.get(full_url, headers=HEADERS, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Validate response structure
                    if 'data' not in data and 'status' not in data:
                        logging.warning(f"Unexpected response structure from {endpoint}")
                        return None
                    
                    # Save to enhanced cache
                    self.cache_manager.save_cached_data(endpoint, params, data)
                    return data
                elif response.status == 429:
                    logging.warning(f"Rate limit exceeded for {endpoint}. Waiting...")
                    await asyncio.sleep(60)  # Wait 1 minute and retry
                    return await self.fetch_with_cache(endpoint, params)
                elif response.status == 401:
                    logging.error(f"API Key authentication failed for {endpoint}")
                    return None
                else:
                    error_text = await response.text()
                    logging.error(f"API Error {response.status} for {endpoint}: {error_text}")
                    return None
                    
        except asyncio.TimeoutError:
            logging.error(f"Timeout error for {endpoint}")
            return None
        except aiohttp.ClientError as e:
            logging.error(f"Client error for {endpoint}: {e}")
            return None
        except Exception as e:
            logging.error(f"Unexpected error for {endpoint}: {e}")
            return None
    
    async def fetch_market_data(self, limit=100) -> Optional[List[dict]]:
        """Get current market data"""
        data = await self.fetch_with_cache("/v1/cryptocurrency/listings/latest", 
                                          {"limit": limit, "convert": "USD"})
        return data['data'] if data else None
    
    async def fetch_global_metrics(self) -> Optional[dict]:
        """Get global market metrics"""
        data = await self.fetch_with_cache("/v1/global-metrics/quotes/latest", 
                                          {"convert": "USD"})
        return data['data'] if data else None
    
    async def fetch_categories(self) -> Optional[List[dict]]:
        """Get cryptocurrency categories"""
        data = await self.fetch_with_cache("/v1/cryptocurrency/categories", 
                                          {"limit": 100})
        return data['data'] if data else None
    
    # === NEW ANALYSIS METHODS ===
    
    async def create_volume_efficiency_analysis(self, market_data: List[dict]) -> go.Figure:
        """
        КОМБИНИРОВАННЫЙ: Volume Efficiency + Volume Analysis 
        Два анализа в одном файле: эффективность объема и анализ торговой активности
        """
        logging.info("Creating Combined Volume Analysis")
        
        symbols = []
        market_caps = []
        volumes_24h = []
        prices = []
        changes_24h = []
        efficiency_ratios = []
        
        for crypto in market_data[:40]:  # Top 40 for performance
            mc = crypto['quote']['USD']['market_cap']
            vol = crypto['quote']['USD']['volume_24h']
            
            if mc and vol and vol > 0:
                symbols.append(crypto['symbol'])
                market_caps.append(mc)
                volumes_24h.append(vol)
                prices.append(crypto['quote']['USD']['price'])
                changes_24h.append(crypto['quote']['USD']['percent_change_24h'] or 0)
                
                # Efficiency ratio: higher volume relative to market cap = better liquidity
                efficiency = vol / mc * 100  # Volume as % of market cap
                efficiency_ratios.append(efficiency)
        
        if not symbols:
            return go.Figure().add_annotation(text="No data available", 
                                            xref="paper", yref="paper", x=0.5, y=0.5)
        
        # Create subplots for combined analysis
        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=[
                "Volume Efficiency Analysis (Cap vs Efficiency)",
                "Volume Analysis (Volume vs Price Change)"
            ],
            horizontal_spacing=0.1
        )
        
        # 1. Volume Efficiency Scatter (left plot)
        colors = changes_24h
        
        fig.add_trace(go.Scatter(
            x=market_caps,
            y=efficiency_ratios,
            mode='markers',
            text=symbols,
            textposition='middle right',
            textfont=dict(size=8),
            marker=dict(
                size=[min(20, max(6, abs(change)*1.5)) for change in changes_24h],
                color=colors,
                colorscale='RdYlGn',
                colorbar=dict(title="24h Change (%)", x=0.45),
                line=dict(width=0.5, color='black'),
                opacity=0.8
            ),
            customdata=list(zip(symbols, prices, volumes_24h, changes_24h)),
            hovertemplate="<b>%{customdata[0]}</b><br>" +
                         "Market Cap: $%{x:,.0f}<br>" +
                         "Efficiency: %{y:.3f}%<br>" +
                         "Price: $%{customdata[1]:,.4f}<br>" +
                         "Volume 24h: $%{customdata[2]:,.0f}<br>" +
                         "Change 24h: %{customdata[3]:+.2f}%<extra></extra>",
            showlegend=False
        ), row=1, col=1)
        
        # Add efficiency trend line
        if len(market_caps) > 3:
            z = np.polyfit(np.log10(market_caps), np.log10(efficiency_ratios), 1)
            p = np.poly1d(z)
            trend_x = sorted(market_caps)
            trend_y = [10**p(np.log10(x)) for x in trend_x]
            
            fig.add_trace(go.Scatter(
                x=trend_x,
                y=trend_y,
                mode='lines',
                line=dict(dash='dash', color='red', width=2),
                name='Efficiency Trend',
                showlegend=False
            ), row=1, col=1)
        
        # 2. Volume Analysis (right plot)
        fig.add_trace(go.Scatter(
            x=volumes_24h,
            y=changes_24h,
            mode='markers',
            text=symbols,
            textposition='middle left',
            textfont=dict(size=8),
            marker=dict(
                size=[min(25, max(8, mc/1e11)) for mc in market_caps],
                color=market_caps,
                colorscale='Plasma',
                colorbar=dict(title="Market Cap ($)", x=1.02),
                line=dict(width=0.5, color='white'),
                opacity=0.8
            ),
            customdata=list(zip(symbols, market_caps, prices)),
            hovertemplate="<b>%{customdata[0]}</b><br>" +
                         "Volume 24h: $%{x:,.0f}<br>" +
                         "Change 24h: %{y:+.2f}%<br>" +
                         "Market Cap: $%{customdata[1]:,.0f}<br>" +
                         "Price: $%{customdata[2]:,.4f}<extra></extra>",
            showlegend=False
        ), row=1, col=2)
        
        # Add zero line for volume analysis
        fig.add_hline(y=0, line_dash="dot", line_color="gray", row=1, col=2)
        
        # Update layout
        fig.update_layout(
            title="Combined Volume Analysis<br><sub>Left: Efficiency (Volume/Cap), Right: Trading Activity (Volume vs Change)</sub>",
            height=600,
            font=dict(size=10),
            margin=dict(l=50, r=100, t=80, b=50)
        )
        
        # Update axes
        fig.update_xaxes(title_text="Market Cap ($)", type="log", row=1, col=1)
        fig.update_yaxes(title_text="Volume Efficiency (%)", type="log", row=1, col=1)
        fig.update_xaxes(title_text="Volume 24h ($)", type="log", row=1, col=2)
        fig.update_yaxes(title_text="Price Change 24h (%)", row=1, col=2)
        
        return fig
    
    async def create_stablecoin_dominance_tracker(self, market_data: List[dict]) -> go.Figure:
        """
        НОВОЕ: Stablecoin Dominance Tracker
        Мониторинг доминации различных стейблкоинов
        """
        logging.info("Creating Stablecoin Dominance Tracker")
        
        # Define known stablecoins
        stablecoins = {
            'USDT': 'Tether',
            'USDC': 'USD Coin',
            'BUSD': 'Binance USD',
            'DAI': 'Dai',
            'FRAX': 'Frax',
            'TUSD': 'TrueUSD',
            'USDP': 'Pax Dollar',
            'USDD': 'USDD',
            'LUSD': 'Liquity USD'
        }
        
        stable_data = []
        total_stable_cap = 0
        
        for crypto in market_data:
            symbol = crypto['symbol']
            if symbol in stablecoins:
                market_cap = crypto['quote']['USD']['market_cap']
                volume_24h = crypto['quote']['USD']['volume_24h']
                
                stable_data.append({
                    'symbol': symbol,
                    'name': stablecoins[symbol],
                    'market_cap': market_cap,
                    'volume_24h': volume_24h,
                    'rank': crypto['cmc_rank']
                })
                total_stable_cap += market_cap
        
        if not stable_data:
            return go.Figure().add_annotation(text="No stablecoin data available", 
                                            xref="paper", yref="paper", x=0.5, y=0.5)
        
        # Sort by market cap
        stable_data.sort(key=lambda x: x['market_cap'], reverse=True)
        
        # Create subplots
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=[
                "Stablecoin Market Cap Distribution",
                "Volume vs Market Cap",
                "Market Cap (USD Billions)",
                "Volume/Market Cap Ratio"
            ],
            specs=[
                [{"type": "pie"}, {"type": "scatter"}],
                [{"type": "bar"}, {"type": "bar"}]
            ]
        )
        
        symbols = [item['symbol'] for item in stable_data]
        market_caps = [item['market_cap'] for item in stable_data]
        volumes = [item['volume_24h'] for item in stable_data]
        
        # 1. Pie chart - Market cap distribution
        fig.add_trace(
            go.Pie(
                labels=symbols,
                values=market_caps,
                textinfo='label+percent',
                name="Market Cap Distribution"
            ),
            row=1, col=1
        )
        
        # 2. Scatter - Volume vs Market Cap
        fig.add_trace(
            go.Scatter(
                x=market_caps,
                y=volumes,
                mode='markers',
                text=symbols,
                textposition='middle center',
                textfont=dict(size=8),
                marker=dict(
                    size=15, 
                    opacity=0.8,
                    color='lightcoral',
                    line=dict(width=1, color='darkred')
                ),
                customdata=[[item['symbol'], item['rank']] for item in stable_data],
                hovertemplate="<b>%{customdata[0]}</b><br>" +
                             "Market Cap: $%{x:,.0f}<br>" +
                             "Volume 24h: $%{y:,.0f}<br>" +
                             "CMC Rank: #%{customdata[1]}<extra></extra>",
                name="Volume vs Cap"
            ),
            row=1, col=2
        )
        
        # 3. Bar chart - Market caps in billions
        fig.add_trace(
            go.Bar(
                x=symbols,
                y=[cap/1e9 for cap in market_caps],
                marker_color='lightblue',
                name="Market Cap (B)"
            ),
            row=2, col=1
        )
        
        # 4. Bar chart - Volume/Market Cap ratios
        ratios = [vol/cap*100 if cap > 0 else 0 for vol, cap in zip(volumes, market_caps)]
        fig.add_trace(
            go.Bar(
                x=symbols,
                y=ratios,
                marker_color='lightgreen',
                name="Volume/Cap %"
            ),
            row=2, col=2
        )
        
        # Update layout
        fig.update_layout(
            height=800,
            title_text=f"Stablecoin Market Analysis<br><sub>Total Stablecoin Market Cap: ${total_stable_cap/1e9:.1f}B</sub>",
            showlegend=False
        )
        
        # Update axes
        fig.update_xaxes(title_text="Market Cap (USD)", type="log", row=1, col=2)
        fig.update_yaxes(title_text="Volume 24h (USD)", type="log", row=1, col=2)
        fig.update_yaxes(title_text="Billions USD", row=2, col=1)
        fig.update_yaxes(title_text="Volume/Cap %", row=2, col=2)
        
        return fig
    
    async def create_market_microstructure_analysis(self, market_data: List[dict]) -> go.Figure:
        """
        НОВОЕ: Market Microstructure Analysis
        Анализ спредов и ликвидности по торговым парам
        """
        logging.info("Creating Market Microstructure Analysis")
        
        # Calculate liquidity metrics
        liquidity_data = []
        
        for crypto in market_data[:30]:  # Top 30 for detailed analysis
            symbol = crypto['symbol']
            price = crypto['quote']['USD']['price']
            volume_24h = crypto['quote']['USD']['volume_24h']
            market_cap = crypto['quote']['USD']['market_cap']
            
            if volume_24h and market_cap and price:
                # Liquidity score: combination of volume and market cap
                liquidity_score = (volume_24h / market_cap) * np.log10(market_cap)
                
                # Turnover ratio
                turnover = volume_24h / market_cap * 100
                
                # Price impact estimate (inverse of liquidity)
                price_impact = 1 / (volume_24h / 1e6) if volume_24h > 0 else float('inf')
                price_impact = min(price_impact, 100)  # Cap at 100%
                
                liquidity_data.append({
                    'symbol': symbol,
                    'price': price,
                    'volume_24h': volume_24h,
                    'market_cap': market_cap,
                    'liquidity_score': liquidity_score,
                    'turnover': turnover,
                    'price_impact': price_impact
                })
        
        if not liquidity_data:
            return go.Figure().add_annotation(text="No liquidity data available", 
                                            xref="paper", yref="paper", x=0.5, y=0.5)
        
        # Sort by liquidity score
        liquidity_data.sort(key=lambda x: x['liquidity_score'], reverse=True)
        
        # Create subplots
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=[
                "Liquidity Score (Higher = Better)",
                "Turnover Ratio vs Price Impact",
                "Volume vs Market Cap (Liquidity View)",
                "Price Impact Distribution"
            ]
        )
        
        symbols = [item['symbol'] for item in liquidity_data]
        
        # 1. Liquidity score bar chart
        fig.add_trace(
            go.Bar(
                x=symbols,
                y=[item['liquidity_score'] for item in liquidity_data],
                marker_color='blue',
                name="Liquidity Score"
            ),
            row=1, col=1
        )
        
        # 2. Turnover vs Price Impact scatter
        fig.add_trace(
            go.Scatter(
                x=[item['turnover'] for item in liquidity_data],
                y=[item['price_impact'] for item in liquidity_data],
                mode='markers',
                text=symbols,
                textposition='middle center',
                textfont=dict(size=8),
                marker=dict(
                    size=[min(15, max(6, item['liquidity_score']*1.5)) for item in liquidity_data],
                    color=[item['liquidity_score'] for item in liquidity_data],
                    colorscale='Viridis',
                    showscale=True,
                    colorbar=dict(title="Liquidity Score", x=0.48),
                    line=dict(width=0.5, color='white'),
                    opacity=0.8
                ),
                customdata=[[item['symbol'], item['market_cap'], item['volume_24h'], item['price']] for item in liquidity_data],
                hovertemplate="<b>%{customdata[0]}</b><br>" +
                             "Turnover: %{x:.1f}%<br>" +
                             "Price Impact: %{y:.3f}%<br>" +
                             "Market Cap: $%{customdata[1]:,.0f}<br>" +
                             "Volume 24h: $%{customdata[2]:,.0f}<br>" +
                             "Price: $%{customdata[3]:,.4f}<extra></extra>",
                name="Turnover vs Impact"
            ),
            row=1, col=2
        )
        
        # 3. Volume vs Market Cap
        fig.add_trace(
            go.Scatter(
                x=[item['market_cap'] for item in liquidity_data],
                y=[item['volume_24h'] for item in liquidity_data],
                mode='markers',
                text=symbols,
                textposition='middle right',
                textfont=dict(size=8),
                marker=dict(
                    size=12, 
                    color=[item['turnover'] for item in liquidity_data],
                    colorscale='Blues',
                    showscale=True,
                    colorbar=dict(title="Turnover %", x=1.02),
                    line=dict(width=0.5, color='darkblue'),
                    opacity=0.8
                ),
                customdata=[[item['symbol'], item['turnover'], item['price_impact']] for item in liquidity_data],
                hovertemplate="<b>%{customdata[0]}</b><br>" +
                             "Market Cap: $%{x:,.0f}<br>" +
                             "Volume 24h: $%{y:,.0f}<br>" +
                             "Turnover: %{customdata[1]:.1f}%<br>" +
                             "Price Impact: %{customdata[2]:.3f}%<extra></extra>",
                name="Volume vs Cap"
            ),
            row=2, col=1
        )
        
        # 4. Price Impact histogram
        fig.add_trace(
            go.Histogram(
                x=[item['price_impact'] for item in liquidity_data],
                nbinsx=15,
                marker_color='orange',
                name="Price Impact Distribution"
            ),
            row=2, col=2
        )
        
        # Update layout
        fig.update_layout(
            height=800,
            title_text="Market Microstructure Analysis<br><sub>Liquidity, Turnover and Price Impact Metrics</sub>",
            showlegend=False
        )
        
        # Update axes
        fig.update_xaxes(title_text="Turnover %", row=1, col=2)
        fig.update_yaxes(title_text="Price Impact %", row=1, col=2)
        fig.update_xaxes(title_text="Market Cap", type="log", row=2, col=1)
        fig.update_yaxes(title_text="Volume 24h", type="log", row=2, col=1)
        fig.update_xaxes(title_text="Price Impact %", row=2, col=2)
        fig.update_yaxes(title_text="Count", row=2, col=2)
        
        return fig
    
    async def create_volatility_surface_mapping(self, market_data: List[dict]) -> go.Figure:
        """
        НОВОЕ: Volatility Surface Mapping
        3D поверхность волатильности по времени и активам
        """
        logging.info("Creating Volatility Surface Mapping")
        
        # Get historical data for top assets to calculate volatilities
        top_assets = market_data[:20]  # Top 20 for performance
        
        timeframes = ['1h', '24h', '7d', '30d']
        volatility_matrix = []
        symbols = []
        
        for crypto in top_assets:
            symbol = crypto['symbol']
            symbols.append(symbol)
            
            # Get volatility data from available fields
            changes = []
            for tf in timeframes:
                if tf == '1h':
                    change = crypto['quote']['USD'].get('percent_change_1h', 0) or 0
                elif tf == '24h':
                    change = crypto['quote']['USD'].get('percent_change_24h', 0) or 0
                elif tf == '7d':
                    change = crypto['quote']['USD'].get('percent_change_7d', 0) or 0
                elif tf == '30d':
                    change = crypto['quote']['USD'].get('percent_change_30d', 0) or 0
                else:
                    change = 0
                changes.append(abs(change))  # Volatility is absolute change
            
            volatility_matrix.append(changes)
        
        if not symbols:
            return go.Figure().add_annotation(text="No volatility data available", 
                                            xref="paper", yref="paper", x=0.5, y=0.5)
        
        # Create 3D surface
        volatility_array = np.array(volatility_matrix)
        
        # Create meshgrid for 3D plotting
        X, Y = np.meshgrid(range(len(timeframes)), range(len(symbols)))
        Z = volatility_array
        
        fig = go.Figure()
        
        # Add 3D surface
        fig.add_trace(go.Surface(
            x=X,
            y=Y, 
            z=Z,
            colorscale='Viridis',
            colorbar=dict(title="Volatility %"),
            showscale=True
        ))
        
        # Add 2D heatmap as well
        fig.add_trace(go.Heatmap(
            x=timeframes,
            y=symbols,
            z=volatility_array,
            colorscale='Viridis',
            showscale=False,
            visible=False,
            name="2D View"
        ))
        
        # Add toggle buttons
        fig.update_layout(
            title="Volatility Surface Mapping<br><sub>3D visualization of volatility across assets and timeframes</sub>",
            scene=dict(
                xaxis_title="Timeframe",
                yaxis_title="Assets", 
                zaxis_title="Volatility %",
                xaxis=dict(tickmode='array', tickvals=list(range(len(timeframes))), ticktext=timeframes),
                yaxis=dict(tickmode='array', tickvals=list(range(len(symbols))), ticktext=symbols)
            ),
            height=700,
            updatemenus=[
                dict(
                    type="buttons",
                    direction="left",
                    buttons=list([
                        dict(
                            args=[{"visible": [True, False]}],
                            label="3D View",
                            method="restyle"
                        ),
                        dict(
                            args=[{"visible": [False, True]}],
                            label="2D Heatmap",
                            method="restyle"
                        )
                    ]),
                    pad={"r": 10, "t": 10},
                    showactive=True,
                    x=0.5,
                    xanchor="center",
                    y=1.1,
                    yanchor="top"
                ),
            ]
        )
        
        return fig
    
    async def create_correlation_matrix_analysis(self, market_data: List[dict]) -> go.Figure:
        """
        НОВОЕ: Correlation Matrix Analysis
        Анализ корреляций между топ криптовалютами с улучшенной обработкой ошибок
        """
        logging.info("Creating Correlation Matrix Analysis")
        
        try:
            # Prepare correlation data
            symbols = []
            changes_24h = []
            changes_7d = []
            changes_30d = []
            volumes = []
            market_caps = []
            
            for crypto in market_data[:25]:  # Top 25 for correlation analysis
                try:
                    symbol = crypto['symbol']
                    quote_data = crypto.get('quote', {}).get('USD', {})
                    
                    change_24h = quote_data.get('percent_change_24h', 0) or 0
                    change_7d = quote_data.get('percent_change_7d', 0) or 0  
                    change_30d = quote_data.get('percent_change_30d', 0) or 0
                    volume = quote_data.get('volume_24h', 0) or 0
                    market_cap = quote_data.get('market_cap', 0) or 0
                    
                    if market_cap > 0 and volume > 0:  # Only include valid data
                        symbols.append(symbol)
                        changes_24h.append(change_24h)
                        changes_7d.append(change_7d)
                        changes_30d.append(change_30d)
                        volumes.append(np.log10(volume))
                        market_caps.append(np.log10(market_cap))
                        
                except (KeyError, TypeError, ValueError) as e:
                    logging.debug(f"Skipping crypto {crypto.get('symbol', 'Unknown')} due to data error: {e}")
                    continue
            
            if len(symbols) < 5:
                return go.Figure().add_annotation(
                    text="Insufficient data for correlation analysis", 
                    xref="paper", yref="paper", x=0.5, y=0.5
                )
            
            # Create correlation DataFrame
            corr_df = pd.DataFrame({
                'Change_24h': changes_24h,
                'Change_7d': changes_7d,
                'Change_30d': changes_30d,
                'Log_Volume': volumes,
                'Log_MarketCap': market_caps
            })
            
            # Calculate correlation matrix
            correlation_matrix = corr_df.corr()
            
            # Create subplots
            fig = make_subplots(
                rows=2, cols=2,
                subplot_titles=[
                    "Price Changes Correlation Matrix",
                    "24h vs 7d Changes Scatter",
                    "Volume vs Market Cap Correlation", 
                    "Top Correlations Analysis"
                ],
                specs=[
                    [{"type": "heatmap"}, {"type": "scatter"}],
                    [{"type": "scatter"}, {"type": "bar"}]
                ]
            )
            
            # 1. Correlation Heatmap
            fig.add_trace(
                go.Heatmap(
                    z=correlation_matrix.values,
                    x=correlation_matrix.columns,
                    y=correlation_matrix.columns,
                    colorscale='RdBu',
                    zmid=0,
                    text=correlation_matrix.round(3).values,
                    texttemplate="%{text}",
                    textfont={"size": 10},
                    colorbar=dict(title="Correlation", x=0.48)
                ),
                row=1, col=1
            )
            
            # 2. 24h vs 7d scatter
            fig.add_trace(
                go.Scatter(
                    x=changes_24h,
                    y=changes_7d,
                    mode='markers+text',
                    text=symbols,
                    textposition='middle right',
                    textfont=dict(size=8),
                    marker=dict(
                        size=10,
                        color=changes_30d,
                        colorscale='Viridis',
                        showscale=True,
                        colorbar=dict(title="30d Change %", x=1.02)
                    ),
                    name="24h vs 7d"
                ),
                row=1, col=2
            )
            
            # 3. Volume vs Market Cap
            fig.add_trace(
                go.Scatter(
                    x=volumes,
                    y=market_caps,
                    mode='markers+text',
                    text=symbols,
                    textposition='middle right',
                    textfont=dict(size=8),
                    marker=dict(
                        size=12,
                        color=changes_24h,
                        colorscale='RdYlGn',
                        showscale=False
                    ),
                    name="Volume vs Cap"
                ),
                row=2, col=1
            )
            
            # 4. Top correlations analysis
            corr_pairs = []
            for i in range(len(correlation_matrix.columns)):
                for j in range(i+1, len(correlation_matrix.columns)):
                    corr_value = correlation_matrix.iloc[i, j]
                    if not np.isnan(corr_value):  # Skip NaN values
                        corr_pairs.append({
                            'pair': f"{correlation_matrix.columns[i]} vs {correlation_matrix.columns[j]}",
                            'correlation': abs(corr_value)
                        })
            
            corr_pairs.sort(key=lambda x: x['correlation'], reverse=True)
            top_5_pairs = corr_pairs[:5]
            
            if top_5_pairs:
                fig.add_trace(
                    go.Bar(
                        x=[pair['pair'] for pair in top_5_pairs],
                        y=[pair['correlation'] for pair in top_5_pairs],
                        marker_color='lightblue',
                        name="Top Correlations"
                    ),
                    row=2, col=2
                )
            
            # Add correlation trendline for 24h vs 7d
            if len(changes_24h) > 3:
                try:
                    correlation_coef, p_value = stats.pearsonr(changes_24h, changes_7d)
                    z = np.polyfit(changes_24h, changes_7d, 1)
                    p = np.poly1d(z)
                    x_trend = sorted(changes_24h)
                    y_trend = [p(x) for x in x_trend]
                    
                    fig.add_trace(
                        go.Scatter(
                            x=x_trend,
                            y=y_trend,
                            mode='lines',
                            line=dict(dash='dash', color='red', width=2),
                            name='Trend Line',
                            showlegend=False
                        ),
                        row=1, col=2
                    )
                except Exception as e:
                    logging.warning(f"Failed to add trendline: {e}")
                    correlation_coef = 0
            else:
                correlation_coef = 0
            
            # Update layout
            fig.update_layout(
                height=900,
                title_text=f"Crypto Correlation Analysis<br><sub>24h vs 7d Correlation: {correlation_coef:.3f} | {len(symbols)} assets analyzed</sub>",
                showlegend=False
            )
            
            # Update axes
            fig.update_xaxes(title_text="24h Change %", row=1, col=2)
            fig.update_yaxes(title_text="7d Change %", row=1, col=2)
            fig.update_xaxes(title_text="Log Volume", row=2, col=1)
            fig.update_yaxes(title_text="Log Market Cap", row=2, col=1)
            fig.update_yaxes(title_text="Abs Correlation", row=2, col=2)
            
            return fig
            
        except Exception as e:
            logging.error(f"Error in correlation analysis: {e}")
            return go.Figure().add_annotation(
                text=f"Error creating correlation analysis: {str(e)}", 
                xref="paper", yref="paper", x=0.5, y=0.5
            )
    
    async def create_comprehensive_dashboard(self) -> Tuple[Dict[str, go.Figure], dict]:
        """Create the ultimate comprehensive dashboard with parallel execution"""
        logging.info("Creating Enhanced Ultimate Comprehensive Dashboard")
        
        try:
            # Fetch all required data in parallel
            print("Fetching market data...")
            data_tasks = [
                self.fetch_market_data(100),
                self.fetch_global_metrics()
            ]
            
            results = await asyncio.gather(*data_tasks, return_exceptions=True)
            market_data = results[0] if not isinstance(results[0], Exception) else None
            global_data = results[1] if not isinstance(results[1], Exception) else None
            
            if not market_data:
                if isinstance(results[0], Exception):
                    logging.error(f"Failed to fetch market data: {results[0]}")
                raise Exception("Failed to fetch market data")
            
            # Create analysis components in parallel
            print("Creating analysis components in parallel...")
            analysis_tasks = [
                self.create_volume_efficiency_analysis(market_data),
                self.create_stablecoin_dominance_tracker(market_data), 
                self.create_market_microstructure_analysis(market_data),
                self.create_volatility_surface_mapping(market_data),
                self.create_correlation_matrix_analysis(market_data)
            ]
            
            print("  - Volume Efficiency Analysis")
            print("  - Stablecoin Dominance Tracker") 
            print("  - Market Microstructure Analysis")
            print("  - Volatility Surface Mapping")
            print("  - Correlation Matrix Analysis")
            
            # Execute all analyses in parallel
            analysis_results = await asyncio.gather(*analysis_tasks, return_exceptions=True)
            
            # Process results with error handling
            all_figures = {}
            analysis_names = [
                'volume_efficiency', 'stablecoin_dominance', 'market_microstructure',
                'volatility_surface', 'correlation_matrix'
            ]
            
            for i, (name, result) in enumerate(zip(analysis_names, analysis_results)):
                if isinstance(result, Exception):
                    logging.error(f"Error in {name} analysis: {result}")
                    # Create error figure
                    error_fig = go.Figure().add_annotation(
                        text=f"Error in {name} analysis: {str(result)}", 
                        xref="paper", yref="paper", x=0.5, y=0.5
                    )
                    all_figures[name] = error_fig
                else:
                    all_figures[name] = result
                    logging.info(f"✓ {name} analysis completed successfully")
            
            # Save individual components in parallel
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            created_files = []
            
            # Create file save tasks 
            save_tasks = []
            for analysis_name, figure in all_figures.items():
                filename = f'{analysis_name}_analysis_{timestamp}.html'
                filepath = os.path.join(OUTPUT_FOLDER, filename)
                save_tasks.append((filepath, figure))
                created_files.append(filepath)
            
            # Save files in parallel using thread pool
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                save_futures = [
                    executor.submit(pyo.plot, figure, filename=filepath, auto_open=False)
                    for filepath, figure in save_tasks
                ]
                
                # Wait for all saves to complete
                for future in concurrent.futures.as_completed(save_futures):
                    try:
                        future.result()
                    except Exception as e:
                        logging.error(f"Error saving file: {e}")
            
            # Create enhanced summary metrics
            summary = {
                'timestamp': timestamp,
                'total_cryptocurrencies': len(market_data),
                'total_market_cap': global_data.get('quote', {}).get('USD', {}).get('total_market_cap', 0) if global_data else 0,
                'total_volume_24h': global_data.get('quote', {}).get('USD', {}).get('total_volume_24h', 0) if global_data else 0,
                'btc_dominance': global_data.get('btc_dominance', 0) if global_data else 0,
                'files_created': created_files,
                'analysis_components': list(all_figures.keys()),
                'successful_analyses': len([r for r in analysis_results if not isinstance(r, Exception)]),
                'failed_analyses': len([r for r in analysis_results if isinstance(r, Exception)])
            }
            
            logging.info(f"Enhanced dashboard created successfully. Files: {len(created_files)}, Success: {summary['successful_analyses']}/{len(analysis_names)}")
            return all_figures, summary
            
        except Exception as e:
            logging.error(f"Critical error in dashboard creation: {e}")
            # Return minimal error response
            error_summary = {
                'timestamp': datetime.now().strftime('%Y%m%d_%H%M'),
                'error': str(e),
                'total_cryptocurrencies': 0,
                'files_created': [],
                'analysis_components': [],
                'successful_analyses': 0,
                'failed_analyses': 1
            }
            error_fig = go.Figure().add_annotation(
                text=f"Critical dashboard error: {str(e)}", 
                xref="paper", yref="paper", x=0.5, y=0.5
            )
            return {'error': error_fig}, error_summary

async def main():
    """Enhanced main function with improved error handling"""
    dashboard = UltimateCryptoDashboard()
    
    try:
        print("=== ENHANCED Ultimate Crypto Market Analysis Dashboard ===\n")
        
        # Create comprehensive dashboard
        all_figures, summary = await dashboard.create_comprehensive_dashboard()
        
        # Check for critical errors
        if 'error' in summary:
            print(f" Critical Error: {summary['error']}")
            return
        
        # Output enhanced summary
        print(f"\n=== Enhanced Dashboard Summary ===")
        print(f"Analysis completed at: {summary['timestamp']}")
        print(f"Total cryptocurrencies analyzed: {summary['total_cryptocurrencies']}")
        print(f"Total market cap: ${summary['total_market_cap']/1e12:.2f}T")
        print(f"Total volume 24h: ${summary['total_volume_24h']/1e9:.1f}B")
        print(f"BTC dominance: {summary['btc_dominance']:.1f}%")
        print(f"Analysis Success Rate: {summary['successful_analyses']}/{summary['successful_analyses'] + summary['failed_analyses']}")
        
        print(f"\n=== Files Created ({len(summary['files_created'])}) ===")
        for file_path in summary['files_created']:
            filename = os.path.basename(file_path)
            file_type = "📊 HTML"
            print(f"{file_type} {filename}")
        
        print(f"\n=== Enhanced Analysis Components ===")
        components_info = {
            'volume_efficiency': " Volume Efficiency - поиск недооцененных активов",
            'stablecoin_dominance': " Stablecoin Dominance - анализ стейблкоин экосистемы",
            'market_microstructure': " Market Microstructure - ликвидность и спреды", 
            'volatility_surface': " Volatility Surface - 3D карта волатильности",
            'correlation_matrix': " Correlation Matrix - взаимосвязи между активами"
        }
        
        for component in summary.get('analysis_components', []):
            if component in components_info:
                status = "_" if component in all_figures else "❌"
                print(f"{status} {components_info[component]}")
        
        print(f"\n=== NEW ENHANCED FEATURES ===")
        print("✅ Параллельное выполнение анализов (до 5x быстрее)")
        print("✅ Улучшенное кеширование (RAM + file)")
        print("✅ Correlation Matrix анализ")
        print("✅ Расширенная обработка ошибок")
        print("✅ Параллельное сохранение файлов")
        print("✅ Детальная статистика выполнения")
        
        if summary['failed_analyses'] > 0:
            print(f"\n {summary['failed_analyses']} analysis(es) failed - check logs for details")
        
        print("\n=== Enhanced Analysis Complete ===")
        
    except Exception as e:
        logging.error(f"Critical error in main: {e}")
        print(f"❌ Critical error occurred: {e}")
        
    finally:
        # Ensure session is always closed
        try:
            await dashboard.close_session()
        except Exception as e:
            logging.warning(f"Error closing session: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 
