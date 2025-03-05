import asyncio
import aiohttp
import pandas as pd
import logging
import os
import sys
import time

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# === Конфигурация ===
API_KEY = "123"
HEADERS = {"X-CMC_PRO_API_KEY": API_KEY}
BASE_URL_HISTORICAL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"

CONFIG = {
    "max_requests_per_minute": 30,              # Лимит запросов в минуту
    "batch_size": 50,                           # Количество токенов в пакете
    "input_file": r"C:\Users\Main\Pitonio\crypto_etf\category_downloader.xlsx",  # Используйте crypto_etf вместо "crypto etf"
    "output_folder": r"C:\Users\Main\Pitonio\crypto_etf",
}

# Проверка существования файла
if not os.path.exists(CONFIG["input_file"]):
    print(f"ОШИБКА: Файл {CONFIG['input_file']} не найден!")
    print("Убедитесь, что файл category_downloader.xlsx находится в той же папке, что и скрипт.")
    sys.exit(1)

# === Логирование ===
logging.basicConfig(
    filename="crypto_combined.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def log_and_print(message, level="info"):
    """Логирование и вывод сообщений."""
    print(f"[{level.upper()}] {message}")
    getattr(logging, level)(message)


class RateLimiter:
    """Контролирует количество запросов в минуту."""
    def __init__(self, max_requests_per_minute):
        self.interval = 60 / max_requests_per_minute
        self.last_call = time.time()

    async def wait(self):
        now = time.time()
        elapsed = now - self.last_call
        if elapsed < self.interval:
            await asyncio.sleep(self.interval - elapsed)
        self.last_call = time.time()


rate_limiter = RateLimiter(CONFIG["max_requests_per_minute"])


def price_change_percentage(open_price, close_price):
    """Вычисление процентного изменения цены."""
    if open_price == 0:
        return 0
    return ((close_price - open_price) / open_price) * 100


async def fetch_historical_data(session, crypto_id, time_start, time_end):
    """Получение исторических данных"""
    url = BASE_URL_HISTORICAL
    params = {
        "id": crypto_id,
        "time_start": time_start,
        "time_end": time_end,
        "interval": "daily",
        "convert": "USD"
    }

    try:
        async with session.get(url, headers=HEADERS, params=params) as response:
            if response.status == 200:
                data = await response.json()
                quotes = data.get('data', {}).get('quotes', [])
                
                if quotes:
                    start_data = quotes[0]['quote']['USD']
                    end_data = quotes[-1]['quote']['USD']
                    
                    log_and_print("Данные за период:")
                    log_and_print(f"Цена начала: {start_data['price']:.8f} USD")
                    log_and_print(f"Капитализация начала: {start_data['market_cap']:.2f} USD")
                    log_and_print(f"Цена конца: {end_data['price']:.8f} USD")
                    log_and_print(f"Капитализация конца: {end_data['market_cap']:.2f} USD")
                    
                    return {
                        'start_price': start_data['price'],
                        'start_mcap': start_data['market_cap'],
                        'end_price': end_data['price'],
                        'end_mcap': end_data['market_cap']
                    }
                else:
                    log_and_print(f"Нет данных для ID: {crypto_id} в указанном диапазоне дат.", level="warning")
            elif response.status == 429:
                log_and_print(f"Превышен лимит запросов для ID: {crypto_id}. Ожидание 60 секунд...", level="error")
                await asyncio.sleep(66)
                return await fetch_historical_data(session, crypto_id, time_start, time_end)
            else:
                log_and_print(f"Ошибка HTTP {response.status} для ID: {crypto_id}", level="error")
    except Exception as e:
        log_and_print(f"Ошибка при получении данных для ID: {crypto_id}: {str(e)}", level="error")
    return None


async def fetch_batch_data(session, tokens, time_start, time_end, processed_tokens):
    """
    Обработка данных пакета токенов с фокусом на цене закрытия и капитализации.
    """
    log_and_print(f"[INFO] Обработка пакета из {len(tokens)} токенов...")
    results = []
    for token in tokens:
        token_id = token["Id"]
        log_and_print(f"[INFO] Проверяем ID: {token_id} | Symbol: {token['Symbol']}")
        if token_id in processed_tokens:
            # Пропускаем запрос для уже обработанного ID
            log_and_print(f"[INFO] Данные для ID {token_id} взяты из кэша.")
            results.append(processed_tokens[token_id])
        else:
            # Выполняем запрос для нового токена
            log_and_print(f"[INFO] Запрос данных для токена {token_id}...")
            data = await fetch_historical_data(session, token_id, time_start, time_end)
            result = {
                "ID": token_id,
                "Symbol": token["Symbol"],
                "Price (USD)": data['end_price'],
                "Market Cap (USD)": data['end_mcap']
            }
            results.append(result)
            processed_tokens[token_id] = result  # Сохраняем в кэш
            log_and_print(f"[INFO] Запрос успешно завершён для {token_id}.")
    return results


async def process_tokens(input_file, output_folder, time_start, time_end):
    """
    Обработка токенов из файла Excel с сохранением результатов только для цены и капитализации.
    """
    log_and_print("[INFO] Чтение данных из входного файла...")
    data = pd.read_excel(input_file)
    data = data.dropna(subset=["Id", "Symbol"])
    data["Id"] = data["Id"].astype(int)
    tokens = data[["Id", "Symbol"]].to_dict(orient="records")
    log_and_print(f"[INFO] Успешно загружено {len(tokens)} токенов для обработки.")

    processed_tokens = {}
    all_results = []

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(tokens), CONFIG["batch_size"]):
            batch = tokens[i:i + CONFIG["batch_size"]]
            log_and_print(f"[INFO] Начинается обработка пакета {i // CONFIG['batch_size'] + 1}...")
            batch_results = await fetch_batch_data(session, batch, time_start, time_end, processed_tokens)
            all_results.extend(batch_results)
            log_and_print(f"[INFO] Обработка пакета {i // CONFIG['batch_size'] + 1} завершена.")

    # Сохранение всех результатов
    output_file = os.path.join(output_folder, f"result_{time_start[:10]}_to_{time_end[:10]}.xlsx")
    pd.DataFrame(all_results).to_excel(output_file, index=False)
    log_and_print(f"[INFO] Результаты успешно сохранены в файл: {output_file}")


async def main():
    """Главная функция."""
    log_and_print("[INFO] Начало работы программы...")
    
    test_id = int(input("Введите ID токена для тестового запроса: ").strip())
    test_start = input("Введите начальную дату для теста (YYYY-MM-DD): ").strip() + "T00:00:00Z"
    test_end = input("Введите конечную дату для теста (YYYY-MM-DD): ").strip() + "T23:59:59Z"

    async with aiohttp.ClientSession() as session:
        log_and_print("[INFO] Выполняем тестовый запрос...")
        await fetch_historical_data(session, test_id, test_start, test_end)

    log_and_print("[INFO] Начало обработки основного списка токенов...")
    process_start = input("Введите начальную дату для обработки (YYYY-MM-DD): ").strip() + "T00:00:00Z"
    process_end = input("Введите конечную дату для обработки (YYYY-MM-DD): ").strip() + "T23:59:59Z"
    await process_tokens(CONFIG["input_file"], CONFIG["output_folder"], process_start, process_end)


if __name__ == "__main__":
    log_and_print("[INFO] Запуск основного процесса.")
    asyncio.run(main())

