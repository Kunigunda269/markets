import asyncio
import os
import time
import json
import logging
import requests
import pandas as pd
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Используем предоставленный API ключ
API_KEY = "123"
BASE_URL = "https://pro-api.coinmarketcap.com/v1"
HEADERS = {
    "X-CMC_PRO_API_KEY": API_KEY,
    "Accept": "application/json"
}

CACHE_FILE = "cache.json"
OUTPUT_FILE = r"C:\Users\Main\Pitonio\crypto_etf\category_downloader.xlsx"

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# Функция для загрузки кэша
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    return {}


# Функция для сохранения кэша
def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as file:
        json.dump(cache, file, ensure_ascii=False, indent=4)


# Функция для выполнения запроса к API
def make_request(endpoint, params=None):
    url = BASE_URL + endpoint
    headers = {
        "X-CMC_PRO_API_KEY": API_KEY,
        "Accept": "application/json"
    }

    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, params=params)
            response_data = response.json()
            
            if response.status_code == 200:
                return response_data
            elif response.status_code == 429:
                logging.warning("Превышен лимит запросов! Ожидание 66 секунд...")
                time.sleep(66)  # Ожидание 66 секунд при превышении лимита
                continue
            else:
                logging.error(f"Ошибка {response.status_code}: {response_data}")
                return None
        except requests.RequestException as e:
            logging.error(f"Ошибка запроса: {e}")
        time.sleep(5)
    return None


# Функция для получения списка категорий
def fetch_categories():
    logging.info("Получение списка категорий...")
    endpoint = "/cryptocurrency/categories"
    data = make_request(endpoint)
    
    if data and 'data' in data:
        return [(cat["id"], cat["name"]) for cat in data.get("data", [])]
    else:
        logging.error("Не удалось получить список категорий")
        return []


# Функция для получения токенов по категории
def fetch_category_tokens(category_id):
    logging.info(f"Загрузка токенов для категории ID {category_id}...")
    endpoint = "/cryptocurrency/category"
    params = {"id": category_id}
    data = make_request(endpoint, params)
    
    if data and 'data' in data:
        unique_tokens = {}
        for token in data["data"].get("coins", []):
            symbol = token["symbol"]
            if symbol not in unique_tokens:
                unique_tokens[symbol] = {
                    "Symbol": symbol,
                    "Name": token["name"],
                    "Category": data["data"]["title"],
                    "Price": token.get("quote", {}).get("USD", {}).get("price", "N/A"),
                    "MarketCap": token.get("quote", {}).get("USD", {}).get("market_cap", "N/A")
                }
        
        return list(unique_tokens.values())
    return []


# Главная функция
def main():
    if input("Начать загрузку данных? (y/n): ").strip().lower() != "y":
        logging.info("Выход из программы.")
        return

    cache = load_cache()
    categories = fetch_categories()
    all_tokens = []

    for category_id, category_name in categories:
        if category_id in cache:
            logging.info(f"Пропускаем категорию {category_name} (уже в кэше)")
            all_tokens.extend(cache[category_id])
            continue

        tokens = fetch_category_tokens(category_id)
        if tokens:
            cache[category_id] = tokens
            all_tokens.extend(tokens)
            save_cache(cache)  # Сохраняем в кэш
            logging.info(f"Данные по категории {category_name} сохранены.")

        time.sleep(66)  # Ожидание 66 секунд между запросами категорий

    # Сохранение в Excel
    df = pd.DataFrame(all_tokens)
    
    # Сортировка по категории и символу для удобства
    df = df.sort_values(['Category', 'Symbol'])
    
    # Сброс индекса после сортировки
    df = df.reset_index(drop=True)
    
    df.to_excel(OUTPUT_FILE, index=False)
    logging.info(f"Данные успешно сохранены в {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
