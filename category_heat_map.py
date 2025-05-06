import asyncio
import aiohttp
import pandas as pd
import plotly.express as px
import os
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
from collections import deque
import sys


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Конфигурация
OUTPUT_DIR = r"C:\Users\Main\Pitonio\crypto_etf"
CATEGORY_FILE = r"C:\Users\Main\Pitonio\crypto_etf\category_downloader.xlsx"
API_KEY = "123"

logging.basicConfig(level=logging.INFO)


class RateLimiter:
    def __init__(self, requests_per_minute: int = 30):
        self.requests_per_minute = requests_per_minute
        self.interval = 66  # 66 секунд для большей надежности
        self.requests = deque()

    async def acquire(self):
        now = time.time()

        # Удаляем старые запросы
        while self.requests and now - self.requests[0] > self.interval:
            self.requests.popleft()

        # Если достигли лимита, ждем
        if len(self.requests) >= self.requests_per_minute:
            wait_time = self.interval - (now - self.requests[0])
            if wait_time > 0:
                logging.info(f"Rate limit reached. Waiting {wait_time:.2f} seconds...")
                await asyncio.sleep(wait_time)

        self.requests.append(time.time())


# Создаем глобальный rate limiter
rate_limiter = RateLimiter()


async def get_token_metadata(session: aiohttp.ClientSession, symbol: str) -> dict:
    """Получение метаданных токена"""
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/info"
    headers = {
        "X-CMC_PRO_API_KEY": API_KEY,
        "Accept": "application/json"
    }

    try:
        await rate_limiter.acquire()  # Ждем, если достигнут лимит запросов
        map_url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/map"
        async with session.get(map_url, params={"symbol": symbol}, headers=headers) as response:
            if response.status != 200:
                logging.error(f"API error: {response.status}")
                return None
            map_data = await response.json()
            for token in map_data.get('data', []):
                if token['symbol'].upper() == symbol.upper():
                    return token
            return None
    except Exception as e:
        logging.error(f"Error getting metadata for {symbol}: {e}")
        return None


async def get_historical_quotes(session: aiohttp.ClientSession, token_id: int, date_start: str, date_end: str) -> dict:
    """Получение исторических данных"""
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
    headers = {
        "X-CMC_PRO_API_KEY": API_KEY,
        "Accept": "application/json"
    }
    params = {
        "id": token_id,
        "time_start": f"{date_start}T00:00:00Z",
        "time_end": f"{date_end}T23:59:59Z",
        "interval": "daily",
        "count": 2,  # Запрашиваем только 2 точки данных
        "convert": "USD"
    }

    try:
        print(f"Запрос к API для токена ID {token_id}...")
        await rate_limiter.acquire()
        async with session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                data = await response.json()
                print(f"Успешно получены данные для токена ID {token_id}")
                return data
            elif response.status == 429:
                print(f"Достигнут лимит запросов для токена ID {token_id}. Ожидание...")
                logging.error(f"Rate limit exceeded for ID: {token_id}. Waiting...")
                await asyncio.sleep(66)
                return await get_historical_quotes(session, token_id, date_start, date_end)
            else:
                print(f"Ошибка API {response.status} для токена ID {token_id}")
                logging.error(f"API error: {response.status}")
                error_data = await response.json()
                logging.error(f"API response: {error_data}")
                return None
    except Exception as e:
        print(f"Ошибка при получении данных для токена ID {token_id}: {e}")
        logging.error(f"Error getting historical data for token {token_id}: {e}")
        return None


async def get_token_historical_data(session: aiohttp.ClientSession, token_id: int, symbol: str, date_start: str,
                                    date_end: str) -> dict:
    """Получение исторических данных токена"""
    try:
        # Проверка дат
        start_date = datetime.strptime(date_start, "%Y-%m-%d").date()
        end_date = datetime.strptime(date_end, "%Y-%m-%d").date()
        current_date = datetime.now().date()

        # Проверка дат на будущее
        if start_date > current_date:
            print(f"Ошибка: Дата начала {date_start} находится в будущем")
            print(f"Текущая дата: {current_date}")
            return None

        if end_date > current_date:
            print(f"Ошибка: Дата окончания {date_end} находится в будущем")
            print(f"Текущая дата: {current_date}")
            return None

        if start_date > end_date:
            print(f"Ошибка: Дата начала {date_start} позже даты окончания {date_end}")
            return None

        print(f"Получение исторических данных для {symbol} (ID: {token_id})...")
        historical_data = await get_historical_quotes(session, token_id, date_start, date_end)

        if not historical_data:
            logging.error(f"No historical data received for {symbol}")
            return None

        if 'status' in historical_data and historical_data['status']['error_code'] != 0:
            error_message = historical_data['status']['error_message']
            logging.error(f"API error: {error_message}")
            print(f"Ошибка API: {error_message}")
            return None

        quotes = historical_data.get('data', {}).get('quotes', [])
        if len(quotes) < 2:  # Нужно минимум 2 точки данных
            print(f"Недостаточно данных для {symbol} (ID: {token_id})")
            return None

        # Берем первую и последнюю точки данных
        start_price = quotes[0]['quote']['USD']['price']
        end_price = quotes[-1]['quote']['USD']['price']
        market_cap = quotes[-1]['quote']['USD']['market_cap']

        percent_change = ((end_price - start_price) / start_price) * 100

        return {
            'id': token_id,
            'symbol': symbol,
            'start_price': start_price,
            'end_price': end_price,
            'market_cap': market_cap,
            'percent_change': percent_change
        }

    except Exception as e:
        logging.error(f"Error processing data for {symbol}: {e}")
        print(f"Ошибка при обработке данных для {symbol}: {e}")
        return None


class CategoryProcessor:
    def __init__(self, category_file: str):
        self.category_file = Path(category_file)
        self.tokens_df = self._load_categories()
        self.token_ids = {}  # Кэш для ID токенов

    def _load_categories(self) -> pd.DataFrame:
        """Загрузка категорий из Excel файла"""
        try:
            # Читаем Excel файл, указывая правильные столбцы
            df = pd.read_excel(
                self.category_file,
                usecols=[1, 2, 3],  # Столбцы B, C, D (индексы 1, 2, 3)
                names=['Name', 'Symbol', 'Category']  # Задаем имена столбцов
            )

            # Удаляем пустые значения и дубликаты
            df = df.dropna(subset=['Symbol', 'Category']).drop_duplicates()

            # Преобразуем символы в верхний регистр
            df['Symbol'] = df['Symbol'].str.upper()

            return df

        except Exception as e:
            logging.error(f"Error reading category file {self.category_file}: {e}")
            raise FileNotFoundError(f"Cannot read category file: {e}")

    async def get_token_id(self, session: aiohttp.ClientSession, symbol: str) -> Optional[int]:
        """Получение ID токена по символу"""
        if symbol in self.token_ids:
            return self.token_ids[symbol]

        await rate_limiter.acquire()
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/map"
        headers = {
            "X-CMC_PRO_API_KEY": API_KEY,
            "Accept": "application/json"
        }

        try:
            async with session.get(url, params={"symbol": symbol}, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    for token in data.get('data', []):
                        if token['symbol'].upper() == symbol.upper():
                            self.token_ids[symbol] = token['id']
                            return token['id']
        except Exception as e:
            logging.error(f"Error getting ID for {symbol}: {e}")
        return None

    def get_sorted_categories(self) -> list:
        return sorted(self.tokens_df['Category'].unique())

    def get_category_tokens(self, category: str) -> list:
        return self.tokens_df[self.tokens_df['Category'] == category]['Symbol'].tolist()


class HeatmapCreator:
    def __init__(self, width: int = 1632, height: int = 680, output_dir: str = OUTPUT_DIR):
        self.width = width
        self.height = height
        self.output_dir = output_dir
        self.color_scale = [[0, 'red'], [0.5, 'gray'], [1, 'green']]
        self.max_tokens = 50

    def create_and_save_heatmap(self, tokens_data: list, category: str,
                                date_start: str, date_end: str) -> str:
        df = pd.DataFrame(tokens_data)

        # Сортировка по market_cap и ограничение до 50 токенов
        df = df.sort_values('market_cap', ascending=False).head(self.max_tokens)

        # Добавляем ранг для размера ячеек
        df['rank'] = pd.qcut(df['market_cap'], q=min(9, len(df)), labels=False) + 1

        fig = px.treemap(
            df,
            path=[px.Constant(category), 'symbol'],
            values='market_cap',
            color='percent_change',
            color_continuous_scale=self.color_scale,
            color_continuous_midpoint=0,
            custom_data=['symbol', 'start_price', 'percent_change', 'market_cap'],
            range_color=[-30, 30]  # Устанавливаем диапазон для цветовой шкалы
        )

        fig.update_layout(
            width=self.width,
            height=self.height,
            title=f"{category} Market Heatmap ({date_start} to {date_end})",
            treemapcolorway=['#1f77b4'] * 50,  # единый цвет для фона
            coloraxis=dict(
                cmin=-30,  # Минимальное значение шкалы
                cmax=30,  # Максимальное значение шкалы
                colorbar=dict(
                    title="Change %",  # Переименовываем шкалу
                    tickformat=".2f",  # Два знака после запятой в легенде
                    ticksuffix="%",  # Добавляем знак процента к значениям в легенде
                    tickfont=dict(  # Настройка шрифта делений
                        size=12,
                        family="Arial"
                    ),
                    title_font=dict(  # Настройка шрифта заголовка
                        size=14,
                        family="Arial"
                    ),
                    len=0.9,  # Длина цветовой шкалы
                    thickness=20  # Толщина цветовой шкалы
                )
            ),
            uniformtext=dict(
                mode='hide',
                minsize=10
            )
        )

        # Обновляем формат отображения текста
        fig.update_traces(
            textposition="middle center",  # Центрирование текста
            textfont=dict(
                size=16,  # Увеличенный базовый размер шрифта
                family="Arial",
                color="black"
            ),
            texttemplate=(
                "<b>%{customdata[0]}</b><br>"  # Символ токена
                "$%{customdata[1]:.4f}<br>"  # Цена с 4 знаками после запятой
                "%{customdata[2]:+.2f}%"  # Процентное изменение с 2 знаками
            ),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Price: $%{customdata[1]:.4f}<br>"
                "Change: %{customdata[2]:+.2f}%<br>"
                "MCap: $%{customdata[3]:,.0f}"
                "<extra></extra>"
            ),
            tiling=dict(
                packing="binary",
                pad=2  # Увеличиваем отступы между ячейками
            ),
            root_color="lightgrey",  # Цвет корневой ячейки
            marker=dict(
                cornerradius=5  # Скругление углов ячеек
            )
        )

        output_path = Path(self.output_dir) / f"{category.lower().replace(' ', '_')}_heatmap.html"
        fig.write_html(output_path, include_plotlyjs='cdn')
        return str(output_path)


async def main():
    try:
        # Запрос на тестовый режим
        while True:
            test_mode = input("Выполнить тестовый запрос? (y/n): ").lower()
            if test_mode in ['y', 'n']:
                break
            print("Пожалуйста, введите 'y' для да или 'n' для нет")

        if test_mode == 'y':
            # Тестовый режим
            while True:
                try:
                    token_id = int(input("Введите ID токена (например, 1 для BTC, 1027 для ETH): "))
                    break
                except ValueError:
                    print("Пожалуйста, введите числовой ID токена")

            symbol = input("Введите тикер криптовалюты (для отображения): ").upper()
            date_start = input("Введите начальную дату (YYYY-MM-DD): ")
            date_end = input("Введите конечную дату (YYYY-MM-DD): ")

            async with aiohttp.ClientSession() as session:
                result = await get_token_historical_data(session, token_id, symbol, date_start, date_end)

                if result:
                    print(f"\nРезультаты для {symbol} (ID: {token_id}):")
                    print(f"Цена на {date_start}: ${result['start_price']:.4f}")
                    print(f"Цена на {date_end}: ${result['end_price']:.4f}")
                    print(f"Изменение: {result['percent_change']:+.2f}%")
                else:
                    print(f"Не удалось получить данные для {symbol} (ID: {token_id})")

            # Добавляем запрос на продолжение
            continue_after_test = input("\nПродолжить с основным режимом? (y/n): ").lower()
            if continue_after_test != 'y':
                return

        # Основной режим
        if not os.path.exists(CATEGORY_FILE):
            print(f"Ошибка: Файл категорий не найден: {CATEGORY_FILE}")
            return

        # Загрузка и вывод категорий
        processor = CategoryProcessor(CATEGORY_FILE)
        categories = processor.get_sorted_categories()

        print("\nДоступные категории:")
        for idx, category in enumerate(categories, 1):
            token_count = len(processor.get_category_tokens(category))
            print(f"{idx}. {category} ({token_count} токенов)")

        # Выбор категории
        while True:
            try:
                category_idx = int(input("\nВыберите номер категории: "))
                if 1 <= category_idx <= len(categories):
                    break
                print(f"Пожалуйста, введите число от 1 до {len(categories)}")
            except ValueError:
                print("Пожалуйста, введите корректный номер категории")

        selected_category = categories[category_idx - 1]
        tokens = processor.get_category_tokens(selected_category)

        # Ввод дат
        date_start = input("Введите начальную дату (YYYY-MM-DD): ")
        date_end = input("Введите конечную дату (YYYY-MM-DD): ")

        print(f"\nЗагрузка данных для категории {selected_category}...")

        # Получение данных токенов
        async with aiohttp.ClientSession() as session:
            # Сначала получаем ID всех токенов
            print("\nПолучение ID токенов...")
            token_ids = {}  # Используем словарь для избежания дубликатов
            for symbol in tokens:
                if symbol not in token_ids:  # Проверяем, не получали ли мы уже ID для этого символа
                    token_id = await processor.get_token_id(session, symbol)
                    if token_id:
                        token_ids[symbol] = token_id
                        print(f"Получен ID {token_id} для токена {symbol}")
                    else:
                        print(f"Не удалось получить ID для токена {symbol}")

            print(f"\nНайдено {len(token_ids)} уникальных токенов")
            print("Получение исторических данных...")

            # Теперь получаем исторические данные используя ID
            tasks = [
                get_token_historical_data(session, token_id, symbol, date_start, date_end)
                for symbol, token_id in token_ids.items()
            ]

            # Используем gather с return_exceptions=True для обработки ошибок
            results = await asyncio.gather(*tasks, return_exceptions=True)
            tokens_data = []

            for result, (symbol, token_id) in zip(results, token_ids.items()):
                if isinstance(result, Exception):
                    print(f"Ошибка при обработке {symbol} (ID: {token_id}): {result}")
                elif result:
                    tokens_data.append(result)
                    print(f"Успешно обработан токен {symbol} (ID: {token_id})")

            if not tokens_data:
                print("\nНе удалось получить данные для токенов")
                return

            print(f"\nУспешно получены данные для {len(tokens_data)} токенов")
            print("Создание тепловой карты...")

            # Создание тепловой карты
            heatmap = HeatmapCreator(output_dir=r"C:\Users\Main\Pitonio\crypto_etf")
            output_path = heatmap.create_and_save_heatmap(
                tokens_data, selected_category, date_start, date_end
            )
            print(f"\nТепловая карта сохранена: {output_path}")

    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
        print(f"Произошла критическая ошибка: {e}")


if __name__ == "__main__":
    asyncio.run(main())
