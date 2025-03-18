import asyncio
import aiohttp
import pandas as pd
import plotly.graph_objects as go
import logging
from datetime import datetime
from tqdm import tqdm
import os
import ssl
import certifi
import re

# Конфигурация логирования
logging.basicConfig(
    filename='crypto_api.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
# Конфигурация для сохранения данных
CONFIG = {
    "max_requests_per_minute": 30,
    "batch_size": 50,
    "input_file": r"C:\Users\Main\Pitonio\crypto_etf\category_downloader_new.xlsx",
    "output_folder": r"C:\Users\Main\Pitonio\crypto_etf\results",
    "save_path": r"C:\Users\Main\Pitonio\crypto_etf"
}

# Создаем директории если они не существуют
os.makedirs(CONFIG["output_folder"], exist_ok=True)
os.makedirs(CONFIG["save_path"], exist_ok=True)

# Конфигурация API
API_KEY = "123"
BASE_URL = "https://pro-api.coinmarketcap.com/v2"
HEADERS = {
    "X-CMC_PRO_API_KEY": API_KEY,
    "Accept": "application/json"
}

# Определяем даты для анализа
ANALYSIS_DATES = [
    ("2024-12-08", "2024-12-09"),
    ("2024-12-15", "2024-12-16"),
    ("2024-12-22", "2024-12-23"),
    ("2024-12-29", "2024-12-30"),
    ("2025-01-05", "2025-01-06"),
    ("2025-01-12", "2025-01-13"),
    ("2025-01-18", "2025-01-19"),
    ("2025-01-25", "2025-01-26"),
    ("2025-02-01", "2025-02-02"),
    ("2025-02-08", "2025-02-09"),
    ("2025-02-15", "2025-02-16"),
    ("2025-02-22", "2025-02-23"),
    ("2025-03-01", "2025-03-02"),
    ("2025-03-08", "2025-03-09"),
    ("2025-03-15", "2025-03-16")
]


class APIHandler:
    def __init__(self):
        self.session = None
        self.last_request_time = 0

    async def _get_session(self):
        """Создание или получение существующей сессии"""
        if self.session is None:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self.session = aiohttp.ClientSession(connector=connector)
        return self.session

    async def get_token_info(self, query: str):
        """Get token information by ID or ticker"""
        session = await self._get_session()

        try:
            endpoint = f"{BASE_URL}/cryptocurrency/info"
            params = {"id": query} if query.isdigit() else {"symbol": query.upper()}

            print(f"Requesting data from {endpoint} with params: {params}")
            logging.info(f"Requesting data from {endpoint} with params: {params}")

            async with session.get(endpoint, headers=HEADERS, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"API Response: {data}")  # Debug print
                    logging.info(f"API Response received: {data}")
                    
                    if data.get("status", {}).get("error_code") == 0 and data.get("data"):
                        token_data = next(iter(data["data"].values()))
                        if isinstance(token_data, list):
                            token_data = token_data[0]
                        return {
                            "id": token_data["id"],
                            "symbol": token_data["symbol"],
                            "name": token_data["name"]
                        }
                    
                    error_message = data.get("status", {}).get("error_message", "Unknown error")
                    logging.warning(f"Token {query} not found. Error: {error_message}")
                    print(f"API Error: {error_message}")
                    return None
                else:
                    error_message = f"API Error {response.status}"
                    logging.error(f"{error_message} for query {query}")
                    print(f"{error_message}")
                    return None
        except Exception as e:
            logging.error(f"Error getting token info: {e}")
            print(f"Error: {e}")
            return None

    async def get_historical_data(self, token_id: int, date_start: str, date_end: str):
        """Получение исторических данных токена"""
        session = await self._get_session()

        try:
            # Проверка корректности дат
            start_date = datetime.strptime(date_start, '%Y-%m-%d').date()
            end_date = datetime.strptime(date_end, '%Y-%m-%d').date()
            
            if end_date < start_date:
                logging.error(f"Дата окончания {date_end} меньше даты начала {date_start}")
                return None

            endpoint = f"{BASE_URL}/cryptocurrency/quotes/historical"
            params = {
                "id": str(token_id),
                "time_start": f"{date_start}T00:00:00Z",
                "time_end": f"{date_end}T23:59:59Z",
                "interval": "1d",
                "convert": "USD"
            }

            async with session.get(endpoint, headers=HEADERS, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("data", {}).get("quotes"):
                        quotes = data["data"]["quotes"]
                        results = []
                        for quote in quotes:
                            usd_data = quote["quote"]["USD"]
                            results.append({
                                "date": quote["timestamp"][:10],  # Берем только дату
                                "price": usd_data["price"],
                                "market_cap": usd_data["market_cap"]
                            })
                        return results
                    logging.warning(f"Нет данных для токена ID {token_id} за период {date_start} - {date_end}")
                    return None
                else:
                    logging.error(f"Ошибка API {response.status} для исторических данных")
                    return None
        except ValueError as e:
            logging.error(f"Ошибка формата даты: {e}")
            return None
        except Exception as e:
            logging.error(f"Ошибка при получении исторических данных: {e}")
            return None

    async def close(self):
        """Закрытие сессии"""
        if self.session:
            await self.session.close()
            self.session = None


class DataProcessor:
    """Обработка и анализ данных по категориям"""

    def __init__(self):
        # Базовая директория
        self.base_dir = r"C:\Users\Main\Pitonio\crypto_etf"
        self.category_file = os.path.join(self.base_dir, "category_downloader_new.xlsx")

        # Динамическое получение списка result файлов
        self.result_files = self._get_result_files()
        self.categories_df = None
        self._load_categories()

    def _get_result_files(self):
        """Динамическое получение списка result файлов"""
        try:
            files = []
            pattern = r"result_\d{4}-\d{2}-\d{2}_to_\d{4}-\d{2}-\d{2}\.xlsx"

            # Сканируем директорию на наличие файлов result
            for file in os.listdir(self.base_dir):
                if re.match(pattern, file):
                    full_path = os.path.join(self.base_dir, file)
                    files.append(full_path)

            # Сортируем файлы по дате
            files.sort(key=lambda x: re.findall(r'\d{4}-\d{2}-\d{2}', x)[0])

            if not files:
                logging.warning("Файлы result не найдены")
            else:
                logging.info(f"Найдено {len(files)} файлов result")

            return files

        except Exception as e:
            logging.error(f"Ошибка при поиске result файлов: {e}")
            return []

    def _load_categories(self):
        """Загрузка данных категорий"""
        try:
            if not os.path.exists(self.category_file):
                print(f"Файл категорий не найден: {self.category_file}")
                logging.error(f"Файл категорий не найден: {self.category_file}")
                raise FileNotFoundError(f"Файл категорий не найден: {self.category_file}")

            print(f"Начинаю загрузку файла категорий: {self.category_file}")
            logging.info(f"Начинаю загрузку файла категорий: {self.category_file}")
            
            # Пробуем загрузить только нужные столбцы
            try:
                print("Пробую загрузить только столбцы C и D...")
                self.categories_df = pd.read_excel(
                    self.category_file,
                    engine='openpyxl',
                    usecols=[2, 3],  # Столбцы C и D
                    names=['Symbol', 'Category']  # Сразу задаем имена столбцов
                )
                
                print(f"Файл успешно загружен")
                print(f"Размер DataFrame: {self.categories_df.shape}")
                print(f"Столбцы: {self.categories_df.columns.tolist()}")
                
            except Exception as e:
                print(f"Ошибка при загрузке файла: {str(e)}")
                logging.error(f"Ошибка при загрузке файла: {str(e)}")
                raise

            # Очищаем данные
            original_length = len(self.categories_df)
            self.categories_df = self.categories_df.dropna(subset=['Symbol', 'Category'])
            cleaned_length = len(self.categories_df)
            
            print(f"Строк до очистки: {original_length}")
            print(f"Строк после очистки: {cleaned_length}")
            print(f"Удалено пустых строк: {original_length - cleaned_length}")
            
            if not self.categories_df.empty:
                print(f"Уникальные категории: {self.categories_df['Category'].unique().tolist()}")
                print(f"Количество уникальных токенов: {len(self.categories_df['Symbol'].unique())}")
                print("\nПример данных:")
                print(self.categories_df.head().to_string())
            else:
                raise ValueError("После очистки данных DataFrame пуст")

            logging.info(f"Загружено {len(self.categories_df)} токенов из {len(self.categories_df['Category'].unique())} категорий")
            
        except Exception as e:
            print(f"Ошибка загрузки категорий: {str(e)}")
            logging.error(f"Ошибка загрузки категорий: {str(e)}")
            raise

    def refresh_result_files(self):
        """Обновление списка result файлов"""
        self.result_files = self._get_result_files()
        return len(self.result_files)

    async def process_tokens(self, input_file, output_folder, time_start, time_end):
        try:
            # Проверяем валидность дат
            current_date = datetime.now().date()
            end_date = datetime.strptime(time_end[:10], '%Y-%m-%d').date()

            if end_date > current_date + timedelta(days=1):  # Разрешаем текущий день
                logging.warning(f"Дата {time_end[:10]} находится в будущем. Пропускаем период.")
                return None

            # Проверяем существование файлов и директорий
            if not os.path.exists(input_file):
                logging.error(f"Входной файл не найден: {input_file}")
                return None

            os.makedirs(output_folder, exist_ok=True)

            # Читаем и подготавливаем данные
            data = pd.read_excel(input_file)
            data = data.dropna(subset=["Id", "Symbol"])
            data["Id"] = data["Id"].astype(int)
            tokens = data[["Id", "Symbol"]].to_dict(orient="records")

            if not tokens:
                logging.warning("Нет данных для обработки")
                return None

            logging.info(f"Загружено {len(tokens)} токенов для обработки")

            # Создаем SSL контекст
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            processed_tokens = {}
            all_results = []

            async def fetch_batch_data(session, batch, time_start, time_end, processed_tokens):
                """Получение данных для пакета токенов"""
                results = []

                for token in batch:
                    try:
                        # Пропускаем уже обработанные токены
                        if token["Id"] in processed_tokens:
                            continue

                        endpoint = f"{BASE_URL}/cryptocurrency/quotes/historical"
                        params = {
                            "id": str(token["Id"]),
                            "time_start": f"{time_start}T00:00:00Z",
                            "time_end": f"{time_end}T23:59:59Z",
                            "interval": "1d",
                            "convert": "USD"
                        }

                        async with session.get(endpoint, headers=HEADERS, params=params) as response:
                            if response.status == 200:
                                data = await response.json()
                                if data.get("data", {}).get("quotes"):
                                    quotes = data["data"]["quotes"]
                                    for quote in quotes:
                                        usd_data = quote["quote"]["USD"]
                                        results.append({
                                            "Id": token["Id"],
                                            "Symbol": token["Symbol"],
                                            "Date": quote["timestamp"][:10],
                                            "Price (USD)": usd_data["price"],
                                            "Market Cap": usd_data["market_cap"],
                                            "Volume": usd_data.get("volume_24h", 0)
                                        })
                                    processed_tokens[token["Id"]] = True
                                    logging.info(f"Успешно получены данные для токена {token['Symbol']}")
                                else:
                                    logging.warning(f"Нет данных для токена {token['Symbol']}")
                            else:
                                logging.error(f"Ошибка API {response.status} для токена {token['Symbol']}")

                        # Задержка между запросами для соблюдения лимитов API
                        await asyncio.sleep(60 / CONFIG["max_requests_per_minute"])

                    except Exception as e:
                        logging.error(f"Ошибка при получении данных для токена {token['Symbol']}: {e}")
                        continue

                return results

            # Обработка токенов пакетами
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
                for i in range(0, len(tokens), CONFIG["batch_size"]):
                    batch = tokens[i:i + CONFIG["batch_size"]]
                    logging.info(f"Обработка пакета {i // CONFIG['batch_size'] + 1}...")

                    batch_results = await fetch_batch_data(session, batch, time_start, time_end, processed_tokens)
                    if batch_results:
                        all_results.extend(batch_results)

                    logging.info(f"Пакет {i // CONFIG['batch_size'] + 1} обработан")

            if not all_results:
                logging.warning("Нет результатов для сохранения")
                return None

            # Сохранение результатов
            output_file = os.path.join(
                output_folder,
                f"result_{time_start[:10]}_to_{time_end[:10]}.xlsx"
            )

            try:
                df = pd.DataFrame(all_results)
                df.to_excel(output_file, index=False)

                if os.path.exists(output_file):
                    file_size = os.path.getsize(output_file)
                    logging.info(f"Результаты сохранены в {output_file} (размер: {file_size:,} байт)")
                    return output_file
                else:
                    logging.error("Не удалось создать файл")
                    return None

            except Exception as e:
                logging.error(f"Ошибка при сохранении файла: {e}")
                return None

        except Exception as e:
            logging.error(f"Ошибка при обработке токенов: {e}")
            return None

    def process_data(self):
        """Обработка данных по категориям"""
        try:
            # Проверяем загрузку категорий
            if self.categories_df is None or self.categories_df.empty:
                logging.error("DataFrame категорий пуст или не инициализирован")
                return pd.DataFrame()

            # Получаем список всех файлов результатов
            results_folder = os.path.join(self.base_dir, "results")
            if not os.path.exists(results_folder):
                logging.error(f"Папка с результатами не найдена: {results_folder}")
                return pd.DataFrame()

            result_files = [f for f in os.listdir(results_folder) if f.startswith('result_') and f.endswith('.xlsx')]
            result_files.sort(key=lambda x: re.findall(r'\d{4}-\d{2}-\d{2}', x)[0])

            if not result_files:
                logging.error("Файлы результатов не найдены")
                return pd.DataFrame()

            print(f"\nОбработка {len(result_files)} файлов результатов...")

            all_results = []
            categories = self.categories_df['Category'].unique()
            
            for result_file in result_files:
                try:
                    file_path = os.path.join(results_folder, result_file)
                    print(f"\nОбработка файла: {result_file}")
                    
                    # Извлекаем дату из имени файла (берем дату окончания периода)
                    end_date_match = re.search(r'to_(\d{4}-\d{2}-\d{2})', result_file)
                    if not end_date_match:
                        print(f"Пропуск файла {result_file}: некорректное имя")
                        continue
                    
                    file_date = end_date_match.group(1)
                    
                    # Загружаем данные из файла results
                    df_results = pd.read_excel(
                        file_path,
                        usecols=['Symbol', 'Price (USD)', 'Market Cap']
                    )
                    
                    print(f"Загружено {len(df_results)} записей")
                    
                    # Обрабатываем каждую категорию
                    for category in categories:
                        # Получаем список токенов для текущей категории
                        category_tokens = set(self.categories_df[
                            self.categories_df['Category'] == category
                        ]['Symbol'].tolist())
                        
                        # Фильтруем данные только для токенов этой категории
                        category_data = df_results[
                            df_results['Symbol'].isin(category_tokens)
                        ]
                        
                        if not category_data.empty:
                            # Рассчитываем средние значения для категории
                            avg_price = category_data['Price (USD)'].mean()
                            avg_market_cap = category_data['Market Cap'].mean()
                            token_count = len(category_data)
                            
                            all_results.append({
                                'Category': category,
                                'Date': file_date,
                                'Price': avg_price,
                                'MarketCap': avg_market_cap,
                                'TokenCount': token_count,
                                'TotalTokens': len(category_tokens)
                            })
                            
                            print(f"Категория {category}: {token_count} токенов из {len(category_tokens)}")
                        else:
                            print(f"Нет данных для категории {category}")

                except Exception as e:
                    print(f"Ошибка при обработке файла {result_file}: {e}")
                    logging.error(f"Ошибка при обработке файла {result_file}: {e}")
                    continue

            # Создаем DataFrame из результатов
            results_df = pd.DataFrame(all_results)
            
            if results_df.empty:
                logging.warning("Нет данных после обработки")
                return pd.DataFrame()

            # Сортируем результаты
            results_df['Date'] = pd.to_datetime(results_df['Date'])
            results_df = results_df.sort_values(['Date', 'Category'])
            
            print(f"\nИтоги обработки:")
            print(f"- Обработано файлов: {len(result_files)}")
            print(f"- Категорий: {len(results_df['Category'].unique())}")
            print(f"- Всего записей: {len(results_df)}")
            print(f"- Диапазон дат: с {results_df['Date'].min()} по {results_df['Date'].max()}")

            return results_df

        except Exception as e:
            logging.error(f"Ошибка при обработке данных категорий: {e}")
            print(f"Ошибка при обработке данных категорий: {e}")
            return pd.DataFrame()

    def save_results(self, df: pd.DataFrame, token_symbol: str):
        """Сохранение результатов анализа"""
        try:
            if df.empty:
                logging.error("Нет данных для сохранения результатов")
                return None

            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            filename = os.path.join(self.base_dir, f'category_analysis_{token_symbol}_{timestamp}.xlsx')

            with pd.ExcelWriter(filename) as writer:
                # Основные данные
                df.to_excel(writer, sheet_name='Category Analysis', index=False)

                # Статистика
                stats_df = df.groupby('Category').agg({
                    'TokenCount': 'mean',
                    'TotalTokens': 'first',
                    'Price': ['mean', 'min', 'max'],
                    'MarketCap': ['mean', 'min', 'max']
                }).round(2)

                stats_df.to_excel(writer, sheet_name='Statistics')

            if os.path.exists(filename):
                file_size = os.path.getsize(filename)
                logging.info(f"Результаты анализа сохранены в {filename} (размер: {file_size} байт)")
                return filename
            else:
                logging.error("Не удалось создать файл результатов")
                return None

        except Exception as e:
            logging.error(f"Ошибка при сохранении результатов: {e}")
            return None


class Visualizer:
    def __init__(self):
        # Цвета для динамически выбираемых категорий
        self.dynamic_colors = {
            1: '#0066FF',  # Яркий синий
            2: '#00CC00',  # Яркий зеленый
            3: '#FFD700',  # Золотой
            4: '#FF1493',  # Ярко-розовый
            5: '#00FFFF',  # Циан
            6: '#FF4500',  # Оранжево-красный
            7: '#9400D3',  # Фиолетовый
            8: '#32CD32',  # Лайм
            9: '#FF69B4',  # Розовый
            10: '#4169E1'  # Королевский синий
        }

    def create_combined_plot(self, categories_df: pd.DataFrame, token_df: pd.DataFrame, token_symbol: str):
        """Creating a combined plot"""
        fig = go.Figure()

        # Normalize dates and ensure they are datetime
        token_df['date'] = pd.to_datetime(token_df['date'])
        categories_df['Date'] = pd.to_datetime(categories_df['Date'])

        # Ensure we only use dates that exist in both datasets
        common_dates = set(token_df['date'].dt.strftime('%Y-%m-%d')).intersection(
            set(categories_df['Date'].dt.strftime('%Y-%m-%d'))
        )
        
        if not common_dates:
            print("Error: No common dates between token and categories data")
            return None

        # Filter data to only include common dates
        token_df = token_df[token_df['date'].dt.strftime('%Y-%m-%d').isin(common_dates)].copy()
        categories_df = categories_df[categories_df['Date'].dt.strftime('%Y-%m-%d').isin(common_dates)].copy()

        # Sort both dataframes by date
        token_df = token_df.sort_values('date')
        categories_df = categories_df.sort_values('Date')

        # Get base price for normalization
        token_base_price = token_df['price'].iloc[0]
        print(f"\nBase price for {token_symbol}: ${token_base_price:.4f}")

        # Normalize token prices (percentage change from initial price)
        token_df['normalized_price'] = ((token_df['price'] - token_base_price) / token_base_price) * 100

        # Add token line
        token_change = token_df['normalized_price'].iloc[-1]
        
        fig.add_trace(go.Scatter(
            x=token_df['date'],
            y=token_df['normalized_price'],
            name=f"{token_symbol}",
            mode='lines+markers',
            line=dict(color='red', width=3),
            marker=dict(size=8),
            visible=True,
            hovertemplate=(
                f"<b>{token_symbol}</b><br>" +
                "Date: %{x}<br>" +
                "Change: %{y:.2f}%<br>" +
                "Price: ${:,.4f}<br>".format(token_df['price'].iloc[-1]) +
                "<extra></extra>"
            )
        ))

        # Process categories
        categories = sorted(categories_df['Category'].unique())
        print(f"\nProcessing {len(categories)} categories...")

        for idx, category in enumerate(categories):
            category_data = categories_df[categories_df['Category'] == category].copy()
            
            if len(category_data) < 2:  # Skip categories with insufficient data
                print(f"Skipping category {category}: insufficient data")
                continue

            # Ensure category data is properly sorted and aligned with token dates
            category_data = category_data.sort_values('Date')
            
            # Base price for category
            category_base_price = category_data['Price'].iloc[0]
            
            # Normalize category prices
            category_data['normalized_price'] = ((category_data['Price'] - category_base_price) / category_base_price) * 100
            
            # Calculate category price change
            category_change = category_data['normalized_price'].iloc[-1]
            
            color_idx = (idx % 10) + 1
            
            # Add category line
            fig.add_trace(go.Scatter(
                x=category_data['Date'],
                y=category_data['normalized_price'],
                name=f"{category}",
                mode='lines+markers',
                line=dict(
                    color=self.dynamic_colors[color_idx],
                    width=2
                ),
                marker=dict(
                    size=6,
                    color=self.dynamic_colors[color_idx]
                ),
                visible='legendonly',  # Hidden by default
                hovertemplate=(
                    f"<b>{category}</b><br>" +
                    "Date: %{x}<br>" +
                    "Change: %{y:.2f}%<br>" +
                    "Tokens: {:,d}<br>".format(category_data['TokenCount'].iloc[-1]) +
                    "<extra></extra>"
                )
            ))
            
            print(f"Category {category}: change {category_change:.2f}%")

        # Configure layout
        fig.update_layout(
            title=dict(
                x=0.5,
                y=0.95
            ),
            annotations=[dict(
                x=0.5,
                y=1.12,
                xref="paper",
                yref="paper",
                text=f"{token_symbol}: {token_change:.2f}%",
                showarrow=False,
                font=dict(
                    family="Arial",
                    size=14,
                    color="black"
                ),
                bgcolor="rgba(255, 255, 0, 0.2)",
                bordercolor="rgba(255, 255, 0, 0.5)",
                borderwidth=2,
                borderpad=8,
                align='center'
            )],
            yaxis=dict(
                title="Price Change (%)",
                showgrid=True,
                gridcolor='lightgray',
                zeroline=True,
                zerolinecolor='black',
                zerolinewidth=1
            ),
            xaxis=dict(
                title="Date",
                type='date',
                tickformat='%Y-%m-%d',
                showgrid=True,
                gridcolor='lightgray'
            ),
            showlegend=True,
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.02,
                bgcolor="rgba(255, 255, 255, 0.8)",
                bordercolor="lightgray",
                borderwidth=1
            ),
            hovermode='x unified',
            plot_bgcolor='white',
            margin=dict(t=100, r=200)  # Increased right margin for legend
        )

        return fig

    def save_plot(self, fig, token_symbol: str):
        """Save plot to HTML file"""
        try:
            # Updated save path
            save_path = r"C:\Users\Main\Pitonio\crypto_etf"
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            filename = os.path.join(save_path, f'analysis_{token_symbol}_{timestamp}.html')

            # Plot configuration
            config = {
                'displayModeBar': True,
                'scrollZoom': True,
                'displaylogo': False,
                'modeBarButtonsToAdd': ['drawline', 'eraseshape']
            }

            # Get base HTML
            html_content = fig.to_html(
                config=config,
                include_plotlyjs=True,
                full_html=True,
                include_mathjax=False
            )

            # JavaScript for dynamic updates
            js_code = """
            <script>
                var graphDiv = document.getElementById('graph');

                function updateTopLegend() {
                    var traces = graphDiv.data;
                    var tokenTrace = traces[0];  // First plot is always the token
                    var tokenChange = parseFloat(tokenTrace.hovertemplate.split('Change: ')[1]);

                    // Start with token
                    var legendParts = [`${tokenTrace.name}: ${tokenChange.toFixed(2)}%`];

                    // Collect information about visible categories
                    var visibleCategories = [];
                    for(var i = 1; i < traces.length; i++) {
                        if(traces[i].visible === true) {
                            var categoryChange = parseFloat(traces[i].hovertemplate.split('Change: ')[1]);
                            visibleCategories.push(`${traces[i].name}: ${categoryChange.toFixed(2)}%`);
                        }
                    }

                    // Add categories if any
                    if(visibleCategories.length > 0) {
                        legendParts = legendParts.concat(visibleCategories);
                    }

                    // Join all parts with proper formatting
                    var legendText = legendParts.join('  |  ');

                    // Update annotation
                    Plotly.relayout(graphDiv, {
                        'annotations[0].text': legendText,
                        'annotations[0].bgcolor': 'rgba(255, 255, 0, 0.2)',
                        'annotations[0].bordercolor': 'rgba(255, 255, 0, 0.5)',
                        'annotations[0].borderwidth': 2,
                        'annotations[0].borderpad': 8,
                        'annotations[0].font.size': 14,
                        'annotations[0].width': Math.min(1000, 200 + legendParts.length * 150)
                    });
                }

                // Event handlers for updates on interaction
                graphDiv.on('plotly_restyle', updateTopLegend);
                graphDiv.on('plotly_legendclick', function(data) {
                    setTimeout(updateTopLegend, 100);
                    return false;
                });

                // Handler for crosshair and updates on hover
                graphDiv.on('plotly_hover', function(data) {
                    updateTopLegend();
                });

                // Initialize on load
                document.addEventListener('DOMContentLoaded', updateTopLegend);
            </script>
            """

            # Add JavaScript to HTML
            html_content = html_content.replace('</body>', f'{js_code}</body>')

            # Save file
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(html_content)

            # Check save success
            if os.path.exists(filename):
                file_size = os.path.getsize(filename)
                logging.info(f"Plot successfully saved to {filename} (size: {file_size} bytes)")
                return filename
            else:
                logging.error(f"Failed to save file {filename}")
                return None

        except Exception as e:
            logging.error(f"Error saving plot: {e}")
            return None


def save_token_data(token_df: pd.DataFrame, token_symbol: str) -> str:
    """Сохранение данных токена в Excel"""
    try:
        # Проверяем наличие данных
        if token_df.empty:
            logging.error("Нет данных для сохранения")
            return None

        # Создаем директорию, если её нет
        save_dir = r"C:\Users\Main\Pitonio\crypto_etf"
        os.makedirs(save_dir, exist_ok=True)

        # Форматируем DataFrame
        formatted_df = token_df.copy()
        formatted_df['date'] = pd.to_datetime(formatted_df['date']).dt.strftime('%Y-%m-%d')
        formatted_df = formatted_df.rename(columns={
            'date': 'Date',
            'price': 'Price (USD)',
            'market_cap': 'Market Cap'
        })

        # Создаем имя файла с временной меткой
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        filename = os.path.join(save_dir, f'token_data_{token_symbol}_{timestamp}.xlsx')

        # Сохраняем в Excel с обработкой ошибок
        try:
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                formatted_df.to_excel(writer, index=False)

            if os.path.exists(filename):
                file_size = os.path.getsize(filename)
                logging.info(f"Данные токена сохранены в {filename} (размер: {file_size} байт)")
                return filename
            else:
                logging.error("Файл не был создан после сохранения")
                return None

        except PermissionError:
            logging.error(f"Ошибка доступа к файлу {filename}")
            return None

    except Exception as e:
        logging.error(f"Ошибка при сохранении данных токена: {e}")
        return None


def save_categories_data(categories_df: pd.DataFrame, token_symbol: str) -> str:
    """Сохранение данных категорий в Excel"""
    try:
        # Проверяем наличие данных
        if categories_df.empty:
            logging.error("Нет данных категорий для сохранения")
            return None

        # Создаем директорию, если её нет
        save_dir = r"C:\Users\Main\Pitonio\crypto_etf"
        os.makedirs(save_dir, exist_ok=True)

        # Форматируем DataFrame
        formatted_df = categories_df.copy()
        formatted_df['Date'] = pd.to_datetime(formatted_df['Date']).dt.strftime('%Y-%m-%d')

        # Создаем имя файла с временной меткой
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        filename = os.path.join(save_dir, f'categories_data_{token_symbol}_{timestamp}.xlsx')

        # Сохраняем в Excel с обработкой ошибок
        try:
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                formatted_df.to_excel(writer, index=False)

            if os.path.exists(filename):
                file_size = os.path.getsize(filename)
                logging.info(f"Данные категорий сохранены в {filename} (размер: {file_size} байт)")
                return filename
            else:
                logging.error("Файл не был создан после сохранения")
                return None

        except PermissionError:
            logging.error(f"Ошибка доступа к файлу {filename}")
            return None

    except Exception as e:
        logging.error(f"Ошибка при сохранении данных категорий: {e}")
        return None


async def main():
    """Основная функция программы"""
    api_handler = APIHandler()
    data_processor = DataProcessor()
    visualizer = Visualizer()

    try:
        # === Тестовый запрос ===
        print("\n=== Test Request ===")
        query = input("Enter token ID (numeric): ").strip()

        # Проверяем, что введено число
        if not query.isdigit():
            print("Error: Please enter a numeric token ID")
            return

        # Получаем информацию о токене
        token_info = await api_handler.get_token_info(query)
        if not token_info:
            print("Token not found")
            return

        print("\nToken Information:")
        print(f"ID: {token_info['id']}")
        print(f"Symbol: {token_info['symbol']}")
        print(f"Name: {token_info['name']}")

        # Спрашиваем пользователя о продолжении тестового запроса
        test_continue = input("\nПродолжить тестовый запрос? (y/n): ").lower()
        if test_continue != 'y':
            print("\n=== Пропуск тестового запроса ===")
            continue_analysis = 'y'
            # Переходим к получению исторических данных
            print("\n=== Получение исторических данных ===")
            all_historical_data = []
        else:
            # Запрашиваем даты для тестового запроса
            print("\nВведите даты для тестового запроса (формат: YYYY-MM-DD)")
            while True:
                try:
                    start_date = input("Дата начала: ").strip()
                    end_date = input("Дата окончания: ").strip()

                    # Проверяем формат дат
                    start = datetime.strptime(start_date, '%Y-%m-%d').date()
                    end = datetime.strptime(end_date, '%Y-%m-%d').date()

                    # Проверяем корректность периода
                    if end < start:
                        print("Ошибка: Дата окончания не может быть раньше даты начала")
                        continue

                    break
                except ValueError:
                    print("Неверный формат даты. Используйте формат YYYY-MM-DD")
                    continue

            # Получаем тестовые данные
            test_data = await api_handler.get_historical_data(
                token_info['id'],
                start_date,
                end_date
            )

            if test_data:
                print(f"\nТестовые данные за период {start_date} - {end_date}:")
                for data in test_data:
                    print(f"Дата: {data['date']}")
                    print(f"Цена закрытия: ${data['price']:.4f}")
                    print(f"Капитализация: ${data['market_cap']:,.2f}")
            else:
                print("Не удалось получить тестовые данные")
                return

            # === Запрос на продолжение ===
            continue_analysis = input("\nПродолжить с полным анализом? (y/n): ").lower()
            if continue_analysis != 'y':
                return

        # === Получение исторических данных ===
        print("\n=== Получение исторических данных ===")
        all_historical_data = []

        print("\nПериоды анализа:")
        for start, end in ANALYSIS_DATES:
            print(f"- {start} to {end}")

        MAX_RETRIES = 10  # Максимальное количество попыток для каждого периода

        with tqdm(total=len(ANALYSIS_DATES), desc="Прогресс запросов") as pbar:
            for start_date, end_date in ANALYSIS_DATES:
                retry_count = 0
                period_data = None
                
                while retry_count < MAX_RETRIES:
                    try:
                        await asyncio.sleep(1)  # Небольшая задержка между запросами
                        period_data = await api_handler.get_historical_data(
                            token_info['id'],
                            start_date,
                            end_date
                        )
                        if period_data:
                            break
                        retry_count += 1
                        if retry_count < MAX_RETRIES:
                            print(f"\nПопытка {retry_count + 1} из {MAX_RETRIES} для периода {start_date} - {end_date}")
                    except Exception as e:
                        print(f"\nОшибка при получении данных: {e}")
                        retry_count += 1
                        if retry_count < MAX_RETRIES:
                            print(f"Повторная попытка {retry_count + 1} из {MAX_RETRIES}")
                
                if not period_data and retry_count >= MAX_RETRIES:
                    print(f"\nНе удалось получить данные за период {start_date} - {end_date} после {MAX_RETRIES} попыток")
                    retry_decision = input("Повторить попытки для этого периода? (y/n): ").lower()
                    
                    while retry_decision == 'y':
                        retry_count = 0
                        while retry_count < MAX_RETRIES:
                            try:
                                await asyncio.sleep(1)
                                period_data = await api_handler.get_historical_data(
                                    token_info['id'],
                                    start_date,
                                    end_date
                                )
                                if period_data:
                                    break
                                retry_count += 1
                                if retry_count < MAX_RETRIES:
                                    print(f"\nДополнительная попытка {retry_count + 1} из {MAX_RETRIES}")
                            except Exception as e:
                                print(f"\nОшибка при получении данных: {e}")
                                retry_count += 1
                        
                        if not period_data:
                            retry_decision = input("Повторить попытки снова? (y/n): ").lower()
                        else:
                            break
                
                if period_data:
                    all_historical_data.extend(period_data)
                    print(f"\nУспешно получены данные за период {start_date} - {end_date}")
                else:
                    print(f"\nПропускаем период {start_date} - {end_date}")
                
                pbar.update(1)

        if not all_historical_data:
            print("Не удалось получить исторические данные")
            return

        # Создаем DataFrame с историческими данными токена
        token_df = pd.DataFrame(all_historical_data)

        # Проверяем данные токена
        if token_df.empty:
            print("Ошибка: Данные токена пусты")
            return

        print(f"\nПолучено записей для токена: {len(token_df)}")

        # === Обработка категорий ===
        print("\n=== Обработка данных категорий ===")
        categories_df = data_processor.process_data()

        # Проверяем данные категорий
        if categories_df.empty:
            print("Ошибка: Нет данных категорий для анализа")
            return

        print(f"Получено записей для категорий: {len(categories_df)}")

        # === Сохранение данных ===
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')

        # Сохраняем данные токена
        token_filename = save_token_data(token_df, token_info['symbol'])
        if not token_filename:
            print("Ошибка при сохранении данных токена")
            return
        print(f"\nДанные токена сохранены в {token_filename}")

        # Сохраняем результаты анализа категорий
        analysis_filename = data_processor.save_results(categories_df, token_info['symbol'])
        if analysis_filename:
            print(f"Результаты анализа категорий сохранены в {analysis_filename}")

        # === Создание визуализации ===
        print("\nСоздание визуализации...")

        # Проверяем данные перед визуализацией
        print("\nПроверка данных для визуализации:")
        print(f"Токен {token_info['symbol']}:")
        print(f"- Временной период: с {token_df['date'].min()} по {token_df['date'].max()}")
        print(f"- Диапазон цен: ${token_df['price'].min():.4f} - ${token_df['price'].max():.4f}")
        print("\nКатегории:")
        print(f"- Количество категорий: {len(categories_df['Category'].unique())}")
        print(f"- Временной период: с {categories_df['Date'].min()} по {categories_df['Date'].max()}")

        # Создаем и сохраняем график
        fig = visualizer.create_combined_plot(
            categories_df=categories_df,
            token_df=token_df,
            token_symbol=token_info['symbol']
        )

        # Сохраняем график
        html_filename = visualizer.save_plot(fig, token_info['symbol'])

        if html_filename and os.path.exists(html_filename):
            print(f"\nГрафик сохранен в {html_filename}")
            print(f"Размер файла: {os.path.getsize(html_filename):,} байт")

            # Проверяем содержимое файла
            with open(html_filename, 'r', encoding='utf-8') as f:
                content = f.read()
                if len(content) < 100:  # Минимальный размер валидного HTML
                    print("Предупреждение: Файл графика может быть поврежден")
        else:
            print("Ошибка: Не удалось сохранить график")

        # === Итоговый отчет ===
        print("\nАнализ завершен успешно!")
        print("Созданные файлы:")
        print(f"1. Данные токена: {token_filename}")
        print(f"2. Анализ категорий: {analysis_filename}")
        print(f"3. Интерактивный график: {html_filename}")

    except Exception as e:
        logging.error(f"Ошибка в основной программе: {e}")
        print(f"\nПроизошла ошибка: {e}")
        print("Проверьте лог-файл для деталей")

    finally:
        await api_handler.close()


if __name__ == "__main__":
    if os.name == 'nt':  # для Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
