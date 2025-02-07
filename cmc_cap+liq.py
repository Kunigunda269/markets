import asyncio
import aiohttp
import pandas as pd
import logging
import os
import sys
import time
import plotly.graph_objects as go
import plotly.offline as pyo
from datetime import datetime, timedelta
from typing import Dict, List, Optional

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# === Конфигурация ===
API_KEY = "123"
HEADERS = {"X-CMC_PRO_API_KEY": API_KEY}
BASE_URL_METADATA = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/info"
BASE_URL_HISTORICAL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
OUTPUT_FOLDER = r"C:\Users\Main\Pitonio\crypto etf"

# === Логирование ===
logging.basicConfig(
    filename=os.path.join(OUTPUT_FOLDER, "crypto_combined.log"),
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


rate_limiter = RateLimiter(30)  # Adjusted for simplicity


async def fetch_token_metadata(session, symbol):
    """Получение метаданных токена."""
    url = BASE_URL_METADATA
    params = {"symbol": symbol}

    await rate_limiter.wait()
    async with session.get(url, headers=HEADERS, params=params) as response:
        if response.status == 200:
            data = await response.json()
            log_and_print(f"[DEBUG] Полный ответ API: {data}", "debug")

            # Проверяем структуру ответа
            if data.get('data') and symbol in data['data']:
                # Если data[symbol] - список, берем первый элемент
                token_info = data['data'][symbol][0] if isinstance(data['data'][symbol], list) else data['data'][symbol]

                # Выбираем первый доступный адрес контракта
                contract_address = 'N/A'
                if 'contract_address' in token_info:
                    contract_addresses = token_info['contract_address']
                    if isinstance(contract_addresses, list) and contract_addresses:
                        contract_address = contract_addresses[0].get('contract_address', 'N/A')

                return {
                    'id': token_info.get('id'),
                    'contract_address': contract_address
                }

        log_and_print(f"[ERROR] Не удалось получить метаданные для {symbol}", "error")
        return None


async def fetch_historical_data(session, token_id, start_date, end_date):
    """Получение исторических данных о торгах и маркет капе."""
    url = BASE_URL_HISTORICAL
    params = {
        "id": token_id,
        "time_start": start_date,
        "time_end": end_date,
        "interval": "daily",
        "convert": "USD"
    }
    await rate_limiter.wait()
    async with session.get(url, headers=HEADERS, params=params) as response:
        if response.status == 200:
            data = await response.json()
            quotes = data.get("data", {}).get("quotes", [])

            # Проверка наличия данных
            if not quotes:
                log_and_print("[WARNING] Нет данных в указанном диапазоне", "warning")

            return quotes
        else:
            log_and_print(f"[ERROR] Не удалось получить исторические данные: HTTP {response.status}", "error")

            # Получаем текст ошибки
            error_text = await response.text()
            log_and_print(f"[ERROR] Детали ошибки: {error_text}", "error")

            return []


def validate_and_adjust_dates(start_date_str, end_date_str):
    """
    Проверка и корректировка дат.
    Если указаны будущие даты, используем последние доступные данные.
    """
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        current_date = datetime.now()

        # Если даты в будущем, используем диапазон за последний месяц
        if start_date > current_date or end_date > current_date:
            log_and_print("[WARNING] Указаны будущие даты. Используем данные за последний месяц.", "warning")
            end_date = current_date
            start_date = end_date - timedelta(days=30)

        # Проверка, что начальная дата раньше конечной
        if start_date >= end_date:
            log_and_print("[WARNING] Начальная дата позже конечной. Корректируем.", "warning")
            start_date = end_date - timedelta(days=30)

        return (
            start_date.strftime("%Y-%m-%dT00:00:00Z"),
            end_date.strftime("%Y-%m-%dT23:59:59Z")
        )

    except ValueError:
        log_and_print("[ERROR] Неверный формат даты. Используйте YYYY-MM-DD", "error")
        return None


def create_dual_axis_plot(dates, liquidity, market_cap):
    """Создание графика с двумя осями Y."""
    fig = go.Figure()

    # Добавление графика капитализации (левая ось)
    fig.add_trace(go.Scatter(
        x=dates,
        y=market_cap,
        mode='lines',
        name='Капитализация',
        line=dict(color='blue'),
        yaxis='y1'
    ))

    # Добавление графика ликвидности (правая ось)
    fig.add_trace(go.Scatter(
        x=dates,
        y=liquidity,
        mode='lines',
        name='Ликвидность (%)',
        line=dict(color='red'),
        yaxis='y2'
    ))

    # Настройка макета с двумя осями Y
    fig.update_layout(
        title='Капитализация и Ликвидность',
        xaxis_title='Дата',
        yaxis1=dict(
            title='Капитализация (USD)',
            side='left',
            color='blue'
        ),
        yaxis2=dict(
            title='Ликвидность (%)',
            side='right',
            color='red',
            overlaying='y1',
            anchor='x'
        )
    )

    return fig


async def main():
    """Главная функция."""
    log_and_print("[INFO] Начало работы программы...")

    # Получение символа токена
    symbol = input("Введите тикер токена (например, BTC): ").strip().upper()

    # Получение метаданных токена
    async with aiohttp.ClientSession() as session:
        token_metadata = await fetch_token_metadata(session, symbol)
        if not token_metadata:
            log_and_print(f"[ERROR] Токен {symbol} не найден. Проверьте правильность ввода.", "error")
            return

        log_and_print(f"[INFO] Токен ID: {token_metadata['id']}")
        log_and_print(f"[INFO] Адрес контракта: {token_metadata['contract_address']}")

        # Ввод диапазона дат
        start_date_str = input("Введите начальную дату для обработки (YYYY-MM-DD): ").strip()
        end_date_str = input("Введите конечную дату для обработки (YYYY-MM-DD): ").strip()

        # Валидация и корректировка дат
        dates = validate_and_adjust_dates(start_date_str, end_date_str)
        if not dates:
            return

        start_date, end_date = dates
        log_and_print(f"[INFO] Обработка данных с {start_date} по {end_date}")

        # Получение исторических данных
        historical_data = await fetch_historical_data(session, token_metadata['id'], start_date, end_date)

        if not historical_data:
            log_and_print("[ERROR] Нет данных для обработки", "error")
            return

        # Подготовка данных
        dates = []
        liquidity = []
        market_cap = []

        for quote in historical_data:
            date = quote['timestamp'].split('T')[0]
            volume = quote['quote']['USD']['volume_24h']
            market_cap_value = quote['quote']['USD']['market_cap']

            # Расчет ликвидности
            liquidity_percent = (volume / market_cap_value) * 100 if market_cap_value else 0

            dates.append(date)
            liquidity.append(liquidity_percent)
            market_cap.append(market_cap_value)

        # Создание графика
        fig = create_dual_axis_plot(dates, liquidity, market_cap)

        # Сохранение интерактивного HTML
        html_file_path = os.path.join(OUTPUT_FOLDER, f'{symbol}_liquidity_market_cap.html')
        pyo.plot(fig, filename=html_file_path)
        log_and_print(f"[INFO] Интерактивный график сохранен в {html_file_path}")

        # Сохранение данных в Excel
        df = pd.DataFrame({
            'Дата': dates,
            'Ликвидность (%)': liquidity,
            'Капитализация (USD)': market_cap
        })
        excel_file_path = os.path.join(OUTPUT_FOLDER, f'{symbol}_liquidity_market_cap_data.xlsx')
        df.to_excel(excel_file_path, index=False)
        log_and_print(f"[INFO] Данные сохранены в {excel_file_path}")


if __name__ == "__main__":
    log_and_print("[INFO] Запуск основного процесса.")
    asyncio.run(main())
