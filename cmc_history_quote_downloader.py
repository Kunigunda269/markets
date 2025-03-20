import asyncio
import aiohttp
import pandas as pd
import logging
import os
import sys
import time
import numpy as np
from tqdm import tqdm

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# === Конфигурация ===
API_KEY = "123"
HEADERS = {"X-CMC_PRO_API_KEY": API_KEY}
BASE_URL_HISTORICAL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"

CONFIG = {
    "max_requests_per_minute": 30,  # Лимит запросов в минуту
    "batch_size": 50,  # Количество токенов в пакете
    "input_file": r"C:\Users\Main\Pitonio\crypto_etf\category_downloader_123.xlsx",
    # Используйте crypto_etf вместо "crypto etf"
    "output_folder": r"C:\Users\Main\Pitonio\crypto_etf",
}

# Проверка существования файла
if not os.path.exists(CONFIG["input_file"]):
    print(f"ОШИБКА: Файл {CONFIG['input_file']} не найден!")
    print("Убедитесь, что файл category_downloader_123.xlsx находится в той же папке, что и скрипт.")
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
                for _ in tqdm(range(66), desc="Ожидание восстановления лимита", unit="сек"):
                    await asyncio.sleep(1)
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

    batch_progress = tqdm(tokens, desc="Текущий пакет", unit="токен", leave=False)
    for token in batch_progress:
        token_id = token["id"]
        batch_progress.set_description(f"Обработка {token['symbol']}")

        if token_id in processed_tokens:
            # Используем кэшированные данные
            log_and_print(f"[CACHE] Используем кэшированные данные для {token['symbol']} (ID: {token_id})")
            results.append(processed_tokens[token_id])
            continue

        # Выполняем запрос для нового токена
        log_and_print(f"[INFO] Запрос данных для {token['symbol']} (ID: {token_id})...")
        data = await fetch_historical_data(session, token_id, time_start, time_end)

        if data is None:
            # Если данные не получены, создаем запись с нулевыми значениями
            result = {
                "ID": token_id,
                "Symbol": token["symbol"],
                "Price (USD)": 0,
                "Market Cap (USD)": 0,
                "Status": "No Data"
            }
        else:
            result = {
                "ID": token_id,
                "Symbol": token["symbol"],
                "Price (USD)": data['end_price'],
                "Market Cap (USD)": data['end_mcap'],
                "Status": "OK"
            }

        results.append(result)
        processed_tokens[token_id] = result  # Сохраняем в кэш
        log_and_print(f"[CACHE] Данные для {token['symbol']} (ID: {token_id}) сохранены в кэш")

        # Добавляем небольшую задержку между запросами
        await asyncio.sleep(0.5)

    batch_progress.close()
    return results


async def process_tokens(input_file, output_folder, time_start, time_end):
    """
    Обработка токенов из файла Excel с сохранением результатов только для цены и капитализации.
    """
    log_and_print("[INFO] Чтение данных из входного файла...")
    data = pd.read_excel(input_file)

    # Добавляем временный числовой ID на основе индекса
    data['Id'] = range(1, len(data) + 1)

    # Фильтрация и подготовка данных
    data = data.dropna(subset=['Symbol'])

    tokens = data[['Id', 'Symbol']].to_dict(orient="records")
    tokens = [{"id": t['Id'], "symbol": t['Symbol']} for t in tokens]

    # Остальной код без изменений
    total_tokens = len(tokens)
    log_and_print(f"[INFO] Успешно загружено {total_tokens} уникальных токенов для обработки.")

    processed_tokens = {}
    all_results = []

    async with aiohttp.ClientSession() as session:
        progress_bar = tqdm(total=total_tokens, desc="Обработка токенов", unit="токен")
        for i in range(0, total_tokens, CONFIG["batch_size"]):
            batch = tokens[i:i + CONFIG["batch_size"]]
            log_and_print(
                f"[INFO] Начинается обработка пакета {i // CONFIG['batch_size'] + 1} из {(total_tokens - 1) // CONFIG['batch_size'] + 1}...")
            batch_results = await fetch_batch_data(session, batch, time_start, time_end, processed_tokens)

            # Добавляем только уникальные результаты
            for result in batch_results:
                if not any(r["ID"] == result["ID"] and r["Symbol"] == result["Symbol"] for r in all_results):
                    all_results.append(result)

            # Обновляем прогресс бар
            progress_bar.update(len(batch))

            log_and_print(
                f"[INFO] Обработка пакета {i // CONFIG['batch_size'] + 1} завершена. В кэше {len(processed_tokens)} токенов.")

        progress_bar.close()

    # Создаем DataFrame и обрабатываем данные
    df = pd.DataFrame(all_results)

    # Дополнительная проверка на дубликаты по ID и Symbol
    df = df.drop_duplicates(subset=["ID", "Symbol"], keep="first")

    # Преобразуем числовые колонки в float64
    df["Price (USD)"] = pd.to_numeric(df["Price (USD)"], errors="coerce")
    df["Market Cap (USD)"] = pd.to_numeric(df["Market Cap (USD)"], errors="coerce")

    # Сортируем по Market Cap (по убыванию)
    df = df.sort_values(by="Market Cap (USD)", ascending=False)

    # Заменяем NaN на "N/A"
    df = df.replace({np.nan: "N/A"})

    # Форматируем числовые значения
    def format_number(x):
        if isinstance(x, (int, float)):
            if x >= 1_000_000_000:  # миллиарды
                return f"{x / 1_000_000_000:.2f}B"
            elif x >= 1_000_000:  # миллионы
                return f"{x / 1_000_000:.2f}M"
            elif x >= 1_000:  # тысячи
                return f"{x / 1_000:.2f}K"
            else:
                return f"{x:.2f}"
        return x

    # Применяем форматирование
    df["Market Cap (USD)"] = df["Market Cap (USD)"].apply(format_number)
    df["Price (USD)"] = df["Price (USD)"].apply(lambda x: format_number(x) if x != "N/A" else x)

    # Сохраняем результат
    output_file = os.path.join(output_folder, f"result_{time_start[:10]}_to_{time_end[:10]}.xlsx")

    # Создаем Excel writer
    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Results')

        # Получаем workbook и worksheet
        workbook = writer.book
        worksheet = writer.sheets['Results']

        # Форматы для ячеек
        header_format = workbook.add_format({
            'bold': True,
            'text_wrap': True,
            'valign': 'top',
            'bg_color': '#D9D9D9',
            'border': 1
        })

        # Применяем форматы к заголовкам
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)

        # Автоматическая ширина колонок
        for idx, col in enumerate(df.columns):
            series = df[col]
            max_len = max(
                series.astype(str).apply(len).max(),
                len(str(series.name))
            ) + 2
            worksheet.set_column(idx, idx, max_len)

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

