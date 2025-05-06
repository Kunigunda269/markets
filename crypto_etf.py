import asyncio
import aiohttp
import pandas as pd
import plotly.graph_objects as go
import logging
from datetime import datetime, timedelta
from tqdm import tqdm
import os
import ssl
import certifi
import re
import json
import boto3
from botocore.exceptions import ClientError
from botocore.client import Config
from typing import Tuple, List, Dict, Any, Optional

# Константы для S3
S3_URL = 'https://s'
S3_BUCKET_NAME = '123'
S3_ACCESS_KEY = '123'
S3_SECRET_ACCESS_KEY = '123'

# Функция загрузки конфигурации
def load_config():
    """Загрузка конфигурации из файла config.json"""
    default_config = {
        "max_requests_per_minute": 30,
        "batch_size": 50,
        "input_file": r"C:\Users\Main\Pitonio\crypto_etf\category_downloader_123.xlsx",
        "output_folder": r"C:\Users\Main\Pitonio\crypto_etf\results",
        "save_path": r"C:\Users\Main\Pitonio\crypto_etf",
        "log_file": "crypto_api.log",
        "log_level": "INFO",
        "api_base_url": "https://pro-api.coinmarketcap.com/v2"
    }
    
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                user_config = json.load(f)
                default_config.update(user_config)
                logging.info(f"Конфигурация загружена из {config_path}")
        except Exception as e:
            logging.error(f"Ошибка при загрузке конфигурации: {e}")
    else:
        # Создаем файл конфигурации с дефолтными настройками
        try:
            with open(config_path, 'w') as f:
                json.dump(default_config, f, indent=4)
            logging.info(f"Создан файл конфигурации по умолчанию {config_path}")
        except Exception as e:
            logging.error(f"Не удалось создать файл конфигурации: {e}")
    
    return default_config

# Конфигурация логирования
logging.basicConfig(
    filename='crypto_api.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Загружаем конфигурацию
CONFIG = load_config()

# Применяем настройки логирования из конфигурации
logging.basicConfig(
    filename=CONFIG["log_file"],
    level=getattr(logging, CONFIG["log_level"]),
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Создаем директории если они не существуют
os.makedirs(CONFIG["output_folder"], exist_ok=True)
os.makedirs(CONFIG["save_path"], exist_ok=True)

# Конфигурация API
API_KEY = "123"
BASE_URL = CONFIG.get("api_base_url", "https://pro-api.coinmarketcap.com/v2")
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
    ("2025-03-15", "2025-03-16"),
    ("2025-03-22", "2025-03-23"),
    ("2025-03-29", "2025-03-30"),
    ("2025-04-05", "2025-04-06")
]

def load_analysis_dates_from_config():
    """Загрузка дат анализа из конфигурационного файла"""
    config_file = os.path.join(CONFIG["save_path"], "analysis_dates.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                import json
                dates = json.load(f)
                logging.info(f"Загружено {len(dates)} периодов из конфигурационного файла")
                return dates
        except Exception as e:
            logging.error(f"Ошибка при загрузке дат анализа: {e}")
    return ANALYSIS_DATES

# Пытаемся загрузить даты из конфига, если не получается - используем предустановленные
ANALYSIS_DATES = load_analysis_dates_from_config()

class APIHandler:
    def __init__(self):
        self.session = None
        self.last_request_time = 0
        self.rate_limit = CONFIG["max_requests_per_minute"]
        self.min_request_interval = 60.0 / self.rate_limit

    async def _get_session(self):
        """Создание или получение существующей сессии"""
        if self.session is None:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self.session = aiohttp.ClientSession(connector=connector)
        return self.session

    async def _rate_limit_wait(self):
        """Управление ограничением скорости запросов"""
        current_time = datetime.now().timestamp()
        elapsed = current_time - self.last_request_time
        
        if elapsed < self.min_request_interval:
            wait_time = self.min_request_interval - elapsed
            logging.debug(f"Rate limit: ожидание {wait_time:.2f} секунд")
            await asyncio.sleep(wait_time)
            
        self.last_request_time = datetime.now().timestamp()

    async def get_token_info(self, query: str):
        """Get token information by ID or ticker"""
        session = await self._get_session()

        try:
            await self._rate_limit_wait()
            
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
            await self._rate_limit_wait()
            
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
        self.category_file = os.path.join(self.base_dir, "category_downloader_123.xlsx")

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
                
            # Также проверяем директорию results, если она существует
            results_folder = os.path.join(self.base_dir, "results")
            if os.path.exists(results_folder) and os.path.isdir(results_folder):
                for file in os.listdir(results_folder):
                    if re.match(pattern, file):
                        full_path = os.path.join(results_folder, file)
                        files.append(full_path)

            # Сортируем файлы по дате
            files.sort(key=lambda x: re.findall(r'\d{4}-\d{2}-\d{2}', x)[0])

            if not files:
                logging.warning("Файлы result не найдены")
                print("Файлы result не найдены ни в основной директории, ни в папке results")
            else:
                logging.info(f"Найдено {len(files)} файлов result")
                print(f"Найдено {len(files)} файлов result:")
                for file in files[:5]:  # Выводим первые 5 файлов для проверки
                    print(f"  - {os.path.basename(file)}")
                if len(files) > 5:
                    print(f"  ... и еще {len(files) - 5} файлов")

            return files

        except Exception as e:
            logging.error(f"Ошибка при поиске result файлов: {e}")
            print(f"Ошибка при поиске result файлов: {e}")
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

            logging.info(
                f"Загружено {len(self.categories_df)} токенов из {len(self.categories_df['Category'].unique())} категорий")

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

            async def _fetch_token_data(session, token, time_start, time_end, processed_tokens):
                """Получение данных для одного токена"""
                try:
                    endpoint = f"{BASE_URL}/cryptocurrency/quotes/historical"
                    params = {
                        "id": str(token["Id"]),
                        "time_start": f"{time_start}T00:00:00Z",
                        "time_end": f"{time_end}T23:59:59Z",
                        "interval": "1d",
                        "convert": "USD"
                    }

                    # Ожидаем лимит запросов
                    await asyncio.sleep(60 / CONFIG["max_requests_per_minute"])
                    
                    async with session.get(endpoint, headers=HEADERS, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get("data", {}).get("quotes"):
                                quotes = data["data"]["quotes"]
                                results = []
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
                                return results
                            else:
                                logging.warning(f"Нет данных для токена {token['Symbol']}")
                        else:
                            logging.error(f"Ошибка API {response.status} для токена {token['Symbol']}")
                except Exception as e:
                    logging.error(f"Ошибка при получении данных для токена {token['Symbol']}: {e}")
                
                return []

            async def fetch_batch_data(session, batch, time_start, time_end, processed_tokens):
                """Получение данных для пакета токенов"""
                results = []
                tasks = []

                for token in batch:
                    # Пропускаем уже обработанные токены
                    if token["Id"] in processed_tokens:
                        continue
                    
                    task = _fetch_token_data(session, token, time_start, time_end, processed_tokens)
                    tasks.append(task)
                
                # Ждем выполнения всех задач
                if tasks:
                    results_list = await asyncio.gather(*tasks)
                    for token_results in results_list:
                        if token_results:
                            results.extend(token_results)

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

    def process_data(self, token_df: pd.DataFrame):
        try:
            # Проверяем загрузку категорий
            if self.categories_df is None or self.categories_df.empty:
                logging.error("DataFrame категорий пуст или не инициализирован")
                print("DataFrame категорий пуст или не инициализирован")
                return pd.DataFrame()

            # Получаем даты из данных токена
            token_dates = pd.to_datetime(token_df['date']).dt.date.unique()
            print(f"Даты из данных токена: {[d.strftime('%Y-%m-%d') for d in token_dates]}")

            # Используем существующий механизм поиска файлов results
            result_files = self._get_result_files()
            
            # Если не нашли файлы через основной механизм, проверяем папку results напрямую
            if not result_files:
                results_folder = os.path.join(self.base_dir, "results")
                if os.path.exists(results_folder):
                    result_files = [
                        os.path.join(results_folder, f) for f in os.listdir(results_folder)
                        if f.startswith('result_') and f.endswith('.xlsx')
                    ]
                    result_files.sort()
                    print(f"Найдено {len(result_files)} файлов в папке results")

            if not result_files:
                logging.error("Файлы результатов не найдены")
                print("Файлы результатов не найдены ни в одной из директорий")
                return pd.DataFrame()

            print(f"Всего найдено файлов результатов: {len(result_files)}")

            all_results = []
            categories = self.categories_df['Category'].unique()
            processed_files = 0

            # Функция очистки численных значений (не меняется)
            def clean_numeric_value(value):
                try:
                    if pd.isna(value):
                        return None
                    if isinstance(value, (int, float)):
                        return float(value)
                    if isinstance(value, str):
                        # Удаляем суффиксы и пробелы
                        value = value.strip().upper()
                        multiplier = 1
                        
                        # Определяем множитель (B, M, K)
                        if 'B' in value:
                            multiplier = 1e9
                            value = value.replace('B', '')
                        elif 'M' in value:
                            multiplier = 1e6
                            value = value.replace('M', '')
                        elif 'K' in value:
                            multiplier = 1e3
                            value = value.replace('K', '')

                        # Удаляем запятые
                        value = value.replace(',', '')
                        
                        # Обрабатываем случай множественных точек
                        if value.count('.') > 1:
                            parts = value.split('.')
                            value = ''.join(parts[:-1]) + '.' + parts[-1]

                        try:
                            return float(value) * multiplier
                        except ValueError:
                            return None
                    return None
                except Exception:
                    return None

            for result_file in result_files:
                try:
                    print(f"\nОбработка файла: {os.path.basename(result_file)}")

                    # Извлекаем дату из имени файла
                    end_date_match = re.search(r'to_(\d{4}-\d{2}-\d{2})', os.path.basename(result_file))
                    if not end_date_match:
                        print(f"Пропуск файла {os.path.basename(result_file)}: не удалось извлечь дату")
                        continue

                    file_date = datetime.strptime(end_date_match.group(1), '%Y-%m-%d').date()
                    print(f"Извлечена дата: {file_date}")

                    # Загружаем данные из файла
                    try:
                        df_results = pd.read_excel(result_file)
                        processed_files += 1
                        print(f"Файл загружен успешно")
                        print(f"Столбцы файла: {df_results.columns.tolist()}")
                        print(f"Количество строк до обработки: {len(df_results)}")

                        # Унификация названий столбцов - проверяем различные варианты
                        column_mapping = {
                            'Market Cap (USD)': 'Market Cap',
                            'Market_Cap': 'Market Cap',
                            'MarketCap': 'Market Cap',
                            'market_cap': 'Market Cap',
                            'Price (USD)': 'Price',
                            'price': 'Price',
                            'Price_USD': 'Price',
                            'Symbol': 'Symbol',
                            'symbol': 'Symbol'
                        }
                        
                        # Переименовываем столбцы если они существуют
                        for old_col, new_col in column_mapping.items():
                            if old_col in df_results.columns and old_col != new_col:
                                df_results = df_results.rename(columns={old_col: new_col})
                                print(f"Переименован столбец: {old_col} -> {new_col}")

                        # Проверка наличия нужных столбцов
                        required_columns = ['Symbol', 'Market Cap', 'Price']
                        missing_columns = [col for col in required_columns if col not in df_results.columns]
                        
                        if missing_columns:
                            print(f"Пропуск файла {os.path.basename(result_file)}: отсутствуют необходимые столбцы: {missing_columns}")
                            print(f"Имеющиеся столбцы: {df_results.columns.tolist()}")
                            
                            # Попытка автоматического определения столбцов
                            price_columns = [col for col in df_results.columns if 'price' in col.lower() or 'стоимость' in col.lower()]
                            cap_columns = [col for col in df_results.columns if 'cap' in col.lower() or 'капитал' in col.lower()]
                            symbol_columns = [col for col in df_results.columns if 'symbol' in col.lower() or 'тикер' in col.lower()]
                            
                            if 'Price' in missing_columns and price_columns:
                                df_results = df_results.rename(columns={price_columns[0]: 'Price'})
                                print(f"Автоопределение: столбец {price_columns[0]} -> Price")
                                missing_columns.remove('Price')
                                
                            if 'Market Cap' in missing_columns and cap_columns:
                                df_results = df_results.rename(columns={cap_columns[0]: 'Market Cap'})
                                print(f"Автоопределение: столбец {cap_columns[0]} -> Market Cap")
                                missing_columns.remove('Market Cap')
                                
                            if 'Symbol' in missing_columns and symbol_columns:
                                df_results = df_results.rename(columns={symbol_columns[0]: 'Symbol'})
                                print(f"Автоопределение: столбец {symbol_columns[0]} -> Symbol")
                                missing_columns.remove('Symbol')
                                
                            if missing_columns:
                                print(f"После автоопределения все еще отсутствуют столбцы: {missing_columns}")
                                continue
                            else:
                                print("Все необходимые столбцы определены автоматически!")
                                
                        # Очистка данных
                        try:
                            # Преобразуем столбец Price, учитывая разные варианты названий
                            price_column = 'Price'
                            if price_column not in df_results.columns and 'Price (USD)' in df_results.columns:
                                price_column = 'Price (USD)'
                                
                            df_results['Price'] = df_results[price_column].apply(clean_numeric_value)
                            
                            # Преобразуем столбец Market Cap, учитывая разные варианты названий
                            cap_column = 'Market Cap'
                            if cap_column not in df_results.columns:
                                potential_cap_columns = [col for col in df_results.columns if 'cap' in col.lower()]
                                if potential_cap_columns:
                                    cap_column = potential_cap_columns[0]
                                    print(f"Используем столбец {cap_column} для Market Cap")
                            
                            df_results['Market Cap'] = df_results[cap_column].apply(clean_numeric_value)
                            
                            # После очистки проверяем еще раз
                            if df_results['Price'].isna().all() or df_results['Market Cap'].isna().all():
                                print(f"Ошибка: после очистки все значения Price или Market Cap равны NaN")
                                print(f"Примеры исходных значений Price: {df_results[price_column].head()}")
                                print(f"Примеры исходных значений Market Cap: {df_results[cap_column].head()}")
                                continue
                        except Exception as e:
                            print(f"Ошибка при очистке данных: {e}")
                            continue

                        # Удаляем только строки с отсутствующими или нулевыми данными
                        df_results = df_results.dropna(subset=['Market Cap', 'Price'])
                        df_results = df_results[
                            (df_results['Price'] > 0) & 
                            (df_results['Market Cap'] > 0)
                        ]

                        # Удаляем дубликаты
                        df_results = df_results.drop_duplicates(subset=['Symbol'], keep='last')

                        print(f"Количество строк после базовой очистки: {len(df_results)}")

                        # Очистка выбросов
                        if len(df_results) > 10:  # Выполняем только если достаточно данных
                            price_mean = df_results['Price'].mean()
                            price_std = df_results['Price'].std()
                            market_cap_mean = df_results['Market Cap'].mean()
                            market_cap_std = df_results['Market Cap'].std()

                            df_results = df_results[
                                (df_results['Price'] <= price_mean + 3 * price_std) &
                                (df_results['Price'] >= price_mean - 3 * price_std) &
                                (df_results['Market Cap'] <= market_cap_mean + 3 * market_cap_std) &
                                (df_results['Market Cap'] >= market_cap_mean - 3 * market_cap_std)
                            ]

                            print(f"Количество строк после очистки выбросов: {len(df_results)}")

                    except Exception as e:
                        print(f"Ошибка при загрузке файла {os.path.basename(result_file)}: {e}")
                        logging.error(f"Ошибка при загрузке файла {os.path.basename(result_file)}: {e}")
                        continue

                    # Обрабатываем каждую категорию
                    category_count = 0
                    for category in categories:
                        # Получаем список токенов для текущей категории
                        category_tokens = set(self.categories_df[
                            self.categories_df['Category'] == category
                        ]['Symbol'].tolist())

                        # Фильтруем данные для токенов этой категории
                        category_data = df_results[
                            df_results['Symbol'].isin(category_tokens)
                        ].copy()

                        if not category_data.empty:
                            category_count += 1
                            # Рассчитываем взвешенную по капитализации среднюю цену
                            total_market_cap = category_data['Market Cap'].sum()
                            weighted_price = (
                                (category_data['Price'] * category_data['Market Cap']).sum() 
                                / total_market_cap
                            )

                            all_results.append({
                                'Category': category,
                                'Date': file_date,
                                'Price': weighted_price,
                                'MarketCap': total_market_cap,
                                'TokenCount': len(category_data),
                                'TotalTokens': len(category_tokens)
                            })
                    
                    print(f"Обработано категорий в файле: {category_count}")

                except Exception as e:
                    print(f"Ошибка при обработке файла {os.path.basename(result_file)}: {e}")
                    logging.error(f"Ошибка при обработке файла {os.path.basename(result_file)}: {e}")
                    continue

            print(f"\nВсего обработано файлов: {processed_files} из {len(result_files)}")
            
            # Создаем DataFrame из результатов
            results_df = pd.DataFrame(all_results)

            if results_df.empty:
                logging.warning("Нет данных после обработки")
                print("Нет данных после обработки файлов")
                return pd.DataFrame()

            # Сортируем результаты
            results_df['Date'] = pd.to_datetime(results_df['Date'])
            results_df = results_df.sort_values(['Date', 'Category'])

            print(f"Получено {len(results_df)} записей для категорий")
            print(f"Уникальные даты в результатах: {sorted(results_df['Date'].dt.date.unique())}")
            
            # Оставляем только те даты, которые есть в токене
            filtered_df = results_df[results_df['Date'].dt.date.isin(token_dates)]
            
            if len(filtered_df) < len(results_df):
                print(f"Отфильтровано записей: оставлено {len(filtered_df)} из {len(results_df)}")
                print(f"Отфильтрованные даты: {sorted(filtered_df['Date'].dt.date.unique())}")
            
            return filtered_df

        except Exception as e:
            logging.error(f"Ошибка при обработке данных категорий: {e}")
            print(f"Общая ошибка при обработке данных категорий: {e}")
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
        
        # Параметры визуализации
        self.chart_params = {
            "token_line_width": 3,
            "token_marker_size": 8,
            "category_line_width": 2,
            "category_marker_size": 6,
            "token_color": "red",
            "legend_font_size": 14
        }

    def create_combined_plot(self, categories_df: pd.DataFrame, token_df: pd.DataFrame, token_symbol: str):
        """Creating a combined plot with synchronized dates"""
        fig = go.Figure()

        # Ensure dates are datetime
        token_df['date'] = pd.to_datetime(token_df['date'])
        categories_df['Date'] = pd.to_datetime(categories_df['Date'])

        # Sort both dataframes by date
        token_df = token_df.sort_values('date')
        categories_df = categories_df.sort_values('Date')

        # Debug info
        print("\nИнформация для визуализации:")
        print(f"Токен {token_symbol}:")
        print(f"- Диапазон дат: с {token_df['date'].min()} по {token_df['date'].max()}")
        print(f"- Количество дат: {len(token_df['date'].unique())}")
        
        print("\nКатегории:")
        print(f"- Диапазон дат: с {categories_df['Date'].min()} по {categories_df['Date'].max()}")
        print(f"- Количество дат: {len(categories_df['Date'].unique())}")
        print(f"- Количество категорий: {len(categories_df['Category'].unique())}")

        # Get base price for normalization
        token_base_price = token_df['price'].iloc[0]
        print(f"\nБазовая цена для {token_symbol}: ${token_base_price:.4f}")

        # Normalize token prices (percentage change from initial price)
        token_df['normalized_price'] = ((token_df['price'] - token_base_price) / token_base_price) * 100

        # Add token line
        token_change = token_df['normalized_price'].iloc[-1]

        # Проверка синхронизации дат
        token_dates = set(token_df['date'].dt.date)
        category_dates = set(categories_df['Date'].dt.date)
        common_dates = token_dates.intersection(category_dates)
        
        print(f"\nАнализ соответствия дат:")
        print(f"- Даты токена: {len(token_dates)}")
        print(f"- Даты категорий: {len(category_dates)}")
        print(f"- Общие даты: {len(common_dates)}")
        
        if len(common_dates) < min(len(token_dates), len(category_dates)):
            print("\nВнимание: несоответствие дат между токеном и категориями!")
            print("Это может привести к некорректному отображению графика.")
            
            # Фильтруем данные по общим датам для корректного отображения
            token_df = token_df[token_df['date'].dt.date.isin(common_dates)]
            categories_df = categories_df[categories_df['Date'].dt.date.isin(common_dates)]
            
            print(f"\nПосле фильтрации:")
            print(f"- Записей токена: {len(token_df)}")
            print(f"- Записей категорий: {len(categories_df)}")
            
            # Перерасчет нормализации после фильтрации
            if not token_df.empty:
                token_base_price = token_df['price'].iloc[0]
                token_df['normalized_price'] = ((token_df['price'] - token_base_price) / token_base_price) * 100
                token_change = token_df['normalized_price'].iloc[-1]
            else:
                print("Ошибка: после фильтрации не осталось данных токена")
                return fig

        # Добавляем линию токена
        self._add_token_trace(fig, token_df, token_symbol)

        # Обрабатываем категории
        self._add_category_traces(fig, categories_df, token_df)

        # Настраиваем макет
        self._configure_layout(fig, token_symbol, token_change)

        return fig
        
    def _add_token_trace(self, fig, token_df, token_symbol):
        """Добавление графика токена"""
        fig.add_trace(go.Scatter(
            x=token_df['date'],
            y=token_df['normalized_price'],
            name=f"{token_symbol}",
            mode='lines+markers',
            line=dict(color=self.chart_params["token_color"], 
                     width=self.chart_params["token_line_width"]),
            marker=dict(size=self.chart_params["token_marker_size"]),
            visible=True,
            hovertemplate=(
                    f"<b>{token_symbol}</b><br>" +
                    "Date: %{x}<br>" +
                    "Change: %{y:.2f}%<br>" +
                    "Price: ${:,.4f}<br>".format(token_df['price'].iloc[-1]) +
                    "<extra></extra>"
            )
        ))
        
    def _add_category_traces(self, fig, categories_df, token_df):
        """Добавление графиков по категориям"""
        categories = sorted(categories_df['Category'].unique())
        print(f"\nВизуализация {len(categories)} категорий...")
        print(f"Даты токена: {sorted(token_df['date'].dt.date.unique())}")
        print(f"Даты категорий: {sorted(categories_df['Date'].dt.date.unique())}")

        # Проверяем соответствие дат
        token_dates = set(token_df['date'].dt.date)
        category_dates = set(categories_df['Date'].dt.date)
        common_dates = token_dates.intersection(category_dates)
        
        if len(common_dates) < len(token_dates):
            missing_dates = token_dates - category_dates
            print(f"Внимание: {len(missing_dates)} дат токена отсутствуют в данных категорий:")
            for date in sorted(missing_dates):
                print(f"  - {date}")
        
        if len(common_dates) < len(category_dates):
            extra_dates = category_dates - token_dates
            print(f"Внимание: {len(extra_dates)} дат категорий отсутствуют в данных токена:")
            for date in sorted(extra_dates):
                print(f"  - {date}")

        for idx, category in enumerate(categories):
            category_data = categories_df[categories_df['Category'] == category].copy()

            if len(category_data) < 2:
                print(f"Пропуск категории {category}: недостаточно данных (записей: {len(category_data)})")
                continue

            # Обеспечиваем соответствие дат категорий датам токена
            category_data = category_data[category_data['Date'].dt.date.isin(token_df['date'].dt.date)]

            if len(category_data) < 2:
                print(f"Пропуск категории {category}: недостаточно выровненных данных (записей: {len(category_data)})")
                continue

            # Сортируем данные по дате для корректной визуализации
            category_data = category_data.sort_values('Date')
            
            # Базовая цена для категории
            category_base_price = category_data['Price'].iloc[0]

            # Нормализуем цены категории
            category_data['normalized_price'] = ((category_data['Price'] - category_base_price) / 
                                                category_base_price) * 100

            # Рассчитываем изменение цены категории
            category_change = category_data['normalized_price'].iloc[-1]

            color_idx = (idx % 10) + 1

            # Проверка соответствия дат (отладочная информация)
            category_date_str = category_data['Date'].dt.date.tolist()
            if len(category_date_str) > 0:
                print(f"Категория {category}: {len(category_date_str)} дат, изменение {category_change:.2f}%")
                if len(category_date_str) <= 10:  # Ограничиваем вывод для большого количества дат
                    print(f"  Даты: {sorted(category_date_str)}")

            fig.add_trace(go.Scatter(
                x=category_data['Date'],
                y=category_data['normalized_price'],
                name=f"{category}",
                mode='lines+markers',
                line=dict(
                    color=self.dynamic_colors[color_idx],
                    width=self.chart_params["category_line_width"]
                ),
                marker=dict(
                    size=self.chart_params["category_marker_size"],
                    color=self.dynamic_colors[color_idx]
                ),
                visible='legendonly',
                hovertemplate=(
                        f"<b>{category}</b><br>" +
                        "Date: %{x}<br>" +
                        "Change: %{y:.2f}%<br>" +
                        "Tokens: {:,d}<br>".format(category_data['TokenCount'].iloc[-1]) +
                        "<extra></extra>"
                )
            ))

    def _configure_layout(self, fig, token_symbol, token_change):
        """Настройка макета графика"""
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
                    size=self.chart_params["legend_font_size"],
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
                
                # Загружаем файл в S3
                try:
                    s3_uploader = S3Uploader()
                    s3_success, s3_message = s3_uploader.upload_file(filename)
                    
                    if s3_success:
                        logging.info(f"График успешно загружен в S3: {s3_message}")
                        print(f"График доступен по ссылке: {s3_message}")
                        # Возвращаем кортеж с локальным файлом и URL в S3
                        return {"local_file": filename, "s3_url": s3_message}
                    else:
                        logging.warning(f"Не удалось загрузить график в S3: {s3_message}")
                        print(f"График сохранен локально: {filename}")
                        return {"local_file": filename, "s3_url": None} 
                except Exception as e:
                    logging.error(f"Ошибка при загрузке в S3: {str(e)}")
                    print(f"График сохранен только локально: {filename}")
                    return {"local_file": filename, "s3_url": None}
            else:
                logging.error(f"Failed to save file {filename}")
                return {"local_file": None, "s3_url": None}

        except Exception as e:
            logging.error(f"Error saving plot: {e}")
            return {"local_file": None, "s3_url": None}


class S3Uploader:
    """Класс для загрузки HTML файлов в облачное хранилище S3"""

    def __init__(self):
        """Инициализация S3 клиента с учетными данными из констант"""
        # Настраиваем S3 клиент для Timeweb S3
        s3_config = Config(
            signature_version='s3',  # Используем старую версию подписи
            s3={'addressing_style': 'path'},  # Используем адресацию в стиле пути
            retries={'max_attempts': 3, 'mode': 'standard'}
        )

        try:
            self.s3_client = boto3.client(
                's3',
                endpoint_url=S3_URL,
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_ACCESS_KEY,
                config=s3_config
            )
            self.bucket_name = S3_BUCKET_NAME

            # Проверяем доступность bucket
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logging.info(f"Успешное подключение к bucket {self.bucket_name}")
            print(f"S3: Успешное подключение к хранилищу")
        except ClientError as e:
            logging.error(f"Ошибка доступа к bucket {self.bucket_name}: {str(e)}")
            print(f"S3: Ошибка подключения к хранилищу - {str(e)}")
            raise

    def upload_file(self, file_path: str, object_name: Optional[str] = None) -> Tuple[bool, str]:
        """
        Загрузка файла в S3 bucket.

        Args:
            file_path: Путь к файлу для загрузки
            object_name: Имя объекта S3. Если не указано, используется имя файла из file_path

        Returns:
            Tuple из (успех: bool, сообщение: str)
        """
        # Если имя объекта S3 не указано, используем имя файла из file_path
        if object_name is None:
            object_name = os.path.basename(file_path)

        try:
            logging.info(f"Загрузка {file_path} в {self.bucket_name}/{object_name}")
            print(f"S3: Загрузка файла {os.path.basename(file_path)}... ", end="", flush=True)

            # Определение типа контента на основе расширения файла
            content_type = None
            if file_path.lower().endswith('.html'):
                content_type = 'text/html'
            elif file_path.lower().endswith('.css'):
                content_type = 'text/css'
            elif file_path.lower().endswith('.js'):
                content_type = 'application/javascript'

            # Для небольших файлов используем put_object вместо upload_file
            if os.path.getsize(file_path) < 5 * 1024 * 1024:  # Меньше 5МБ
                with open(file_path, 'rb') as file_data:
                    extra_args = {}
                    if content_type:
                        extra_args['ContentType'] = content_type

                    self.s3_client.put_object(
                        Bucket=self.bucket_name,
                        Key=object_name,
                        Body=file_data,
                        **extra_args
                    )
            else:
                # Для больших файлов используем метод загрузки файлов
                extra_args = {}
                if content_type:
                    extra_args['ContentType'] = content_type

                self.s3_client.upload_file(
                    file_path,
                    self.bucket_name,
                    object_name,
                    ExtraArgs=extra_args
                )

            file_url = f"{S3_URL}/{self.bucket_name}/{object_name}"
            print("✓")
            return True, file_url
        except FileNotFoundError:
            message = f"Файл {file_path} не найден"
            logging.error(message)
            print("✗")
            return False, message
        except ClientError as e:
            message = f"Ошибка загрузки в S3: {str(e)}"
            logging.error(message)
            print("✗")
            return False, message
        except Exception as e:
            message = f"Непредвиденная ошибка при загрузке файла: {str(e)}"
            logging.error(message)
            print("✗")
            return False, message


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
        # Получаем информацию о токене
        token_info = await get_token_info(api_handler)
        if not token_info:
            return
            
        # Получаем исторические данные
        all_historical_data = await get_historical_data(api_handler, token_info)
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
        
        # Обрабатываем категории
        categories_df = process_categories(data_processor, token_df)
        if categories_df.empty:
            print("Ошибка: Нет данных категорий для анализа")
            return
            
        # Сохраняем данные и создаем визуализацию
        await save_and_visualize(token_df, categories_df, token_info, data_processor, visualizer)
        
    except Exception as e:
        logging.error(f"Ошибка в основной программе: {e}")
        print(f"\nПроизошла ошибка: {e}")
        print("Проверьте лог-файл для деталей")
    finally:
        await api_handler.close()


async def get_token_info(api_handler):
    """Получение информации о токене"""
    print("\n=== Test Request ===")
    query = input("Enter token ID (numeric): ").strip()

    # Проверяем, что введено число
    if not query.isdigit():
        print("Error: Please enter a numeric token ID")
        return None

    # Получаем информацию о токене
    token_info = await api_handler.get_token_info(query)
    if not token_info:
        print("Token not found")
        return None

    print("\nToken Information:")
    print(f"ID: {token_info['id']}")
    print(f"Symbol: {token_info['symbol']}")
    print(f"Name: {token_info['name']}")
    
    # Тестовый запрос
    if await test_token_request(api_handler, token_info) == False:
        return None
        
    return token_info


async def test_token_request(api_handler, token_info):
    """Тестовый запрос данных для токена"""
    test_continue = input("\nПродолжить тестовый запрос? (y/n): ").lower()
    
    if test_continue != 'y':
        print("\n=== Пропуск тестового запроса ===")
        return True
        
    # Запрашиваем даты для тестового запроса
    print("\nВведите даты для тестового запроса (формат: YYYY-MM-DD)")
    
    dates = get_test_dates()
    if not dates:
        return False
        
    start_date, end_date = dates
    
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
        return False

    # Запрос на продолжение
    continue_analysis = input("\nПродолжить с полным анализом? (y/n): ").lower()
    return continue_analysis == 'y'


def get_test_dates():
    """Получение дат для тестового запроса"""
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

            return start_date, end_date
                
        except ValueError:
            print("Неверный формат даты. Используйте формат YYYY-MM-DD")
            continue
    
    return None


async def get_historical_data(api_handler, token_info):
    """Получение исторических данных"""
    print("\n=== Получение исторических данных ===")
    all_historical_data = []

    print("\nПериоды анализа:")
    for start, end in ANALYSIS_DATES:
        print(f"- {start} to {end}")

    MAX_RETRIES = 10  # Максимальное количество попыток для каждого периода

    with tqdm(total=len(ANALYSIS_DATES), desc="Прогресс запросов") as pbar:
        for start_date, end_date in ANALYSIS_DATES:
            period_data = await fetch_period_data(
                api_handler, 
                token_info['id'], 
                start_date, 
                end_date, 
                MAX_RETRIES
            )
                
            if period_data:
                all_historical_data.extend(period_data)
                print(f"\nУспешно получены данные за период {start_date} - {end_date}")
            else:
                print(f"\nПропускаем период {start_date} - {end_date}")

            pbar.update(1)

    return all_historical_data


async def fetch_period_data(api_handler, token_id, start_date, end_date, max_retries):
    """Получение данных за период с повторными попытками"""
    retry_count = 0
    period_data = None

    while retry_count < max_retries:
        try:
            await asyncio.sleep(1)  # Небольшая задержка между запросами
            period_data = await api_handler.get_historical_data(
                token_id,
                start_date,
                end_date
            )
            if period_data:
                break
            retry_count += 1
            if retry_count < max_retries:
                print(f"\nПопытка {retry_count + 1} из {max_retries} для периода {start_date} - {end_date}")
        except Exception as e:
            print(f"\nОшибка при получении данных: {e}")
            retry_count += 1
            if retry_count < max_retries:
                print(f"Повторная попытка {retry_count + 1} из {max_retries}")

    if not period_data and retry_count >= max_retries:
        print(f"\nНе удалось получить данные за период {start_date} - {end_date} после {max_retries} попыток")
        retry_decision = input("Повторить попытки для этого периода? (y/n): ").lower()

        while retry_decision == 'y':
            period_data = await retry_period_data(api_handler, token_id, start_date, end_date, max_retries)
            if not period_data:
                retry_decision = input("Повторить попытки снова? (y/n): ").lower()
            else:
                break

    return period_data


async def retry_period_data(api_handler, token_id, start_date, end_date, max_retries):
    """Повторные попытки получения данных за период"""
    retry_count = 0
    while retry_count < max_retries:
        try:
            await asyncio.sleep(1)
            period_data = await api_handler.get_historical_data(
                token_id,
                start_date,
                end_date
            )
            if period_data:
                return period_data
            retry_count += 1
            if retry_count < max_retries:
                print(f"\nДополнительная попытка {retry_count + 1} из {max_retries}")
        except Exception as e:
            print(f"\nОшибка при получении данных: {e}")
            retry_count += 1
    
    return None


def process_categories(data_processor, token_df):
    """Обработка данных категорий"""
    print("\n=== Обработка данных категорий ===")
    categories_df = data_processor.process_data(token_df)
    
    if not categories_df.empty:
        print(f"Получено записей для категорий: {len(categories_df)}")
        
    return categories_df


async def save_and_visualize(token_df, categories_df, token_info, data_processor, visualizer):
    """Сохранение данных и создание визуализации"""
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

    # Создание визуализации
    html_result = await create_visualization(token_df, categories_df, token_info, visualizer)
    
    # Итоговый отчет
    print("\nАнализ завершен успешно!")
    print("Созданные файлы:")
    print(f"1. Данные токена: {token_filename}")
    print(f"2. Анализ категорий: {analysis_filename}")
    
    if html_result and html_result.get("local_file"):
        print(f"3. Интерактивный график (локально): {html_result['local_file']}")
        
        if html_result.get("s3_url"):
            print(f"4. Интерактивный график (онлайн): {html_result['s3_url']}")


async def create_visualization(token_df, categories_df, token_info, visualizer):
    """Создание и сохранение визуализации"""
    print("\nСоздание визуализации...")

    # Проверяем данные перед визуализацией
    print("\nПроверка данных для визуализации:")
    print(f"Токен {token_info['symbol']}:")
    print(f"- Временной период: с {token_df['date'].min()} по {token_df['date'].max()}")
    print(f"- Диапазон цен: ${token_df['price'].min():.4f} - ${token_df['price'].max():.4f}")
    print("\nКатегории:")
    print(f"- Количество категорий: {len(categories_df['Category'].unique())}")
    print(f"- Временной период: с {categories_df['Date'].min()} по {categories_df['Date'].max()}")

    # Создаем график
    fig = visualizer.create_combined_plot(
        categories_df=categories_df,
        token_df=token_df,
        token_symbol=token_info['symbol']
    )

    # Сохраняем график
    html_result = visualizer.save_plot(fig, token_info['symbol'])

    if html_result and html_result.get("local_file") and os.path.exists(html_result["local_file"]):
        print(f"\nГрафик сохранен в {html_result['local_file']}")
        print(f"Размер файла: {os.path.getsize(html_result['local_file']):,} байт")

        # Проверяем содержимое файла
        with open(html_result["local_file"], 'r', encoding='utf-8') as f:
            content = f.read()
            if len(content) < 100:  # Минимальный размер валидного HTML
                print("Предупреждение: Файл графика может быть поврежден")
    else:
        print("Ошибка: Не удалось сохранить график")
        
    return html_result


def generate_api_documentation():
    """Генерация документации по API"""
    docs = {
        "endpoints": [
            {
                "name": "Cryptocurrency Info",
                "endpoint": "/cryptocurrency/info",
                "description": "Получение информации о токене по ID или тикеру",
                "parameters": [
                    {"name": "id", "type": "string", "description": "ID токена в CoinMarketCap"},
                    {"name": "symbol", "type": "string", "description": "Тикер токена (если не указан id)"}
                ],
                "example": f"{BASE_URL}/cryptocurrency/info?id=1"
            },
            {
                "name": "Historical Quotes",
                "endpoint": "/cryptocurrency/quotes/historical",
                "description": "Получение исторических данных токена за период",
                "parameters": [
                    {"name": "id", "type": "string", "description": "ID токена в CoinMarketCap"},
                    {"name": "time_start", "type": "string", "description": "Начало периода в формате YYYY-MM-DDT00:00:00Z"},
                    {"name": "time_end", "type": "string", "description": "Конец периода в формате YYYY-MM-DDT23:59:59Z"},
                    {"name": "interval", "type": "string", "description": "Интервал данных: 1d, 1h, 5m и т.д."},
                    {"name": "convert", "type": "string", "description": "Валюта конвертации, например USD"}
                ],
                "example": f"{BASE_URL}/cryptocurrency/quotes/historical?id=1&time_start=2023-01-01T00:00:00Z&time_end=2023-01-31T23:59:59Z&interval=1d&convert=USD"
            }
        ],
        "s3_integration": {
            "description": "Интеграция с облачным хранилищем S3 для загрузки HTML графиков",
            "storage_url": S3_URL,
            "usage_example": "После генерации графика, он автоматически загружается в S3 и возвращается URL для доступа",
            "result_format": {
                "local_file": "Локальный путь к сохраненному HTML файлу",
                "s3_url": "URL для доступа к графику в S3 хранилище"
            }
        }
    }
    
    # Сохранение документации в JSON
    docs_path = os.path.join(CONFIG["save_path"], "api_documentation.json")
    with open(docs_path, 'w') as f:
        json.dump(docs, f, indent=4)
    
    print(f"Документация API сохранена в {docs_path}")
    return docs_path


if __name__ == "__main__":
    # Создаем пример конфигурационного файла, если его нет
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(config_path):
        example_config = {
            "max_requests_per_minute": 30,
            "batch_size": 50,
            "input_file": r"C:\Users\Main\Pitonio\crypto_etf\category_downloader_123.xlsx",
            "output_folder": r"C:\Users\Main\Pitonio\crypto_etf\results",
            "save_path": r"C:\Users\Main\Pitonio\crypto_etf",
            "log_file": "crypto_api.log",
            "log_level": "INFO",
            "api_base_url": "https://pro-api.coinmarketcap.com/v2"
        }
        try:
            with open(config_path, 'w') as f:
                json.dump(example_config, f, indent=4)
            print(f"Создан пример конфигурационного файла: {config_path}")
        except Exception as e:
            print(f"Не удалось создать файл конфигурации: {e}")
    
    if os.name == 'nt':  # для Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
