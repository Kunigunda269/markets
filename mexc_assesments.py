import requests
import logging
import json
import time
from datetime import datetime
from pathlib import Path
from tqdm import tqdm
import hashlib
import os
from bs4 import BeautifulSoup
import random
import sys
from openpyxl import Workbook

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('mexc_api.log'),
        logging.StreamHandler()
    ]
)

class MEXCAPI:
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = 'https://api.mexc.com'
        self.cache_dir = Path('cache')
        self.cache_dir.mkdir(exist_ok=True)
        
    def _get_cache_path(self, endpoint):
        return self.cache_dir / f"{hashlib.md5(endpoint.encode()).hexdigest()}.json"
        
    def _get_cached_data(self, endpoint):
        cache_path = self._get_cache_path(endpoint)
        if cache_path.exists():
            with open(cache_path, 'r') as f:
                return json.load(f)
        return None
        
    def _save_to_cache(self, endpoint, data):
        cache_path = self._get_cache_path(endpoint)
        with open(cache_path, 'w') as f:
            json.dump(data, f)
            
    def get_exchange_info(self):
        endpoint = '/api/v3/exchangeInfo'
        cached_data = self._get_cached_data(endpoint)
        
        if cached_data:
            logging.info("Используем кэшированные данные")
            return cached_data
            
        try:
            response = requests.get(f"{self.base_url}{endpoint}")
            response.raise_for_status()
            data = response.json()
            self._save_to_cache(endpoint, data)
            return data
        except requests.exceptions.RequestException as e:
            logging.error(f"Ошибка при получении данных: {e}")
            return None
            
    def get_24hr_ticker(self):
        endpoint = '/api/v3/ticker/24hr'
        cached_data = self._get_cached_data(endpoint)
        
        if cached_data:
            logging.info("Используем кэшированные данные")
            return cached_data
            
        try:
            response = requests.get(f"{self.base_url}{endpoint}")
            response.raise_for_status()
            data = response.json()
            self._save_to_cache(endpoint, data)
            return data
        except requests.exceptions.RequestException as e:
            logging.error(f"Ошибка при получении данных: {e}")
            return None

    def is_assessment_token(self, symbol):
        """
        Проверяет, является ли токен assessment по наличию блока Countdown на странице пары.
        Кэширует результат в отдельный файл.
        """
        safe_symbol = symbol.replace('/', '_')
        cache_path = self.cache_dir / f"assessment_{safe_symbol}.json"
        if cache_path.exists():
            with open(cache_path, 'r') as f:
                return json.load(f).get('assessment', False)
        url = f"https://www.mexc.com/ru-RU/exchange/{safe_symbol}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            found = soup.find(string=lambda t: t and 'Countdown' in t)
            assessment = found is not None
            with open(cache_path, 'w') as f:
                json.dump({'assessment': assessment}, f)
            return assessment
        except Exception as e:
            logging.error(f"Ошибка при проверке assessment для {symbol}: {e}")
            return False

    def filter_usdt_low_volume(self, exchange_info, ticker_24hr, min_volume=500000):
        """
        Возвращает список символов USDT-пар с объёмом торгов за 24ч меньше min_volume.
        """
        usdt_symbols = [s['symbol'] for s in exchange_info.get('symbols', []) if s['quoteAsset'] == 'USDT']
        low_volume_symbols = []
        ticker_map = {t['symbol']: t for t in ticker_24hr}
        for symbol in usdt_symbols:
            ticker = ticker_map.get(symbol)
            if ticker:
                try:
                    volume = float(ticker.get('quoteVolume', 0))
                    if volume < min_volume:
                        low_volume_symbols.append(symbol.replace('USDT', '/USDT'))
                except Exception as e:
                    logging.warning(f"Ошибка при обработке объёма для {symbol}: {e}")
        return low_volume_symbols

    def find_assessment_tokens(self, symbols, delay_min=1, delay_max=5):
        """
        Проверяет список символов на assessment-статус с прогресс-баром и рандомной задержкой.
        """
        assessment_tokens = []
        for symbol in tqdm(symbols, desc='Проверка assessment'):
            if self.is_assessment_token(symbol):
                assessment_tokens.append(symbol)
            time.sleep(random.uniform(delay_min, delay_max))  # рандомная задержка
        return assessment_tokens

def save_to_excel(tokens, output_dir):
    today = datetime.now().strftime('%d-%m-%Y')
    suffix = '_False' if not tokens else ''
    filename = f"mexc assesments {today}{suffix}.xlsx"
    filepath = f"{output_dir}/{filename}"
    wb = Workbook()
    ws = wb.active
    ws.append(["Тикер", "Ссылка на биржу"])
    for token in tokens:
        safe_token = token.replace('/', '_')
        url = f"@https://www.mexc.com/exchange/{safe_token}"
        ws.append([token, url])
    wb.save(filepath)
    logging.info(f"Результаты сохранены в {filepath}")

def main():
    api_key = "123"
    api_secret = "123"
    
    mexc = MEXCAPI(api_key, api_secret)
    
    logging.info("Получаем информацию о бирже...")
    exchange_info = mexc.get_exchange_info()
    ticker_24hr = mexc.get_24hr_ticker()
    
    if exchange_info and ticker_24hr:
        symbols = mexc.filter_usdt_low_volume(exchange_info, ticker_24hr, min_volume=500000)
        logging.info(f"USDT-пар с объёмом < 500000$: {len(symbols)}")
        # --- Тестовый режим ---
        do_test = input('Выполнить тест? (y/n): ').strip().lower()
        if do_test == 'y':
            test_symbols = random.sample(symbols, min(5, len(symbols)))
            logging.info(f"Тестовый режим: выбрано токенов: {test_symbols}")
            assessment_tokens = mexc.find_assessment_tokens(test_symbols)
            logging.info(f"Assessment-токенов найдено: {len(assessment_tokens)} (тест)")
            for token in assessment_tokens:
                logging.info(f"Assessment: {token}")
            save_to_excel(assessment_tokens, r"C:/Users/Илья/PycharmProjects/crypto etf")
        # --- Основной режим ---
        do_main = input('Выполнить основной запрос? (y/n): ').strip().lower()
        if do_main == 'y':
            assessment_tokens = mexc.find_assessment_tokens(symbols)
            logging.info(f"Assessment-токенов найдено: {len(assessment_tokens)} (основной)")
            for token in assessment_tokens:
                logging.info(f"Assessment: {token}")
            save_to_excel(assessment_tokens, r"C:/Users/Илья/PycharmProjects/crypto etf")

    logging.info("Получаем информацию о бирже...")
    exchange_info = mexc.get_exchange_info()
    
    if exchange_info:
        logging.info(f"Получено {len(exchange_info.get('symbols', []))} торговых пар")
        
        # Выводим информацию о первых 10 парах
        for symbol in exchange_info.get('symbols', [])[:10]:
            logging.info(f"Пара: {symbol['symbol']}")
            
    logging.info("Получаем 24-часовую статистику...")
    ticker_24hr = mexc.get_24hr_ticker()
    
    if ticker_24hr:
        logging.info(f"Получена статистика для {len(ticker_24hr)} пар")
        
        # Выводим информацию о первых 10 парах
        for ticker in ticker_24hr[:10]:
            logging.info(f"Пара: {ticker['symbol']}, Изменение цены: {ticker['priceChangePercent']}%")

if __name__ == "__main__":
    main()
