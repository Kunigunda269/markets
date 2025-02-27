import asyncio
import aiohttp
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import time
import sys
import logging
from collections import deque

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(level=logging.INFO)

HEADERS = {'X-CMC_PRO_API_KEY': "831812bd-1186-43d4-b0d3-b71f0d61074e"}


def price_change_percentage(open_price, close_price):
    return ((close_price - open_price) / open_price) * 100


async def fetch_token_metadata(session, symbol):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/map"
    params = {"symbol": symbol}
    async with session.get(url, headers=HEADERS, params=params) as response:
        data = await response.text()
        logging.info(f"Response from fetch_token_metadata: {data}")
        if response.status == 200:
            data = await response.json()
            if data['data']:
                return data['data'][0]['id']
        return None


async def fetch_historical_data(session, crypto_id, time_start, time_end):
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
    params = {
        "id": crypto_id,
        "time_start": time_start,
        "time_end": time_end,
        "interval": "daily",
        "convert": "USD"
    }

    async with session.get(url, headers=HEADERS, params=params) as response:
        if response.status == 200:
            data = await response.json()
            quotes = data['data']['quotes']
            if len(quotes) >= 2:
                open_price = quotes[0]['quote']['USD']['price']
                close_price = quotes[-1]['quote']['USD']['price']
                return price_change_percentage(open_price, close_price)
        return None


async def fetch_top_100_cryptos(session, time_start, time_end):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    params = {"limit": 100, "sort": "market_cap", "sort_dir": "desc"}

    async with session.get(url, headers=HEADERS, params=params) as response:
        if response.status == 200:
            data = await response.json()
            cryptos = []

            for crypto in data['data']:
                if crypto['symbol'] not in ['USDT', 'USDC', 'BUSD', 'DAI']:
                    price_change = await fetch_historical_data(
                        session,
                        crypto['id'],
                        time_start,
                        time_end
                    )

                    if price_change is not None:
                        crypto_data = {
                            'symbol': crypto['symbol'],
                            'market_cap': crypto['quote']['USD']['market_cap'],
                            'price': crypto['quote']['USD']['price'],
                            'percent_change_24h': price_change
                        }
                        cryptos.append(crypto_data)

            return cryptos
        return []


def plot_heatmap(df, time_start, time_end):
    """Создание адаптивной тепловой карты"""
    # Оставляем существующую подготовку данных без изменений
    df['market_cap'] = (df['market_cap'] / 1e9).round(2)
    df['percent_change_24h'] = df['percent_change_24h'].round(2)
    total_market_cap = df['market_cap'].sum()
    df['dominance'] = (df['market_cap'] / total_market_cap * 100).round(2)
    df['size_factor'] = np.log10(df['market_cap'])
    df = df.sort_values('market_cap', ascending=False)

    # Оставляем логику уровней текста
    max_cap = df['market_cap'].max()
    df['text_level'] = 0
    df.loc[df['market_cap'] < max_cap * 0.002, 'text_level'] = 3
    df.loc[(df['market_cap'] >= max_cap * 0.002) & (df['market_cap'] < max_cap * 0.008), 'text_level'] = 2
    df.loc[(df['market_cap'] >= max_cap * 0.008) & (df['market_cap'] < max_cap * 0.03), 'text_level'] = 1

    # Оставляем существующую логику шаблонов текста
    def get_text_template(row):
        if row['text_level'] == 0:
            return (
                f"<b>{row['symbol']}</b><br>"
                f"${row['price']:,.2f}<br>"
                f"{row['percent_change_24h']:+.2f}%<br>"
                f"Dom: {row['dominance']:.2f}%"
            )
        elif row['text_level'] == 1:
            return (
                f"<b>{row['symbol']}</b><br>"
                f"${row['price']:,.2f}<br>"
                f"{row['percent_change_24h']:+.2f}%"
            )
        elif row['text_level'] == 2:
            return f"<b>{row['symbol']}</b><br>{row['percent_change_24h']:+.2f}%"
        else:
            return f"<b>{row['symbol']}</b>"

    df['display_text'] = df.apply(get_text_template, axis=1)

    # Кастомная цветовая схема
    def get_color(pct_change):
        abs_change = abs(pct_change)
        if abs_change < 1:
            return 'rgb(179,179,179)'
        elif pct_change > 0:
            if abs_change < 2:
                return '#B6e880'
            elif abs_change < 3:
                return '#00cc96'
            elif abs_change < 4:
                return '#54a24b'
            elif abs_change < 5:
                return '#66aa00'
            elif abs_change < 6:
                return '#109618'
            elif abs_change < 7:
                return '#16ff32'
            elif abs_change < 8:
                return '#86ce00'
            else:
                return '#00fe35'
        else:
            if abs_change < 2:
                return 'rgb(253,218,236)'
            elif abs_change < 3:
                return '#e48f72'
            elif abs_change < 4:
                return '#fc6955'
            elif abs_change < 5:
                return '#f6222e'
            elif abs_change < 6:
                return 'rgb(237,100,90)'
            elif abs_change < 7:
                return '#fb0d0d'
            elif abs_change < 8:
                return 'rgb(228,26,28)'
            else:
                return '#fd3216'

    df['color'] = df['percent_change_24h'].apply(get_color)

    # Создаем тепловую карту
    fig = px.treemap(
        df,
        path=[px.Constant(""), 'symbol'],
        values='size_factor',
        color='percent_change_24h',
        custom_data=['symbol', 'market_cap', 'percent_change_24h', 'dominance', 'display_text', 'price', 'color']
    )

    # Обновляем настройки отображения для лучшей поддержки мобильных устройств
    fig.update_traces(
        textposition="middle center",
        texttemplate='%{customdata[4]}',
        textfont=dict(
            size=11,
            weight="bold",
            color="black"
        ),
        marker=dict(
            colors=df['color'],
            pad=dict(t=0, l=0, r=0, b=0),
            cornerradius=0
        ),
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Price: $%{customdata[5]:,.2f}<br>"
            "Market Cap: $%{customdata[1]:.2f}B<br>"
            "Change: %{customdata[2]:+.2f}%<br>"
            "Dominance: %{customdata[3]:.2f}%<br>"
            "<extra></extra>"
        )
    )

    # Обновляем layout для адаптивности
    fig.update_layout(
        autosize=True,  # Включаем автоматическое изменение размера
        margin=dict(t=50, l=5, r=50, b=5),
        title=dict(
            text=f"Crypto Market Heatmap ({time_start} to {time_end})",
            x=0.5,
            y=0.98,
            xanchor='center',
            yanchor='top',
            font=dict(size=16)
        ),
        coloraxis_showscale=True,
        coloraxis=dict(
            cmin=-30,
            cmax=30,
            colorscale=[
                [0, '#ff0000'],
                [0.4, '#ffb6b6'],
                [0.5, '#808080'],
                [0.6, '#b6ffb6'],
                [1, '#00ff00']
            ],
            colorbar=dict(
                title=dict(text="Change %", side="right"),
                tickformat=".0f",
                ticksuffix="%",
                len=0.75,
                thickness=15,
                x=1.02,
                xanchor="left",
                yanchor="middle"
            )
        )
    )

    # Сохраняем с адаптивным HTML шаблоном
    html_file = r"C:\Users\Main\Pitonio\crypto etf\heatmap.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write("""
           <!DOCTYPE html>
           <html lang="en">
           <head>
               <meta charset="UTF-8">
               <meta name="viewport" content="width=device-width, initial-scale=1.0">
               <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
               <style>
                   body {
                       margin: 0;
                       padding: 0;
                       width: 100%;
                       height: 100vh;
                   }
                   #heatmap {
                       width: 100%;
                       height: 100vh;
                   }
                   @media screen and (max-width: 768px) {
                       .js-plotly-plot .plotly {
                           font-size: 12px;
                       }
                   }
               </style>
           </head>
           <body>
               <div id="heatmap"></div>
               <script>
                   var fig = """ + fig.to_json() + """;
                   var config = {
                       responsive: true,
                       displayModeBar: true,
                       displaylogo: false,
                       modeBarButtonsToRemove: [
                           'zoom2d',
                           'pan2d',
                           'select2d',
                           'lasso2d',
                           'zoomIn2d',
                           'zoomOut2d',
                           'autoScale2d'
                       ]
                   };
                   Plotly.newPlot('heatmap', fig.data, fig.layout, config);

                   // Обработчик изменения размера окна
                   window.addEventListener('resize', function() {
                       Plotly.Plots.resize('heatmap');
                   });

                   // Оптимизация для мобильных устройств
                   if (window.innerWidth <= 768) {
                       fig.layout.title.font.size = 14;
                       fig.layout.margin = {t: 30, l: 5, r: 30, b: 5};
                       Plotly.newPlot('heatmap', fig.data, fig.layout, config);
                   }
               </script>
           </body>
           </html>
           """)

    # Показываем график
    fig.show()
    fig.write_html(
        r"C:\Users\Main\Pitonio\crypto etf\heatmap.html",
        include_plotlyjs='cdn',
        full_html=True
    )


async def main():
    test_mode = input("Выполнить тестовый запрос? (y/n): ").lower()

    if test_mode == 'y':
        symbol = input("Введите тикер криптовалюты для теста (например, BTC, ETH): ").upper()
        time_start = input("Введите начальную дату для теста (YYYY-MM-DD): ")
        time_end = input("Введите конечную дату для теста (YYYY-MM-DD): ")

        async with aiohttp.ClientSession() as session:
            crypto_id = await fetch_token_metadata(session, symbol)
            if crypto_id:
                data = await fetch_historical_data(session, crypto_id, time_start, time_end)
                if data:
                    print("\nТестовый запрос выполнен успешно!")
                    proceed = input("\nПродолжить с основным запросом? (y/n): ")
                    if proceed.lower() != 'y':
                        return
                else:
                    print("Не удалось получить тестовые данные.")
                    return
            else:
                print("Не удалось найти указанную криптовалюту.")
                return

    print("\n=== Основной запрос ===")
    time_start_main = input("Введите начальную дату для основного запроса (YYYY-MM-DD): ")
    time_end_main = input("Введите конечную дату для основного запроса (YYYY-MM-DD): ")

    async with aiohttp.ClientSession() as session:
        print("\nПолучение данных...")
        cryptos = await fetch_top_100_cryptos(session, time_start_main, time_end_main)
        if cryptos:
            print("Данные получены успешно!")
            print("Создание визуализации...")
            df = pd.DataFrame(cryptos)
            plot_heatmap(df, time_start_main, time_end_main)
            print("Визуализация сохранена!")
        else:
            print("Не удалось получить данные о топ-100 криптовалютах.")


if __name__ == "__main__":
    asyncio.run(main())