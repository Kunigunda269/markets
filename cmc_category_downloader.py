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

API_KEY = "831812bd-1186-43d4-b0d3-b71f0d61074e"
BASE_URL = "https://pro-api.coinmarketcap.com/v1"
HEADERS = {
    "X-CMC_PRO_API_KEY": API_KEY,
    "Accept": "application/json"
}

CACHE_FILE = "cache.json"
OUTPUT_FILE = r"C:\Users\Main\Pitonio\crypto_etf\category_downloader.xlsx"
BASE_URL = "https://pro-api.coinmarketcap.com/v1/"

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
    headers = {"X-CMC_PRO_API_KEY": API_KEY}

    for attempt in range(3):  # 3 попытки в случае ошибки
        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                logging.warning("Превышен лимит запросов! Ожидание 66 секунд...")
                time.sleep(66)
            else:
                logging.error(f"Ошибка {response.status_code}: {response.text}")
        except requests.RequestException as e:
            logging.error(f"Ошибка запроса: {e}")
        time.sleep(5)  # Ожидание перед повторной попыткой
    return None


# Функция для получения списка категорий
def fetch_categories():
    logging.info("Получение списка категорий...")
    data = make_request("cryptocurrency/categories")
    if data:
        return [(cat["id"], cat["name"]) for cat in data.get("data", [])]
    return []


# Функция для получения токенов по категории
def fetch_category_tokens(category_id):
    logging.info(f"Загрузка токенов для категории ID {category_id}...")
    params = {"id": category_id}
    data = make_request("cryptocurrency/category", params)
    if data:
        return [
            {
                "Id": token["id"],
                "Name": token["name"],
                "Symbol": token["symbol"],
                "Category": data["data"]["title"],
                "Price": token.get("quote", {}).get("USD", {}).get("price", "N/A"),
                "MarketCap": token.get("quote", {}).get("USD", {}).get("market_cap", "N/A"),
                "Profile_URL": f"https://coinmarketcap.com/currencies/{token['slug']}/"
            }
            for token in data["data"].get("coins", [])
        ]
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

        logging.info("Ожидание 66 секунд перед следующим запросом...")
        time.sleep(66)

    # Сохранение в Excel
    df = pd.DataFrame(all_tokens)
    df.to_excel(OUTPUT_FILE, index=False)
    logging.info(f"Данные успешно сохранены в {OUTPUT_FILE}")


if __name__ == "__main__":
    main()