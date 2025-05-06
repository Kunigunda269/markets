import asyncio
import aiohttp
import pandas as pd
import logging
import os
import sys
import time
import plotly.graph_objects as go
import plotly.offline as pyo
from datetime import datetime
from collections import OrderedDict
from typing import Dict, List, Optional

# === Конфигурация ===
API_KEY: str = "123"
HEADERS: Dict[str, str] = {"X-CMC_PRO_API_KEY": API_KEY}
BASE_URL_HISTORICAL: str = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
OUTPUT_FOLDER: str = r"C:\Users\Main\Pitonio\crypto etf"

# === Логирование ===
logging.basicConfig(
    filename=os.path.join(OUTPUT_FOLDER, "crypto_combined.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def log_and_print(message: str, level: str = "info") -> None:
    """Логирование сообщений с одновременным выводом в консоль."""
    print(f"[{level.upper()}] {message}")
    getattr(logging, level)(message)


class RateLimiter:
    def __init__(self, max_requests_per_minute: int) -> None:
        self.interval: float = 60 / max_requests_per_minute
        self.last_call: float = time.time()

    async def wait(self) -> None:
        """Ждёт, если запросы отправляются слишком часто."""
        now: float = time.time()
        elapsed: float = now - self.last_call
        if elapsed < self.interval:
            await asyncio.sleep(self.interval - elapsed)
        self.last_call = time.time()


rate_limiter: RateLimiter = RateLimiter(30)


async def fetch_historical_data(session: aiohttp.ClientSession, symbol: str, start_date: str, end_date: str) -> Dict[
    str, float]:
    """Запрашивает исторические данные о криптовалюте и группирует их по дням."""
    url: str = BASE_URL_HISTORICAL
    params: Dict[str, str] = {
        "symbol": symbol,
        "time_start": start_date,
        "time_end": end_date,
        "convert": "USD"
    }
    await rate_limiter.wait()

    async with session.get(url, headers=HEADERS, params=params) as response:
        data: Dict = await response.json()
        log_and_print(f"[DEBUG] Ответ API: {data}", "info")

        if "data" not in data or symbol not in data["data"]:
            log_and_print("[ERROR] API не вернул данных о криптовалюте", "error")
            return {}

        quotes: List[Dict] = data["data"][symbol][0]["quotes"]
        daily_data: Dict[str, float] = OrderedDict()

        for entry in quotes:
            date: str = entry["timestamp"].split("T")[0]
            daily_data[date] = entry["quote"]["USD"]["volume_24h"]

        return daily_data


def plot_xrp_volume_line_chart(data: pd.DataFrame) -> None:
    """Строит линейный график объема торгов."""
    data["Дата"] = pd.to_datetime(data["Дата"])

    fig: go.Figure = go.Figure()
    fig.add_trace(go.Scatter(
        x=data["Дата"],
        y=data["Объем торгов (USD)"],
        mode='lines+markers',
        line=dict(color='blue', width=2),
        marker=dict(size=8, color='blue'),
        name='Объем торгов'
    ))

    fig.update_layout(
        title="Объем торгов (USD) (дневной)",
        xaxis_title="Дата",
        yaxis_title="Объем торгов (USD)",
        template="plotly_white"  # Фон белый
    )

    html_file_path: str = os.path.join(OUTPUT_FOLDER, "trading_volume.html")
    pyo.plot(fig, filename=html_file_path, auto_open=True)
    log_and_print(f"[INFO] График сохранен в {html_file_path}")


async def main() -> None:
    """Основная логика работы программы."""
    log_and_print("[INFO] Начало работы программы...")

    symbol: str = input("Введите тикер токена (например, BTC): ").strip().upper()
    start_date: str = input("Введите начальную дату (YYYY-MM-DD): ").strip()
    end_date: str = input("Введите конечную дату (YYYY-MM-DD): ").strip()

    # Проверка формата даты
    try:
        start_dt: datetime = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt: datetime = datetime.strptime(end_date, "%Y-%m-%d")
        if start_dt >= end_dt:
            log_and_print("[ERROR] Начальная дата должна быть раньше конечной.", "error")
            return
    except ValueError:
        log_and_print("[ERROR] Неверный формат даты. Используйте YYYY-MM-DD.", "error")
        return

    start_date += "T00:00:00Z"
    end_date += "T23:59:59Z"

    async with aiohttp.ClientSession() as session:
        daily_data: Dict[str, float] = await fetch_historical_data(session, symbol, start_date, end_date)
        if not daily_data:
            log_and_print("[ERROR] Нет данных", "error")
            return

        dates: List[str] = list(daily_data.keys())
        volumes: List[float] = list(daily_data.values())

        df: pd.DataFrame = pd.DataFrame({"Дата": dates, "Объем торгов (USD)": volumes})
        plot_xrp_volume_line_chart(df)

        # Сохранение данных в Excel
        excel_file_path: str = os.path.join(OUTPUT_FOLDER, "trading_volume_data.xlsx")
        df.to_excel(excel_file_path, index=False)
        log_and_print(f"[INFO] Данные сохранены в {excel_file_path}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    log_and_print("[INFO] Запуск основного процесса.")
    asyncio.run(main())
