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
    "input_file": r"C:\\Users\\User\\OneDrive\\Рабочий стол\\category_tokens_details_2.xlsx",
    "output_folder": r"C:\\Users\\User\\OneDrive\\Рабочий стол",
}

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


async def fetch_historical_data(session, query_param, query_value, time_start, time_end):
    """
    Получение исторических данных (цена закрытия и капитализация) для одного токена.
    """
    log_and_print(f"[INFO] Начат запрос данных для {query_param}={query_value}")
    params = {
        query_param: query_value,
        "time_start": time_start,
        "time_end": time_end,
        "interval": "daily",
        "convert": "USD",
    }
    try:
        async with session.get(BASE_URL_HISTORICAL, headers=HEADERS, params=params) as response:
            if response.status == 200:
                data = await response.json()
                quotes = data.get("data", {}).get("quotes", [])
                if quotes:
                    usd_data = quotes[0].get("quote", {}).get("USD", {})
                    log_and_print(f"[INFO] Данные успешно получены для {query_param}={query_value}")
                    return {
                        "price": usd_data.get("price", 0),
                        "market_cap": usd_data.get("market_cap", 0),
                    }
                else:
                    log_and_print(f"[WARNING] Нет данных для {query_value} ({query_param})", "warning")
            elif response.status == 429:
                log_and_print(f"[ERROR] Лимит запросов превышен для {query_param}={query_value}. Ожидание...")
                await asyncio.sleep(60)  # Ожидание перед повтором
                return await fetch_historical_data(session, query_param, query_value, time_start, time_end)
            else:
                log_and_print(f"[ERROR] HTTP {response.status} для {query_param}={query_value}", "error")
    except Exception as e:
        log_and_print(f"[ERROR] Ошибка при запросе {query_param}={query_value}: {e}", "error")
    return {}


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
            data = await fetch_historical_data(session, "id", token_id, time_start, time_end)
            result = {
                "ID": token_id,
                "Symbol": token["Symbol"],
                "Price (USD)": data.get("price", 0),
                "Market Cap": data.get("market_cap", 0),
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
        test_result = await fetch_historical_data(session, "id", test_id, test_start, test_end)
        log_and_print(f"[INFO] Тестовый запрос для ID {test_id}: Результаты: {test_result}")

    log_and_print("[INFO] Начало обработки основного списка токенов...")
    process_start = input("Введите начальную дату для обработки (YYYY-MM-DD): ").strip() + "T00:00:00Z"
    process_end = input("Введите конечную дату для обработки (YYYY-MM-DD): ").strip() + "T23:59:59Z"
    await process_tokens(CONFIG["input_file"], CONFIG["output_folder"], process_start, process_end)


if __name__ == "__main__":
    log_and_print("[INFO] Запуск основного процесса.")
    asyncio.run(main())


