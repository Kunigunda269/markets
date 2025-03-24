import asyncio
import aiohttp
import pandas as pd
import logging
import os
import sys
import time
import json
import random
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# === Конфигурация ===
CONFIG = {
    # API параметры
    "api_key": "123",    # Обновленный API ключ
    "max_requests_per_minute": 30,      # Увеличен до максимума по документации
    
    # Оптимизация производительности
    "batch_size": 100,                  # Максимальный размер батча для API v1
    "concurrent_requests": 30,          # Максимальное число параллельных запросов
    "timeout": 60,                      # Таймаут в секундах
    
    # Параметры повторных попыток
    "max_retries": 3,                   # Уменьшено для ускорения
    "retry_delay": 1,                   # Уменьшено для ускорения
    
    # Параметры кэширования
    "cache_file": "cache.json",
    "cache_expiry_days": 90,            # Увеличен срок кэширования
    "cache_metadata_days": 180,         # Долгосрочное кэширование метаданных
    
    # Пути к файлам
    "input_file": r"C:\Users\Илья\PycharmProjects\crypto etf\category_downloader_123.xlsx", 
    "output_folder": r"C:\Users\Илья\PycharmProjects",
    
    # Дополнительные настройки
    "request_delay": 1,                 # Уменьшена задержка для ускорения
    "save_interval": 100,               # Интервал сохранения промежуточных результатов
    "count_param": 1                    # Запрашивать только одну точку данных в истории
}

# Создаем папку для результатов, если она не существует
os.makedirs(CONFIG["output_folder"], exist_ok=True)

# Базовые URL и заголовки для API v1 (более стабильная версия)
BASE_URL_METADATA = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/info"
BASE_URL_HISTORICAL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/historical"
HEADERS = {
    "X-CMC_PRO_API_KEY": CONFIG["api_key"],
    "Accept": "application/json"
}

# Проверка существования файла
if not os.path.exists(CONFIG["input_file"]):
    print(f"ОШИБКА: Файл {CONFIG['input_file']} не найден!")
    print("Убедитесь, что файл category_downloader_123.xlsx находится в той же папке, что и скрипт.")
    sys.exit(1)

# === Логирование ===
logging.basicConfig(
    filename=os.path.join(CONFIG["output_folder"], "crypto_combined.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def log_and_print(message, level="info"):
    """Улучшенная функция логирования."""
    if level == "info":
        logging.info(message)
    elif level == "error":
        logging.error(message)
    elif level == "warning":
        logging.warning(message)
    elif level == "debug":
        logging.debug(message)


class RateLimiter:
    """
    Управляет лимитами запросов к API с интеллектуальной паузой.
    
    Attributes:
        max_requests_per_minute (int): Максимальное количество запросов в минуту
        interval (float): Интервал между запросами
        last_call (float): Время последнего запроса
        request_count (int): Счетчик запросов
        reset_time (float): Время сброса счетчика
        is_waiting (bool): Флаг ожидания после 429 ошибки
    """

    def __init__(self, max_requests_per_minute: int):
        """
        Инициализация лимитера запросов.
        
        Args:
            max_requests_per_minute (int): Максимальное количество запросов в минуту
        """
        self.max_requests_per_minute = max_requests_per_minute
        self.interval = 60 / max_requests_per_minute
        self.last_call = time.time()
        self.request_count = 0
        self.reset_time = time.time() + 60
        self.is_waiting = False

    async def wait(self):
        """
        Асинхронное ожидание перед запросом с учетом лимитов и 429 ошибок.
        
        Основные действия:
        - Проверка и сброс счетчика запросов
        - Паузы при превышении лимита
        - Специальная обработка 429 ошибки с расширенным ожиданием
        """
        now = time.time()

        # Расширенная логика ожидания после 429 ошибки
        if self.is_waiting:
            wait_time = 66  # Увеличенное время ожидания
            log_and_print(f"[WARNING] Ожидание после 429 ошибки: {wait_time} секунд", "warning")
            await asyncio.sleep(wait_time)
            self.is_waiting = False
            self.request_count = 0
            self.reset_time = time.time() + 60
            return

        # Сброс счетчика по истечении минуты
        if now >= self.reset_time:
            self.request_count = 0
            self.reset_time = now + 60

        # Контроль количества запросов
        if self.request_count >= self.max_requests_per_minute:
            log_and_print("[WARNING] Превышен лимит запросов. Пауза.", "warning")
            await asyncio.sleep(66)
            self.request_count = 0
            self.reset_time = time.time() + 60

        # Равномерное распределение запросов
        elapsed = now - self.last_call
        if elapsed < self.interval:
            await asyncio.sleep(self.interval - elapsed)

        self.last_call = time.time()
        self.request_count += 1

    def set_429_received(self):
        """
        Устанавливает флаг получения 429 ошибки для специальной обработки.
        """
        self.is_waiting = True
        log_and_print("[CRITICAL] Получена 429 ошибка. Активирован режим ожидания.", "warning")


rate_limiter = RateLimiter(CONFIG["max_requests_per_minute"])


def price_change_percentage(open_price, close_price):
    """Вычисление процентного изменения цены."""
    if open_price == 0:
        return 0
    return ((close_price - open_price) / open_price) * 100


class CacheManager:
    """Управление кэшем данных токенов."""

    def __init__(self, cache_file, expiry_days):
        self.cache_file = cache_file
        self.expiry_days = expiry_days
        self.cache = self._load_cache()

    def _load_cache(self):
        """Загрузка кэша из файла."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                log_and_print(f"Ошибка загрузки кэша: {e}", "error")
                return {}
        return {}

    def _save_cache(self):
        """Сохранение кэша в файл."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f)
        except Exception as e:
            log_and_print(f"Ошибка сохранения кэша: {e}", "error")

    def get_cached_data(self, token_id, time_start, time_end):
        """Получение кэшированных данных с проверкой актуальности."""
        if str(token_id) not in self.cache:
            return None

        cached_data = self.cache[str(token_id)]
        cache_time = datetime.fromisoformat(cached_data.get('timestamp', '2000-01-01'))

        # Проверяем актуальность данных
        if datetime.now() - cache_time > timedelta(days=self.expiry_days):
            return None

        # Проверяем соответствие временного диапазона
        if cached_data.get('time_start') != time_start or cached_data.get('time_end') != time_end:
            return None

        return cached_data.get('data')

    def update_cache(self, token_id, data, time_start, time_end):
        """Обновление кэша новыми данными."""
        self.cache[str(token_id)] = {
            'data': data,
            'timestamp': datetime.now().isoformat(),
            'time_start': time_start,
            'time_end': time_end
        }
        self._save_cache()


def extract_price_and_market_cap(data, endpoint_type, token_id):
    try:
        if endpoint_type == "latest":
            quote_data = data["data"][str(token_id)]["quote"]["USD"]
            return quote_data.get("price"), quote_data.get("market_cap")

        elif endpoint_type == "historical":
            quotes = data["data"].get("quotes", [])
            if quotes:
                quote_data = quotes[-1]["quote"]["USD"]
                return quote_data.get("price"), quote_data.get("market_cap")

        return None, None

    except (KeyError, IndexError) as e:
        log_and_print(f"[WARNING] Ошибка при извлечении данных: {str(e)}")
        return None, None


def format_date_for_api(date_str):
    """Улучшенное форматирование и валидация даты для API."""
    try:
        # Очищаем строку от лишних пробелов
        date_str = date_str.strip()
        
        # Проверяем формат даты
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        current_date = datetime.now(timezone.utc)
        
        # Если дата в будущем, используем вчерашнюю дату
        if parsed_date > current_date:
            log_and_print(f"[WARNING] Дата {date_str} находится в будущем, используем вчерашнюю дату", "warning")
            parsed_date = current_date - timedelta(days=1)
        
        # Проверяем, что дата не слишком старая (ограничения API могут варьироваться)
        # CoinMarketCap обычно хранит данные не более нескольких лет
        min_date = datetime(2013, 4, 28, tzinfo=timezone.utc)  # Примерно дата начала CoinMarketCap
        if parsed_date < min_date:
            log_and_print(f"[WARNING] Дата {date_str} слишком старая, используем минимальную доступную", "warning")
            parsed_date = min_date
        
        # Форматируем даты согласно документации API
        # Для современного API часто используется ISO 8601
        date_str = parsed_date.strftime("%Y-%m-%d")
        
        return (date_str, date_str)
        
    except ValueError:
        log_and_print(f"[ERROR] Неверный формат даты '{date_str}'. Используйте формат YYYY-MM-DD", "error")
        # В случае ошибки возвращаем вчерашнюю дату
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        return (yesterday, yesterday)


def read_excel_file(file_path):
    """Чтение Excel файла с обработкой различных кодировок."""
    try:
        # Пробуем прочитать файл
        df = pd.read_excel(file_path)
        
        # Проверяем и приводим к единому виду столбец ID
        if 'id' in df.columns:
            # Переименовываем для единообразия
            df = df.rename(columns={'id': 'ID'})
        elif 'ID' not in df.columns:
            log_and_print("[ERROR] В файле отсутствует столбец с идентификаторами токенов", "error")
            return None
            
        log_and_print(f"[INFO] Загружен Excel файл: {len(df)} строк")
        log_and_print(f"[INFO] Столбцы: {df.columns.tolist()}")
        
        return df
        
    except Exception as e:
        log_and_print(f"[ERROR] Ошибка при чтении файла: {str(e)}", "error")
        return None


def save_to_excel(df, filename):
    """Безопасное сохранение в Excel с обработкой ошибок доступа."""
    try:
        # Создаем директорию, если она не существует
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # Форматируем данные перед сохранением
        df['ID'] = df['ID'].astype(int)  # ID как целое число
        df['Symbol'] = df['Symbol'].astype(str)  # Symbol как текст
        
        # Форматируем числовые столбцы
        def format_price(x):
            try:
                if pd.isna(x) or x is None:
                    return None
                return f"{float(x):.8f}"
            except:
                return None

        def format_market_cap(x):
            try:
                if pd.isna(x) or x is None:
                    return None
                return f"{float(x):.2f}"
            except:
                return None

        df['Price (USD)'] = df['Price (USD)'].apply(format_price)
        df['Market Cap (USD)'] = df['Market Cap (USD)'].apply(format_market_cap)
        
        # Проверяем и устанавливаем порядок столбцов
        required_columns = ['ID', 'Symbol', 'Price (USD)', 'Market Cap (USD)']
        df = df[required_columns]
        
        # Попытка сохранить файл
        df.to_excel(filename, index=False)
        log_and_print(f"[SUCCESS] Данные сохранены в {filename}", "success")
        
        # Проверяем сохраненные данные
        saved_df = pd.read_excel(filename)
        log_and_print(f"[INFO] Проверка сохраненных данных: {len(saved_df)} строк", "info")
        log_and_print(f"[INFO] Столбцы: {saved_df.columns.tolist()}", "info")
        return True
        
    except PermissionError:
        # Если файл открыт или нет прав доступа
        alt_filename = f"{os.path.splitext(filename)[0]}_{int(time.time())}.xlsx"
        try:
            df.to_excel(alt_filename, index=False)
            log_and_print(f"[WARNING] Не удалось сохранить в {filename}. Данные сохранены в {alt_filename}", "warning")
            return True
        except Exception as e:
            log_and_print(f"[ERROR] Не удалось сохранить данные: {str(e)}", "error")
            return False
    except Exception as e:
        log_and_print(f"[ERROR] Ошибка при сохранении данных: {str(e)}", "error")
        return False


async def get_valid_tokens(df, session=None, count=None):
    try:
        # Проверяем наличие столбца ID
        if 'ID' not in df.columns:
            log_and_print("[ERROR] В файле отсутствует столбец 'ID'", "error")
            return []
        
        # Добавляем отладочную информацию для понимания данных
        log_and_print(f"[DEBUG] Используем столбец 'ID' для идентификаторов", "debug")
        
        tokens = []
        for _, row in df.iterrows():
            try:
                token = {
                    'ID': int(row['ID']),  # Используем ID в верхнем регистре
                    'Symbol': str(row['Symbol'])
                }
                tokens.append(token)
            except (ValueError, TypeError) as e:
                log_and_print(f"[WARNING] Ошибка обработки токена {row.get('Symbol', 'Unknown')}: {e}", "warning")
        
        log_and_print(f"[DEBUG] Успешно загружено {len(tokens)} токенов", "debug")
        
        # Выборка случайных токенов если нужно
        if count:
            if len(tokens) < count:
                log_and_print(f"[WARNING] Доступно только {len(tokens)} токенов, запрошено {count}", "warning")
            
            selected_tokens = random.sample(tokens, min(count, len(tokens)))
            log_and_print(f"[DEBUG] Выбрано {len(selected_tokens)} случайных токенов", "debug")
            return selected_tokens
        
        return tokens
        
    except Exception as e:
        log_and_print(f"[ERROR] Ошибка при получении токенов: {str(e)}", "error")
        return []


async def fetch_data(
    session: aiohttp.ClientSession, 
    token_id: int, 
    start_date: str, 
    end_date: str
) -> Optional[Dict[str, Any]]:
    """
    Получение исторических данных о токене по заданным датам.
    """
    # Используем эндпоинт для исторических данных
    url = BASE_URL_HISTORICAL
    
    # Параметры запроса для исторических данных
    params = {
        "id": token_id,
        "convert": "USD",
        "time_start": start_date,
        "time_end": end_date
    }
    
    for attempt in range(CONFIG["max_retries"]):
        try:
            await rate_limiter.wait()
            
            # Детальное логирование для отладки
            log_and_print(f"[DEBUG] Запрос к {url} для токена {token_id} с {start_date} по {end_date}", "debug")
            
            async with session.get(url, params=params, headers=HEADERS) as response:
                if response.status == 429:
                    rate_limiter.set_429_received()
                    log_and_print(f"[CRITICAL] Превышен лимит для токена {token_id}", "warning")
                    await asyncio.sleep(66)
                    continue
                
                if response.status != 200:
                    log_and_print(f"[ERROR] Ошибка API {response.status} для токена {token_id}", "error")
                    # Попробуем получить текст ошибки для лучшей диагностики
                    try:
                        error_text = await response.text()
                        log_and_print(f"[ERROR] Ответ: {error_text[:200]}", "error")
                    except:
                        pass
                    # Увеличиваем задержку при ошибках
                    await asyncio.sleep(CONFIG["retry_delay"] * (attempt + 1))
                    continue
                
                # Безопасное декодирование JSON
                try:
                    data = await response.json()
                    
                    # Простая проверка структуры данных
                    if 'data' not in data:
                        log_and_print(f"[WARNING] Нет ключа 'data' в ответе для токена {token_id}", "warning")
                        continue
                    
                    # Проверяем наличие исторических данных
                    if 'quotes' not in data['data'] or not data['data']['quotes']:
                        log_and_print(f"[WARNING] Нет исторических данных для токена {token_id}", "warning")
                        continue
                    
                    # Берем последнюю доступную цену из исторических данных
                    last_quote = data['data']['quotes'][-1]
                    
                    if 'quote' not in last_quote or 'USD' not in last_quote['quote']:
                        log_and_print(f"[WARNING] Нет данных USD для токена {token_id}", "warning")
                        continue
                    
                    # Получаем цену и капитализацию
                    usd_data = last_quote['quote']['USD']
                    price = usd_data.get('price')
                    market_cap = usd_data.get('market_cap')
                    
                    # Дополнительная проверка значений
                    if price is None or market_cap is None or price <= 0 or market_cap <= 0:
                        log_and_print(f"Некорректные значения price={price}, market_cap={market_cap} для токена {token_id}", "warning")
                        continue
                    
                    # Если все проверки прошли, возвращаем данные
                    return data
                    
                except json.JSONDecodeError:
                    log_and_print(f"[ERROR] Ошибка декодирования JSON для токена {token_id}", "error")
                    continue
                except Exception as e:
                    log_and_print(f"[ERROR] Ошибка при обработке данных: {str(e)}", "error")
                    continue
        
        except aiohttp.ClientError as e:
            log_and_print(f"[ERROR] Сетевая ошибка для токена {token_id}: {e}", "error")
            await asyncio.sleep(CONFIG["retry_delay"] * (attempt + 1))
        
        except Exception as e:
            log_and_print(f"[ERROR] Неожиданная ошибка для токена {token_id}: {e}", "error")
            await asyncio.sleep(CONFIG["retry_delay"])
    
    log_and_print(f"[ERROR] Превышено количество попыток для токена {token_id}", "error")
    return None


async def check_token_status(session, token_id):
    """Проверка статуса токена через metadata API."""
    url = BASE_URL_METADATA
    params = {"id": token_id}
    
    for attempt in range(3):
        try:
            await rate_limiter.wait()
            timeout = aiohttp.ClientTimeout(total=30)
            async with session.get(url, params=params, headers=HEADERS, timeout=timeout) as response:
                if response.status == 429:
                    log_and_print("Превышен лимит запросов, ожидание 66 секунд", "warning")
                    await asyncio.sleep(66)
                    continue
                    
                if response.status == 200:
                    data = await response.json()
                    if str(token_id) in data.get("data", {}):
                        token_info = data["data"][str(token_id)]
                        is_active = token_info.get("is_active", 0)
                        platform = token_info.get("platform")
                        slug = token_info.get("slug", "")
                        cmc_url = f"https://coinmarketcap.com/currencies/{slug}/"
                        return is_active == 1, platform, cmc_url
                return False, None, None
        except asyncio.CancelledError:
            log_and_print(f"Запрос для токена {token_id} был отменен", "warning")
            return False, None, None
        except Exception as e:
            log_and_print(f"Ошибка при проверке токена {token_id}: {str(e)}", "error")
            if attempt < 2:
                await asyncio.sleep(5)
                continue
            return False, None, None


async def process_tokens_with_endpoint(tokens, start_date, end_date, df, session, is_test=False):
    """
    Оптимизированная обработка токенов с использованием пакетных запросов и индикатором прогресса.
    Args:
        tokens: список токенов для обработки
        start_date: начальная дата
        end_date: конечная дата
        df: исходный DataFrame с данными
        session: сессия aiohttp
        is_test: флаг тестового режима
    Returns:
        Кортеж (успешные результаты, ошибки)
    """
    from tqdm import tqdm
    
    results = []
    errors = []
    processed_ids = set()  # Для отслеживания обработанных токенов
    results_lock = asyncio.Lock()  # Блокировка для безопасной записи результатов
    
    # Если режим тестовый, обрабатываем только до 5 успешных токенов
    max_results = 5 if is_test else float('inf')
    
    # Создаем прогресс-бар
    total = len(tokens)
    pbar = tqdm(total=total, desc="Обработка токенов", unit="токен")
    
    # Файл для промежуточных результатов
    temp_file = os.path.join(CONFIG["output_folder"], "temp_results.xlsx")
    
    # Сохранение промежуточных результатов
    async def save_intermediate_results():
        if results:
            df_results = pd.DataFrame(results)
            if not df_results.empty:
                df_results = df_results[['ID', 'Symbol', 'Price (USD)', 'Market Cap (USD)']]
                df_results.to_excel(temp_file, index=False)
                log_and_print(f"[INFO] Сохранено {len(results)} промежуточных результатов", "info")
    
    # Обработка одного токена (используется только в тестовом режиме)
    async def process_single_token(token):
        token_id = token.get('ID')
        if token_id in processed_ids:
            return None
        
        processed_ids.add(token_id)
        
        try:
            response = await fetch_data(session, token_id, start_date, end_date)
            
            if not response or not isinstance(response, dict) or 'data' not in response:
                pbar.update(1)
                return {'status': 'error', 'token': token, 'error': 'no_data'}
            
            # Проверки и извлечение данных из ответа
            if 'quotes' not in response['data'] or not response['data']['quotes']:
                pbar.update(1)
                return {'status': 'error', 'token': token, 'error': 'no_quotes'}
            
            last_quote = response['data']['quotes'][-1]
            
            if 'quote' not in last_quote or 'USD' not in last_quote['quote']:
                pbar.update(1)
                return {'status': 'error', 'token': token, 'error': 'no_usd_data'}
            
            usd_data = last_quote['quote']['USD']
            price = usd_data.get('price')
            market_cap = usd_data.get('market_cap')
            
            if not price or not market_cap or float(market_cap) <= 0:
                pbar.update(1)
                return {'status': 'error', 'token': token, 'error': 'invalid_values'}
            
            result = {
                'ID': int(token_id),
                'Symbol': str(token.get('Symbol', '')),
                'Price (USD)': f"{float(price):.8f}",
                'Market Cap (USD)': f"{float(market_cap):.2f}"
            }
            
            pbar.update(1)
            return {'status': 'success', 'result': result}
        
        except Exception as e:
            log_and_print(f"[ERROR] Ошибка при обработке токена {token_id}: {str(e)}", "error")
            pbar.update(1)
            return {'status': 'error', 'token': token, 'error': str(e)}
    
    # Обработка результатов батч-запроса
    async def process_batch_response(batch_tokens, batch_response):
        if not batch_response or not isinstance(batch_response, dict) or 'data' not in batch_response:
            # Если весь батч-запрос не удался, отмечаем все токены как ошибки
            for token in batch_tokens:
                pbar.update(1)
                async with results_lock:
                    errors.append({
                        'ID': token['ID'],
                        'Symbol': token.get('Symbol', ''),
                    })
            return
        
        # Обрабатываем каждый токен в батче
        for token in batch_tokens:
            token_id = token.get('ID')
            if token_id in processed_ids:
                pbar.update(1)
                continue
            
            processed_ids.add(token_id)
            
            try:
                # Проверяем, есть ли данные для этого токена в ответе
                if str(token_id) not in batch_response['data']:
                    pbar.update(1)
                    async with results_lock:
                        errors.append({
                            'ID': token_id,
                            'Symbol': token.get('Symbol', ''),
                        })
                    continue
                
                # Получаем данные токена
                token_data = batch_response['data'][str(token_id)]
                
                # Извлекаем цену и капитализацию
                if 'quote' not in token_data or 'USD' not in token_data['quote']:
                    pbar.update(1)
                    async with results_lock:
                        errors.append({
                            'ID': token_id,
                            'Symbol': token.get('Symbol', ''),
                        })
                    continue
                
                usd_data = token_data['quote']['USD']
                price = usd_data.get('price')
                market_cap = usd_data.get('market_cap')
                
                if not price or not market_cap or float(market_cap) <= 0:
                    pbar.update(1)
                    async with results_lock:
                        errors.append({
                            'ID': token_id,
                            'Symbol': token.get('Symbol', ''),
                        })
                    continue
                
                # Добавляем успешный результат
                result = {
                    'ID': int(token_id),
                    'Symbol': str(token.get('Symbol', '')),
                    'Price (USD)': f"{float(price):.8f}",
                    'Market Cap (USD)': f"{float(market_cap):.2f}"
                }
                
                pbar.update(1)
                async with results_lock:
                    results.append(result)
                    
                    # В тестовом режиме останавливаемся после достижения нужного числа результатов
                    if is_test and len(results) >= max_results:
                        return True
            
            except Exception as e:
                log_and_print(f"[ERROR] Ошибка обработки токена {token_id} из batch: {str(e)}", "error")
                pbar.update(1)
                async with results_lock:
                    errors.append({
                        'ID': token_id,
                        'Symbol': token.get('Symbol', ''),
                    })
        
        return False
    
    try:
        # Разные режимы обработки в зависимости от теста или основного режима
        if is_test:
            # В тестовом режиме обрабатываем последовательно до 5 успешных
            for token in tokens:
                if len(results) >= max_results:
                    break
                
                result = await process_single_token(token)
                
                if result and result['status'] == 'success':
                    async with results_lock:
                        results.append(result['result'])
                        log_and_print(f"[SUCCESS] Успешно получены данные для {token['Symbol']}", "info")
                elif result and result['status'] == 'error':
                    error_token = result['token']
                    async with results_lock:
                        errors.append({
                            'ID': error_token['ID'],
                            'Symbol': error_token.get('Symbol', ''),
                        })
        else:
            # В основном режиме используем батч-запросы для повышения эффективности
            # Используем максимальный размер батча 100 токенов (ограничение API)
            batch_size = min(100, CONFIG.get("batch_size", 20))
            save_frequency = CONFIG.get("save_interval", 50)
            
            for i in range(0, len(tokens), batch_size):
                if len(results) >= max_results:
                    break
                    
                # Берем очередной батч токенов
                batch = tokens[i:i + batch_size]
                token_ids = [token['ID'] for token in batch]
                
                # Выполняем батч-запрос
                batch_response = await fetch_batch_data(session, token_ids, start_date, end_date)
                
                # Обрабатываем результаты батч-запроса
                should_stop = await process_batch_response(batch, batch_response)
                if should_stop:
                    break
                
                # Сохраняем промежуточные результаты периодически
                if (i + batch_size) % save_frequency == 0 or (i + batch_size) >= len(tokens):
                    await save_intermediate_results()
                
                # Соблюдаем ограничение на количество запросов в минуту
                if (i + batch_size) < len(tokens):
                    # Один батч-запрос считается за один запрос к API
                    await asyncio.sleep(60 / CONFIG["max_requests_per_minute"])
                
                # Обновляем информацию о прогрессе
                pbar.set_postfix(
                    успешных=len(results), 
                    ошибок=len(errors),
                    процент=f"{len(results)/(len(processed_ids))*100:.1f}%" if processed_ids else "0%"
                )
    
    except Exception as e:
        log_and_print(f"[ERROR] Ошибка при обработке токенов: {str(e)}", "error")
    finally:
        pbar.close()
    
    return results, errors


async def save_intermediate_results(results, start_date, end_date):
    """Промежуточное сохранение результатов для защиты от сбоев."""
    try:
        df_results = pd.DataFrame(results)
        if len(df_results) > 0:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            intermediate_file = os.path.join(
                CONFIG["output_folder"], 
                f"intermediate_{start_date}_{end_date}_{len(results)}_{timestamp}.xlsx"
            )
            df_results = df_results[['ID', 'Symbol', 'Price (USD)', 'Market Cap (USD)']]
            df_results.to_excel(intermediate_file, index=False)
            log_and_print(f"[INFO] Сохранено {len(results)} промежуточных результатов", "info")
    except Exception as e:
        log_and_print(f"[WARNING] Ошибка промежуточного сохранения: {e}", "warning")


async def save_test_results(results):
    """Сохранение тестовых результатов."""
    if not results:
        log_and_print("Тестовый запрос не вернул данных", "error")
        return False
    
    # Сохраняем все результаты в один файл
    if results:
        # Формируем имя файла с текущей датой и временем
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(CONFIG["output_folder"], f"result_test_{current_time}.xlsx")
        df_results = pd.DataFrame(results)
        
        # Выводим данные для проверки
        log_and_print("[DEBUG] Данные перед сохранением:", "debug")
        for result in results:
            log_and_print(f"[DEBUG] {result}", "debug")
        
        # Сохраняем в правильном порядке столбцов
        df_results = df_results[['ID', 'Symbol', 'Price (USD)', 'Market Cap (USD)']]
        
        if not save_to_excel(df_results, output_file):
            return False
        log_and_print(f"[INFO] Сохранено {len(results)} тестовых результатов")
    else:
        log_and_print("[ERROR] Тестовый запрос не вернул данных", "error")
        return False


async def fetch_batch_data(session, token_ids, start_date, end_date):
    """
    Получение данных сразу для нескольких токенов в одном запросе через v1 API.
    Значительно эффективнее, чем отдельные запросы.
    """
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/historical"
    
    # Ограничение: максимум 100 ID в одном запросе
    if len(token_ids) > 100:
        token_ids = token_ids[:100]
    
    # Конвертируем массив ID в строку с разделителями-запятыми
    ids_str = ",".join(map(str, token_ids))
    
    # Оптимизированные параметры запроса
    params = {
        "id": ids_str,
        "convert": "USD",
        "time_start": start_date,
        "time_end": end_date,
        "count": 1  # Запрашиваем только одну последнюю точку данных
    }
    
    for attempt in range(CONFIG["max_retries"]):
        try:
            await rate_limiter.wait()
            log_and_print(f"[DEBUG] Batch запрос для {len(token_ids)} токенов: {start_date}-{end_date}", "debug")
            
            async with session.get(url, params=params, headers=HEADERS) as response:
                if response.status == 429:
                    rate_limiter.set_429_received()
                    log_and_print(f"[CRITICAL] Превышен лимит запросов для batch", "warning")
                    await asyncio.sleep(66)
                    continue
                
                if response.status != 200:
                    error_text = await response.text()
                    log_and_print(f"[ERROR] Ошибка API {response.status} для batch: {error_text[:200]}", "error")
                    await asyncio.sleep(CONFIG["retry_delay"] * (attempt + 1))
                    continue
                
                try:
                    data = await response.json()
                    if 'data' not in data:
                        log_and_print("[WARNING] Нет ключа 'data' в batch ответе", "warning")
                        continue
                    
                    return data
                    
                except json.JSONDecodeError:
                    log_and_print("[ERROR] Ошибка декодирования JSON для batch запроса", "error")
                    continue
                except Exception as e:
                    log_and_print(f"[ERROR] Ошибка при обработке batch данных: {str(e)}", "error")
                    continue
        
        except aiohttp.ClientError as e:
            log_and_print(f"[ERROR] Сетевая ошибка для batch запроса: {e}", "error")
            await asyncio.sleep(CONFIG["retry_delay"] * (attempt + 1))
        
        except Exception as e:
            log_and_print(f"[ERROR] Неожиданная ошибка для batch запроса: {e}", "error")
            await asyncio.sleep(CONFIG["retry_delay"])
    
    log_and_print("[ERROR] Превышено количество попыток для batch запроса", "error")
    return None


async def main():
    """Главная функция с улучшенной батчевой обработкой."""
    start_time = time.time()  # Засекаем время начала выполнения
    
    try:
        log_and_print("[INFO] Начало работы программы...")

        # Загрузка файла
        df = read_excel_file(CONFIG["input_file"])
        if df is None:
            return

        # Проверяем наличие данных
        if len(df) == 0:
            log_and_print("[ERROR] Файл не содержит данных", "error")
            return

        # Создаем клиентскую сессию с увеличенными лимитами
        timeout = aiohttp.ClientTimeout(total=CONFIG["timeout"])
        connector = aiohttp.TCPConnector(limit=CONFIG["concurrent_requests"], force_close=True)
        
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            # Сначала спрашиваем про тестовый запрос
            operation_type = input("Выполнить тестовый запрос? (да/нет): ").strip().lower()
            while operation_type not in ['да', 'нет']:
                log_and_print("[ERROR] Пожалуйста, введите 'да' или 'нет'", "error")
                operation_type = input("Выполнить тестовый запрос? (да/нет): ").strip().lower()

            if operation_type == 'да':
                try:
                    log_and_print("[INFO] Подготовка тестового запроса...")
                    
                    # Получаем токены и перемешиваем их для лучшей выборки
                    all_tokens = await get_valid_tokens(df, session)
                    random.shuffle(all_tokens)
                    
                    # Запрашиваем даты для тестового запроса
                    while True:
                        start_date_str = input("Введите начальную дату (YYYY-MM-DD): ").strip()
                        end_date_str = input("Введите конечную дату (YYYY-MM-DD): ").strip()
                        
                        start_date = format_date_for_api(start_date_str)
                        end_date = format_date_for_api(end_date_str)
                        
                        if start_date and end_date:
                            break
                        log_and_print("[ERROR] Неверный формат даты", "error")

                    # Запускаем тестовую обработку (до 5 успешных токенов)
                    log_and_print("[INFO] Запуск тестового запроса...")
                    results, errors = await process_tokens_with_endpoint(
                        all_tokens[:50], start_date[0], end_date[1], df, session, is_test=True
                    )
                    
                    # Сохраняем результаты теста
                    if results:
                        output_file = os.path.join(
                            CONFIG["output_folder"], 
                            "result_test.xlsx"
                        )
                        
                        df_results = pd.DataFrame(results)
                        df_results = df_results[['ID', 'Symbol', 'Price (USD)', 'Market Cap (USD)']]
                        
                        if not save_to_excel(df_results, output_file):
                            return
                        
                        success_rate = len(results) / (len(results) + len(errors)) * 100 if results or errors else 0
                        log_and_print(f"[SUCCESS] Тест завершен. Успешно: {len(results)} токенов ({success_rate:.1f}%)", "info")
                    else:
                        log_and_print("[ERROR] Тест не вернул данных", "error")
                        return

                except Exception as e:
                    log_and_print(f"[ERROR] Ошибка в тестовом запросе: {str(e)}", "error")
                    return

            # После тестового запроса спрашиваем про основной
            proceed = input("Выполнить основной запрос? (да/нет): ").strip().lower()
            if proceed != 'да':
                return

            # Запрашиваем даты для основного запроса
            while True:
                start_date_str = input("Введите начальную дату (YYYY-MM-DD): ").strip()
                end_date_str = input("Введите конечную дату (YYYY-MM-DD): ").strip()
                
                start_date = format_date_for_api(start_date_str)
                end_date = format_date_for_api(end_date_str)
                
                if start_date and end_date:
                    break
                log_and_print("[ERROR] Неверный формат даты", "error")

            # Основной запрос с батчевой обработкой
            try:
                log_and_print("[INFO] Подготовка основного запроса...")
                all_tokens = await get_valid_tokens(df, session)
                
                if not all_tokens:
                    log_and_print("[ERROR] Не удалось получить токены", "error")
                    return
                
                total_tokens = len(all_tokens)
                log_and_print(f"[INFO] Найдено {total_tokens} токенов")
                
                # Расчет времени выполнения с учетом батчевой обработки
                batch_size = CONFIG["batch_size"]
                batch_count = (total_tokens + batch_size - 1) // batch_size
                requests_per_minute = CONFIG["max_requests_per_minute"]
                
                # Примерное время в минутах
                estimated_time_min = batch_count / requests_per_minute
                # Добавляем 20% на обработку ошибок и накладные расходы
                estimated_time_min *= 1.2
                
                log_and_print(f"[INFO] Примерное время выполнения: {estimated_time_min:.1f} минут " +
                              f"({estimated_time_min/60:.1f} часов)")
                
                log_and_print("[INFO] Запуск основного запроса...")
                # Запускаем обработку всех токенов с батчевыми запросами
                results, errors = await process_tokens_with_endpoint(
                    all_tokens, start_date[0], end_date[1], df, session, is_test=False
                )
                
                # Сохраняем результаты
                if results:
                    output_file = os.path.join(
                        CONFIG["output_folder"], 
                        f"result_{start_date_str}_{end_date_str}.xlsx"
                    )
                    
                    df_results = pd.DataFrame(results)
                    
                    # Выводим первые несколько результатов для проверки
                    log_and_print("[DEBUG] Первые результаты:", "debug")
                    for result in results[:5]:
                        log_and_print(f"[DEBUG] {result}", "debug")
                    
                    # Сохраняем в правильном порядке столбцов
                    df_results = df_results[['ID', 'Symbol', 'Price (USD)', 'Market Cap (USD)']]
                    
                    if not save_to_excel(df_results, output_file):
                        return
                    
                    # Сохраняем статистику ошибок отдельно для анализа
                    if errors:
                        errors_file = os.path.join(
                            CONFIG["output_folder"], 
                            f"errors_{start_date_str}_{end_date_str}.csv"
                        )
                        
                        df_errors = pd.DataFrame([{"ID": err["ID"], "Symbol": err["Symbol"]} for err in errors])
                        df_errors.to_csv(errors_file, index=False)
                        log_and_print(f"[INFO] Сохранено {len(errors)} токенов с ошибками", "info")
                    
                    # Итоговая статистика
                    success_rate = len(results) / total_tokens * 100
                    log_and_print(f"[SUCCESS] Обработка завершена. Получено {len(results)} результатов", "info")
                    log_and_print(f"[INFO] Процент успешных запросов: {success_rate:.1f}%", "info")
                    
                    # Общее время выполнения
                    total_time = time.time() - start_time
                    hours, remainder = divmod(total_time, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    log_and_print(f"[INFO] Общее время выполнения: {int(hours)}ч {int(minutes)}м {int(seconds)}с", "info")
                    
                    # Скорость обработки
                    tokens_per_second = total_tokens / total_time if total_time > 0 else 0
                    log_and_print(f"[INFO] Средняя скорость: {tokens_per_second:.1f} токенов в секунду", "info")
                    
                else:
                    log_and_print("[ERROR] Запрос не вернул данных", "error")
                    return

            except Exception as e:
                log_and_print(f"[ERROR] Ошибка в основном запросе: {str(e)}", "error")
                import traceback
                log_and_print(f"[DEBUG] {traceback.format_exc()}", "debug")
                return

    except asyncio.CancelledError:
        log_and_print("[WARNING] Программа прервана пользователем", "warning")
    except Exception as e:
        log_and_print(f"[ERROR] Критическая ошибка: {str(e)}", "error")
        import traceback
        log_and_print(f"[DEBUG] {traceback.format_exc()}", "error")
    finally:
        if 'session' in locals():
            await session.close()
        # Общее время выполнения
        total_time = time.time() - start_time
        hours, remainder = divmod(total_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        log_and_print(f"[INFO] Общее время выполнения: {int(hours)}ч {int(minutes)}м {int(seconds)}с", "info")


if __name__ == "__main__":
    asyncio.run(main())

