import asyncio
import aiohttp
import pandas as pd
import logging
import os
import sys
import time
import json
from datetime import datetime, timedelta, timezone
import random

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
    "api_key": "123",  # Ваш API ключ
    "batch_size": 10,
    "max_retries": 3,
    "retry_delay": 1,
    "cache_file": "cache.json",
    "cache_expiry_days": 7,
    "input_file": "category_downloader_123.xlsx",  # Имя входного файла
    "output_folder": "C:\\Users\\Main\\Pitonio\\crypto_etf",  # Папка для результатов
    "max_requests_per_minute": 30,  # Лимит запросов в минуту
    "request_delay": 2  # Увеличим задержку между запросами до 2 секунд
}

# Создаем папку для результатов, если она не существует
os.makedirs(CONFIG["output_folder"], exist_ok=True)

# Базовые URL и заголовки
BASE_URL_METADATA = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/info"
BASE_URL_HISTORICAL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
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
    """Контролирует количество запросов в минуту с паузой при превышении."""

    def __init__(self, max_requests_per_minute):
        self.max_requests_per_minute = max_requests_per_minute
        self.interval = 60 / max_requests_per_minute
        self.last_call = time.time()
        self.request_count = 0
        self.reset_time = time.time() + 60  # Время сброса счетчика
        self.is_waiting = False  # Флаг ожидания после 429 ошибки

    async def wait(self):
        """Ожидание перед следующим запросом с паузой при превышении лимита."""
        now = time.time()

        # Если находимся в режиме ожидания после 429
        if self.is_waiting:
            await asyncio.sleep(66)
            self.is_waiting = False
            self.request_count = 0
            self.reset_time = time.time() + 60
            return

        # Сброс счетчика, если прошла минута
        if now >= self.reset_time:
            self.request_count = 0
            self.reset_time = now + 60

        # Если превышен лимит запросов, ждем 66 секунд
        if self.request_count >= self.max_requests_per_minute:
            log_and_print("[WARNING] Превышен лимит запросов. Пауза 66 секунд.", "warning")
            await asyncio.sleep(66)
            self.request_count = 0
            self.reset_time = time.time() + 60

        elapsed = now - self.last_call
        if elapsed < self.interval:
            await asyncio.sleep(self.interval - elapsed)

        self.last_call = time.time()
        self.request_count += 1

    def set_429_received(self):
        """Устанавливает флаг получения 429 ошибки."""
        self.is_waiting = True


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
    """Форматирование и валидация даты для API."""
    try:
        # Очищаем строку от лишних пробелов
        date_str = date_str.strip()
        
        # Проверяем формат даты
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        
        # Проверка на будущую дату
        if parsed_date > datetime.now(timezone.utc):
            log_and_print(f"[WARNING] Дата {date_str} находится в будущем, используем текущую дату", "warning")
            parsed_date = datetime.now(timezone.utc)
        
        # Форматируем даты для начала и конца дня
        start_date = parsed_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = parsed_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        return (
            start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            end_date.strftime("%Y-%m-%dT%H:%M:%S.999Z")
        )
        
    except ValueError as e:
        log_and_print(f"[ERROR] Неверный формат даты '{date_str}'. Используйте формат YYYY-MM-DD", "error")
        return None


def read_excel_file(file_path):
    """Чтение Excel файла с обработкой различных кодировок."""
    try:
        # Пробуем прочитать файл
        df = pd.read_excel(file_path)
        
        # Проверяем необходимые столбцы
        required_columns = ["Symbol", "Name", "Category", "Price", "MarketCap", "ID"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            log_and_print(f"[ERROR] Отсутствуют столбцы: {', '.join(missing_columns)}", "error")
            return None
            
        # Приводим названия столбцов к единому виду
        column_mapping = {
            'Symbol': 'Symbol',
            'Name': 'Name',
            'Category': 'Category',
            'Price': 'Price',
            'MarketCap': 'MarketCap',
            'ID': 'id'  # Переименовываем ID в id для совместимости с остальным кодом
        }
        df = df.rename(columns=lambda x: column_mapping.get(x, x))
        
        # Убеждаемся, что id целое число
        df['id'] = df['id'].astype(int)
        
        log_and_print(f"[INFO] Загружен Excel файл: {len(df)} строк")
        log_and_print(f"[INFO] Столбцы: {df.columns.tolist()}")
        
        return df
        
    except Exception as e:
        log_and_print(f"[ERROR] Ошибка при чтении файла: {str(e)}", "error")
        return None


def save_to_excel(df, filename):
    """Безопасное сохранение в Excel с обработкой ошибок доступа."""
    try:
        # Форматируем данные перед сохранением
        df['ID'] = pd.to_numeric(df['ID'], errors='coerce').fillna(0).astype(int)  # ID как целое число
        df['Symbol'] = df['Symbol'].astype(str)  # Symbol как текст
        
        # Выводим данные перед форматированием для отладки
        log_and_print(f"[DEBUG] Типы данных перед форматированием: {df.dtypes}", "debug")
        log_and_print(f"[DEBUG] Первые 5 записей до форматирования: {df.head()}", "debug")
        
        # Удаляем строки, где все значения None или NaN
        df = df.dropna(how='all')
        
        # Выводим данные после обработки для отладки
        log_and_print(f"[DEBUG] Данные после обработки: {df.head()}", "debug")
        
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
        log_and_print(f"[DEBUG] Данные после чтения файла: {saved_df.head()}", "debug")
        
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


async def get_valid_tokens(df, session, count=None):
    """Получение валидных токенов из датафрейма."""
    try:
        # Проверяем наличие столбца id
        if 'id' not in df.columns:
            log_and_print("[ERROR] В файле отсутствует столбец 'id'", "error")
            return []
        
        # Создаем словарь для хранения уникальных токенов по ID
        unique_tokens = {}
        
        # Берем все токены из датафрейма
        for _, row in df.iterrows():
            token_id = int(row['id'])
            if token_id not in unique_tokens:
                unique_tokens[token_id] = {
                    'id': token_id,
                    'Symbol': str(row['Symbol'])
                }
            else:
                log_and_print(f"[WARNING] Найден дубликат ID {token_id} для токена {row['Symbol']}", "warning")
        
        # Преобразуем словарь в список
        tokens = list(unique_tokens.values())
            
        log_and_print(f"[DEBUG] Загружено {len(tokens)} уникальных токенов", "debug")
        log_and_print(f"[DEBUG] Пример токена: {tokens[0]}", "debug")
        
        if count:
            # Если нужно определенное количество, выбираем случайные
            selected_tokens = random.sample(tokens, min(count, len(tokens)))
            log_and_print(f"[DEBUG] Выбрано {len(selected_tokens)} случайных токенов", "debug")
            for token in selected_tokens:
                log_and_print(f"[DEBUG] Выбран токен: {token}", "debug")
            return selected_tokens
        
        return tokens
        
    except Exception as e:
        log_and_print(f"Ошибка при получении токенов: {str(e)}", "error")
        return []


async def fetch_data(session, token_id, start_date, end_date):
    """Получение данных по токену."""
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
    params = {
        "id": token_id,
        "convert": "USD",
        "time_start": start_date,
        "time_end": end_date,
        "interval": "1d"  # Получаем данные с интервалом в 1 день
    }
    
    log_and_print(f"Отправка запроса к API для токена {token_id}:", "debug")
    log_and_print(f"URL: {url}", "debug")
    log_and_print(f"Параметры: {params}", "debug")
    
    for attempt in range(3):
        try:
            await rate_limiter.wait()
            async with session.get(url, params=params, headers=HEADERS) as response:
                response_text = await response.text()
                log_and_print(f"Статус ответа: {response.status}", "debug")
                
                if response.status == 429:
                    log_and_print("Превышен лимит запросов, ожидание 66 секунд", "warning")
                    await asyncio.sleep(66)
                    continue
                
                if response.status == 200:
                    try:
                        data = json.loads(response_text)
                        if "data" in data:
                            if "quotes" in data["data"]:
                                quotes = data["data"]["quotes"]
                                if quotes:
                                    # Берем последнюю котировку из списка
                                    quote = quotes[-1]
                                    quote_data = quote.get("quote", {}).get("USD", {})
                                    
                                    price = quote_data.get("price")
                                    market_cap = quote_data.get("market_cap")
                                    
                                    # Выводим полученные данные для отладки
                                    log_and_print(f"Полученные данные для токена {token_id}:", "debug")
                                    log_and_print(f"Price: {price}", "debug")
                                    log_and_print(f"Market Cap: {market_cap}", "debug")
                                    
                                    # Проверяем валидность данных
                                    if price is not None and price > 0:
                                        if market_cap is None or market_cap == 0:
                                            log_and_print(f"[WARNING] Для токена {token_id} есть цена {price}, но нет маркет капа", "warning")
                                            return None
                                        
                                        # Данные возвращаем как числа, а не строки
                                        return {
                                            "data": {
                                                "quotes": [{
                                                    "quote": {
                                                        "USD": {
                                                            "price": float(price),
                                                            "market_cap": float(market_cap)
                                                        }
                                                    }
                                                }]
                                            }
                                        }
                                    else:
                                        log_and_print(f"Некорректные данные для токена {token_id} (price: {price}, market_cap: {market_cap})", "warning")
                                        return None
                                else:
                                    log_and_print(f"Нет котировок для токена {token_id} в указанный период", "warning")
                                    return None
                            else:
                                log_and_print(f"Нет поля 'quotes' в ответе API для токена {token_id}", "warning")
                                return None
                        else:
                            log_and_print(f"Нет поля 'data' в ответе API для токена {token_id}", "warning")
                            return None
                    except json.JSONDecodeError:
                        log_and_print(f"Ошибка декодирования JSON для токена {token_id}", "error")
                        return None
                else:
                    log_and_print(f"Ошибка API {response.status} для токена {token_id}: {response_text}", "error")
                    return None
                    
        except Exception as e:
            log_and_print(f"Ошибка при получении данных для токена {token_id}: {str(e)}", "error")
            if attempt < 2:
                await asyncio.sleep(5)
                continue
            return None
    
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


async def process_tokens_with_endpoint(tokens, start_date, end_date, df=None, session=None, is_test=False):
    """Обработка токенов и получение исторических данных."""
    results = []
    error_tokens = []
    remaining_tokens = tokens.copy()
    
    async with aiohttp.ClientSession() as local_session:
        session = session or local_session
        
        while len(results) < len(tokens) and (not is_test or len(results) < 5):
            if not remaining_tokens and is_test and df is not None:
                # Если это тестовый запрос и у нас закончились токены, берем новые
                new_tokens = await get_valid_tokens(df, session, count=1)
                if new_tokens:
                    remaining_tokens.extend(new_tokens)
                    log_and_print(f"Добавлен новый случайный токен: {new_tokens[0]['Symbol']}", "info")
                else:
                    break
            
            if not remaining_tokens:
                break
                
            token = remaining_tokens.pop(0)
            try:
                log_and_print(f"[DEBUG] Обработка токена: {token}", "debug")
                log_and_print(f"Получение данных для токена {token['Symbol']} (ID: {token['id']})", "info")
                
                # Получаем данные
                response = await fetch_data(session, token['id'], start_date, end_date)
                
                if response and isinstance(response, dict):
                    quotes = response['data'].get('quotes', [])
                    
                    if quotes and len(quotes) > 0:
                        quote = quotes[0]  # Берем первую котировку
                        usd_data = quote.get('quote', {}).get('USD', {})
                        
                        price = usd_data.get('price')
                        market_cap = usd_data.get('market_cap')
                        
                        # Проверяем наличие данных
                        if price is not None and market_cap is not None and float(market_cap) > 0:
                            # Сохраняем числовые значения
                            result = {
                                'ID': token['id'],
                                'Symbol': token['Symbol'],
                                'Price (USD)': price,  # Числовое значение
                                'Market Cap (USD)': market_cap  # Числовое значение
                            }
                            
                            results.append(result)
                            log_and_print(f"Успешно получены данные для {token['Symbol']}", "info")
                        else:
                            log_and_print(f"Нет корректных данных для {token['Symbol']}", "warning")
                            # Добавляем токен с пустыми данными
                            error_tokens.append({
                                'ID': token['id'],
                                'Symbol': token['Symbol'],
                                'Price (USD)': None,
                                'Market Cap (USD)': None
                            })
                    else:
                        log_and_print(f"Нет котировок для {token['Symbol']}", "warning")
                        # Добавляем токен с пустыми данными
                        error_tokens.append({
                            'ID': token['id'],
                            'Symbol': token['Symbol'],
                            'Price (USD)': None,
                            'Market Cap (USD)': None
                        })
                else:
                    log_and_print(f"Неверный формат данных для {token['Symbol']}", "error")
                    # Добавляем токен с пустыми данными
                    error_tokens.append({
                        'ID': token['id'],
                        'Symbol': token['Symbol'],
                        'Price (USD)': None,
                        'Market Cap (USD)': None
                    })
                
            except Exception as e:
                log_and_print(f"Ошибка при обработке токена {token['Symbol']}: {str(e)}", "error")
                # Добавляем токен с пустыми данными
                error_tokens.append({
                    'ID': token['id'],
                    'Symbol': token['Symbol'],
                    'Price (USD)': None,
                    'Market Cap (USD)': None
                })
                continue
            
            await asyncio.sleep(1)  # Небольшая пауза между токенами
    
    # Выводим итоговые результаты
    log_and_print(f"[DEBUG] Количество обработанных токенов: {len(results)}", "info")
    
    return results, error_tokens


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


async def main():
    """Главная функция с улучшенной обработкой ошибок."""
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

        # Создаем клиентскую сессию с таймаутом
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(limit=10, force_close=True)
        
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            # Сначала спрашиваем про тестовый запрос
            operation_type = input("Выполнить тестовый запрос? (да/нет): ").strip().lower()
            while operation_type not in ['да', 'нет']:
                log_and_print("[ERROR] Пожалуйста, введите 'да' или 'нет'", "error")
                operation_type = input("Выполнить тестовый запрос? (да/нет): ").strip().lower()

            if operation_type == 'да':
                try:
                    log_and_print("[INFO] Выбор случайных токенов для тестового запроса...")
                    test_tokens = await get_valid_tokens(df, session, count=5)
                    
                    if not test_tokens:
                        log_and_print("[ERROR] Не удалось получить токены для тестового запроса", "error")
                        return
                    
                    log_and_print(f"[INFO] Выбрано {len(test_tokens)} токенов для тестового запроса")
                    
                    # Запрашиваем даты для тестового запроса
                    while True:
                        start_date_str = input("Введите начальную дату для тестового запроса (YYYY-MM-DD): ").strip()
                        end_date_str = input("Введите конечную дату для тестового запроса (YYYY-MM-DD): ").strip()
                        
                        start_date = format_date_for_api(start_date_str)
                        end_date = format_date_for_api(end_date_str)
                        
                        if start_date and end_date:
                            break
                        log_and_print("[ERROR] Пожалуйста, введите даты в правильном формате", "error")

                    # Получение данных для тестовых токенов с возможностью замены битых токенов
                    test_results, test_errors = await process_tokens_with_endpoint(
                        test_tokens, 
                        start_date[0], 
                        end_date[1],
                        df=df,
                        session=session,
                        is_test=True
                    )
                    
                    # Сохраняем результаты
                    if test_results:
                        # Формируем имя файла с текущей датой и временем
                        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
                        output_file = os.path.join(CONFIG["output_folder"], f"result_test_{current_time}.xlsx")
                        df_results = pd.DataFrame(test_results)
                        
                        # Выводим данные для проверки
                        log_and_print("[DEBUG] Данные перед сохранением:", "debug")
                        for result in test_results:
                            log_and_print(f"[DEBUG] {result}", "debug")
                        
                        # Сохраняем в правильном порядке столбцов
                        df_results = df_results[['ID', 'Symbol', 'Price (USD)', 'Market Cap (USD)']]
                        
                        if not save_to_excel(df_results, output_file):
                            return
                        log_and_print(f"[INFO] Сохранено {len(test_results)} тестовых результатов")
                    else:
                        log_and_print("[ERROR] Не удалось получить валидные данные ни для одного токена", "error")
                        return

                except Exception as e:
                    log_and_print(f"[ERROR] Ошибка при выполнении тестового запроса: {str(e)}", "error")
                    return

            # После тестового запроса спрашиваем про основной
            proceed = input("Выполнить основной запрос? (да/нет): ").strip().lower()
            if proceed != 'да':
                return

            # Запрашиваем даты для основного запроса
            while True:
                start_date_str = input("Введите начальную дату для основного запроса (YYYY-MM-DD): ").strip()
                end_date_str = input("Введите конечную дату для основного запроса (YYYY-MM-DD): ").strip()
                
                start_date = format_date_for_api(start_date_str)
                end_date = format_date_for_api(end_date_str)
                
                if start_date and end_date:
                    break
                log_and_print("[ERROR] Пожалуйста, введите даты в правильном формате", "error")

            # Основной запрос для всех токенов
            try:
                log_and_print("[INFO] Получение всех токенов для основного запроса...")
                all_tokens = await get_valid_tokens(df, session)
                
                if not all_tokens:
                    log_and_print("[ERROR] Не удалось получить токены", "error")
                    return
                
                log_and_print(f"[INFO] Найдено {len(all_tokens)} токенов")
                
                # Получение данных
                results, errors = await process_tokens_with_endpoint(all_tokens, start_date[0], end_date[1])
                
                # Объединяем успешные результаты и ошибки в один файл
                all_results = []
                
                # Добавляем успешные результаты
                if results:
                    all_results.extend(results)
                
                # Добавляем токены с ошибками
                if errors:
                    all_results.extend(errors)
                
                # Сохраняем все результаты
                if all_results:
                    output_file = os.path.join(CONFIG["output_folder"], 
                                           f"result_{start_date_str}_{end_date_str}.xlsx")
                    df_results = pd.DataFrame(all_results)
                    
                    # Выводим данные для проверки
                    log_and_print("[DEBUG] Данные перед сохранением:", "debug")
                    for result in all_results[:5]:  # Показываем первые 5 результатов
                        log_and_print(f"[DEBUG] {result}", "debug")
                    
                    # Сохраняем в правильном порядке столбцов
                    df_results = df_results[['ID', 'Symbol', 'Price (USD)', 'Market Cap (USD)']]
                    
                    if not save_to_excel(df_results, output_file):
                        return
                    log_and_print(f"[INFO] Сохранено {len(all_results)} результатов")
                else:
                    log_and_print("[ERROR] Запрос не вернул данных", "error")
                    return

            except Exception as e:
                log_and_print(f"[ERROR] Ошибка при выполнении основного запроса: {str(e)}", "error")
                return

    except asyncio.CancelledError:
        log_and_print("[WARNING] Программа была прервана пользователем", "warning")
    except Exception as e:
        log_and_print(f"[ERROR] Критическая ошибка: {str(e)}", "error")
        import traceback
        log_and_print(f"[DEBUG] Traceback: {traceback.format_exc()}", "error")
    finally:
        if 'session' in locals():
            await session.close()


if __name__ == "__main__":
    asyncio.run(main())

