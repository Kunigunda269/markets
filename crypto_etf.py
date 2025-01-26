import asyncio
import aiohttp
import pandas as pd
import plotly.graph_objects as go
import logging
from datetime import datetime
from tqdm import tqdm
import os
import ssl
import certifi
import re

# Конфигурация логирования
logging.basicConfig(
    filename='crypto_api.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Конфигурация API
API_KEY = "831812bd-1186-43d4-b0d3-b71f0d61074e"
BASE_URL = "https://pro-api.coinmarketcap.com/v2"
HEADERS = {
    "X-CMC_PRO_API_KEY": API_KEY,
    "Accept": "application/json"
}

# Определяем даты для анализа
ANALYSIS_DATES = [
    ("2024-12-08", "2024-12-09"),
    ("2024-12-15", "2024-12-16"),
    ("2024-12-22", "2024-12-23"),
    ("2024-12-29", "2024-12-30"),
    ("2025-01-05", "2025-01-06"),
    ("2025-01-12", "2025-01-13"),
    ("2025-01-18", "2025-01-19")
]


class APIHandler:
    def __init__(self):
        self.session = None
        self.last_request_time = 0

    async def _get_session(self):
        """Создание или получение существующей сессии"""
        if self.session is None:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self.session = aiohttp.ClientSession(connector=connector)
        return self.session

    async def get_token_info(self, query: str):
        """Получение информации о токене по ID или тикеру"""
        session = await self._get_session()

        try:
            endpoint = f"{BASE_URL}/cryptocurrency/info"
            params = {"symbol": query.upper()} if not query.isdigit() else {"id": query}

            async with session.get(endpoint, headers=HEADERS, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("data"):
                        token_data = next(iter(data["data"].values()))[0]
                        return {
                            "id": token_data["id"],
                            "symbol": token_data["symbol"],
                            "name": token_data["name"]
                        }
                    logging.warning(f"Токен {query} не найден")
                    return None
                else:
                    logging.error(f"Ошибка API {response.status} для запроса {query}")
                    return None
        except Exception as e:
            logging.error(f"Ошибка при получении информации о токене: {e}")
            return None

    async def get_historical_data(self, token_id: int, date_start: str, date_end: str):
        """Получение исторических данных токена"""
        session = await self._get_session()

        try:
            endpoint = f"{BASE_URL}/cryptocurrency/quotes/historical"
            params = {
                "id": str(token_id),
                "time_start": f"{date_start}T00:00:00Z",
                "time_end": f"{date_end}T23:59:59Z",
                "interval": "1d",
                "convert": "USD"
            }

            async with session.get(endpoint, headers=HEADERS, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("data", {}).get("quotes"):
                        quotes = data["data"]["quotes"]
                        results = []
                        for quote in quotes:
                            usd_data = quote["quote"]["USD"]
                            results.append({
                                "date": quote["timestamp"][:10],  # Берем только дату
                                "price": usd_data["price"],
                                "market_cap": usd_data["market_cap"]
                            })
                        return results
                    return None
                else:
                    logging.error(f"Ошибка API {response.status} для исторических данных")
                    return None
        except Exception as e:
            logging.error(f"Ошибка при получении исторических данных: {e}")
            return None

    async def close(self):
        """Закрытие сессии"""
        if self.session:
            await self.session.close()
            self.session = None


class DataProcessor:
    """Обработка и анализ данных по категориям"""

    def __init__(self):
        # Фиксированные пути к файлам
        self.category_file = r"C:\Users\Main\PycharmProjects\crypto etf\category_tokens_details_2.xlsx"
        self.result_files = [
            r"C:\Users\Main\PycharmProjects\crypto etf\result_2024-12-08_to_2024-12-09.xlsx",
            r"C:\Users\Main\PycharmProjects\crypto etf\result_2024-12-15_to_2024-12-16.xlsx",
            r"C:\Users\Main\PycharmProjects\crypto etf\result_2024-12-22_to_2024-12-23.xlsx",
            r"C:\Users\Main\PycharmProjects\crypto etf\result_2024-12-29_to_2024-12-30.xlsx",
            r"C:\Users\Main\PycharmProjects\crypto etf\result_2025-01-05_to_2025-01-06.xlsx",
            r"C:\Users\Main\PycharmProjects\crypto etf\result_2025-01-12_to_2025-01-13.xlsx",
            r"C:\Users\Main\PycharmProjects\crypto etf\result_2025-01-18_to_2025-01-19.xlsx"
        ]
        self.categories_df = None
        self._load_categories()

    def _load_categories(self):
        """Загрузка данных категорий"""
        try:
            self.categories_df = pd.read_excel(self.category_file)
            self.categories_df = self.categories_df.dropna(subset=['Symbol', 'Category'])
            logging.info(
                f"Загружено {len(self.categories_df)} токенов из {len(self.categories_df['Category'].unique())} категорий")
        except Exception as e:
            logging.error(f"Ошибка загрузки категорий: {e}")
            raise

    def process_data(self):
        """Обработка данных по категориям"""
        try:
            results = []
            categories = self.categories_df['Category'].unique()

            for result_file in self.result_files:
                try:
                    # Получаем дату из имени файла
                    date_match = re.search(r'result_(\d{4}-\d{2}-\d{2})', result_file)
                    if not date_match:
                        continue
                    date = date_match.group(1)

                    # Загружаем данные результатов
                    df_results = pd.read_excel(result_file)
                    logging.info(f"Обработка файла {result_file}: {len(df_results)} записей")

                    # Обрабатываем каждую категорию
                    for category in categories:
                        # Получаем токены для категории
                        category_tokens = self.categories_df[
                            self.categories_df['Category'] == category
                            ]['Symbol'].tolist()

                        # Фильтруем данные по токенам категории
                        category_data = df_results[
                            df_results['Symbol'].isin(category_tokens)
                        ]

                        if not category_data.empty:
                            results.append({
                                'Category': category,
                                'Date': date,
                                'Price': category_data['Price (USD)'].mean(),
                                'MarketCap': category_data['Market Cap'].mean(),
                                'TokenCount': len(category_data),
                                'TotalTokens': len(category_tokens)
                            })

                except Exception as e:
                    logging.error(f"Ошибка обработки файла {result_file}: {e}")
                    continue

            # Создаем DataFrame с результатами
            results_df = pd.DataFrame(results)

            # Сохраняем промежуточные результаты для проверки
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            debug_filename = f'categories_debug_{timestamp}.xlsx'
            results_df.to_excel(debug_filename, index=False)
            logging.info(f"Отладочные данные сохранены в {debug_filename}")

            return results_df

        except Exception as e:
            logging.error(f"Ошибка при обработке данных категорий: {e}")
            return pd.DataFrame()

    def save_results(self, df: pd.DataFrame, token_symbol: str):
        """Сохранение результатов анализа"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            filename = f'category_analysis_{token_symbol}_{timestamp}.xlsx'

            with pd.ExcelWriter(filename) as writer:
                # Сохраняем основные данные
                df.to_excel(writer, sheet_name='Category Analysis', index=False)

                # Добавляем статистику
                stats_df = df.groupby('Category').agg({
                    'TokenCount': 'mean',
                    'TotalTokens': 'first',
                    'Price': ['mean', 'min', 'max'],
                    'MarketCap': ['mean', 'min', 'max']
                }).round(2)

                stats_df.to_excel(writer, sheet_name='Statistics')

            logging.info(f"Результаты анализа сохранены в {filename}")
            return filename

        except Exception as e:
            logging.error(f"Ошибка при сохранении результатов: {e}")
            return None


class Visualizer:
    def __init__(self):
        # Цвета для динамически выбираемых категорий
        self.dynamic_colors = {
            1: '#0066FF',  # Яркий синий
            2: '#00CC00',  # Яркий зеленый
            3: '#FFD700',  # Золотой
            4: '#FF1493',  # Ярко-розовый
            5: '#00FFFF',  # Циан
            6: '#FF4500',  # Оранжево-красный
            7: '#9400D3',  # Фиолетовый
            8: '#32CD32',  # Лайм
            9: '#FF69B4',  # Розовый
            10: '#4169E1'  # Королевский синий
        }

    def create_combined_plot(self, categories_df: pd.DataFrame, token_df: pd.DataFrame, token_symbol: str):
        """Создание улучшенного комбинированного графика"""
        fig = go.Figure()

        # Вычисляем изменение цены токена
        token_first_price = token_df['price'].iloc[0]
        token_last_price = token_df['price'].iloc[-1]
        token_change = ((token_last_price - token_first_price) / token_first_price) * 100

        # Добавляем линию токена (всегда видима, привязана к левой оси Y)
        fig.add_trace(go.Scatter(
            x=token_df['date'],
            y=token_df['price'],
            name=f"{token_symbol}",
            mode='lines+markers',
            line=dict(color='red', width=3),
            marker=dict(size=8),
            yaxis='y',  # Привязка к левой оси
            visible=True,  # Всегда видимый
            hovertemplate=(
                    f"<b>{token_symbol}</b><br>" +
                    "Дата: %{x}<br>" +
                    "Цена: $%{y:.4f}<br>" +
                    f"Изменение: {token_change:.2f}%<br>" +
                    "<extra></extra>"
            )
        ))

        # Добавляем линии категорий (привязаны к правой оси Y)
        categories = categories_df['Category'].unique()
        for idx, category in enumerate(categories):
            category_data = categories_df[categories_df['Category'] == category]

            first_price = category_data['Price'].iloc[0]
            last_price = category_data['Price'].iloc[-1]
            price_change = ((last_price - first_price) / first_price) * 100

            color_idx = (idx % 10) + 1

            fig.add_trace(go.Scatter(
                x=category_data['Date'],
                y=category_data['Price'],
                name=f"{category}",
                mode='lines+markers',
                line=dict(
                    color=self.dynamic_colors[color_idx],
                    width=3
                ),
                marker=dict(
                    size=8,
                    color=self.dynamic_colors[color_idx]
                ),
                opacity=1.0,
                visible='legendonly',
                yaxis='y2',  # Привязка к правой оси
                hovertemplate=(
                        f"<b>{category}</b><br>" +
                        "Дата: %{x}<br>" +
                        "Цена: $%{y:.4f}<br>" +
                        f"Изменение: {price_change:.2f}%<br>" +
                        "<extra></extra>"
                )
            ))

        # Настраиваем макет с динамической легендой сверху
        fig.update_layout(
            # Верхняя динамическая легенда
            annotations=[dict(
                x=0.5,  # Центр графика
                y=1.12,  # Положение над графиком
                xref="paper",
                yref="paper",
                text=f"{token_symbol}: {token_change:.2f}%",
                showarrow=False,
                font=dict(
                    family="Arial",
                    size=14,
                    color="black"
                ),
                bgcolor="rgba(255, 255, 0, 0.2)",  # Светло-желтый фон
                bordercolor="rgba(255, 255, 0, 0.5)",  # Желтая рамка
                borderwidth=2,
                borderpad=8,  # Увеличенный отступ
                align='center',
                width=1000  # Фиксированная ширина
            )],

            # Настройка осей
            yaxis=dict(
                title=f"Цена {token_symbol} (USD)",
                side='left',
                showgrid=True
            ),
            yaxis2=dict(
                title="Цена категорий (USD)",
                side='right',
                overlaying='y',
                showgrid=False
            ),

            # Остальные настройки макета
            xaxis=dict(title="Дата"),
            showlegend=True,
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.02
            ),
            hovermode='x unified',
            plot_bgcolor='white',
            margin=dict(t=100)  # Отступ сверху для легенды
        )

        return fig

    def save_plot(self, fig, token_symbol: str):
        """Сохранение графика в HTML файл"""
        try:
            # Обновленный путь для сохранения
            save_path = r"C:\Users\Main\PycharmProjects\crypto etf"
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            filename = os.path.join(save_path, f'analysis_{token_symbol}_{timestamp}.html')

            # Конфигурация графика
            config = {
                'displayModeBar': True,
                'scrollZoom': True,
                'displaylogo': False,
                'modeBarButtonsToAdd': ['drawline', 'eraseshape']
            }

            # Получаем базовый HTML
            html_content = fig.to_html(
                config=config,
                include_plotlyjs=True,
                full_html=True,
                include_mathjax=False
            )

            # JavaScript для динамического обновления
            js_code = """
            <script>
                var graphDiv = document.getElementById('graph');

                function updateTopLegend() {
                    var traces = graphDiv.data;
                    var tokenTrace = traces[0];  // Первый график - всегда токен
                    var tokenChange = parseFloat(tokenTrace.hovertemplate.split('Изменение: ')[1]);

                    // Начинаем с токена
                    var legendParts = [`${tokenTrace.name}: ${tokenChange.toFixed(2)}%`];

                    // Собираем информацию о видимых категориях
                    var visibleCategories = [];
                    for(var i = 1; i < traces.length; i++) {
                        if(traces[i].visible === true) {
                            var categoryChange = parseFloat(traces[i].hovertemplate.split('Изменение: ')[1]);
                            visibleCategories.push(`${traces[i].name}: ${categoryChange.toFixed(2)}%`);
                        }
                    }

                    // Добавляем категории, если они есть
                    if(visibleCategories.length > 0) {
                        legendParts = legendParts.concat(visibleCategories);
                    }

                    // Объединяем все части с правильным форматированием
                    var legendText = legendParts.join('  |  ');

                    // Обновляем аннотацию
                    Plotly.relayout(graphDiv, {
                        'annotations[0].text': legendText,
                        'annotations[0].bgcolor': 'rgba(255, 255, 0, 0.2)',
                        'annotations[0].bordercolor': 'rgba(255, 255, 0, 0.5)',
                        'annotations[0].borderwidth': 2,
                        'annotations[0].borderpad': 8,
                        'annotations[0].font.size': 14,
                        'annotations[0].width': Math.min(1000, 200 + legendParts.length * 150)
                    });
                }

                // Обработчики событий для обновления при взаимодействии
                graphDiv.on('plotly_restyle', updateTopLegend);
                graphDiv.on('plotly_legendclick', function(data) {
                    setTimeout(updateTopLegend, 100);
                    return false;
                });

                // Обработчик для перекрестия и обновления при наведении
                graphDiv.on('plotly_hover', function(data) {
                    updateTopLegend();
                });

                // Инициализация при загрузке
                document.addEventListener('DOMContentLoaded', updateTopLegend);
            </script>
            """

            # Добавляем JavaScript в HTML
            html_content = html_content.replace('</body>', f'{js_code}</body>')

            # Сохраняем файл
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(html_content)

            # Проверяем успешность сохранения
            if os.path.exists(filename):
                file_size = os.path.getsize(filename)
                logging.info(f"График успешно сохранен в {filename} (размер: {file_size} байт)")
                return filename
            else:
                logging.error(f"Не удалось сохранить файл {filename}")
                return None

        except Exception as e:
            logging.error(f"Ошибка при сохранении графика: {e}")
            return None


def save_token_data(token_df: pd.DataFrame, token_symbol: str) -> str:
    """Сохранение данных токена в Excel"""
    try:
        # Форматируем DataFrame
        formatted_df = token_df.copy()
        formatted_df['date'] = pd.to_datetime(formatted_df['date']).dt.strftime('%Y-%m-%d')
        formatted_df = formatted_df.rename(columns={
            'date': 'Date',
            'price': 'Price (USD)',
            'market_cap': 'Market Cap'
        })

        # Создаем имя файла с временной меткой
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        filename = os.path.join(r"C:\Users\Main\PycharmProjects\crypto etf",
                                f'token_data_{token_symbol}_{timestamp}.xlsx')

        # Сохраняем в Excel
        formatted_df.to_excel(filename, index=False)
        logging.info(f"Данные токена сохранены в {filename}")
        return filename
    except Exception as e:
        logging.error(f"Ошибка при сохранении данных токена: {e}")
        return None


def save_categories_data(categories_df: pd.DataFrame, token_symbol: str) -> str:
    """Сохранение данных категорий в Excel"""
    try:
        # Форматируем DataFrame
        formatted_df = categories_df.copy()
        formatted_df['Date'] = pd.to_datetime(formatted_df['Date']).dt.strftime('%Y-%m-%d')

        # Создаем имя файла с временной меткой
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        filename = os.path.join(r"C:\Users\Main\PycharmProjects\crypto etf",
                                f'categories_data_{token_symbol}_{timestamp}.xlsx')

        # Сохраняем в Excel
        formatted_df.to_excel(filename, index=False)
        logging.info(f"Данные категорий сохранены в {filename}")
        return filename
    except Exception as e:
        logging.error(f"Ошибка при сохранении данных категорий: {e}")
        return None


async def main():
    """Основная функция программы"""
    api_handler = APIHandler()
    data_processor = DataProcessor()
    visualizer = Visualizer()

    try:
        # === Тестовый запрос ===
        print("\n=== Тестовый запрос ===")
        query = input("Введите ID или тикер токена: ").strip()

        # Получаем информацию о токене
        token_info = await api_handler.get_token_info(query)
        if not token_info:
            print("Токен не найден")
            return

        print("\nИнформация о токене:")
        print(f"ID: {token_info['id']}")
        print(f"Символ: {token_info['symbol']}")
        print(f"Название: {token_info['name']}")

        # Запрашиваем даты для тестового запроса
        print("\nВведите даты для тестового запроса (формат: YYYY-MM-DD)")
        start_date = input("Дата начала: ").strip()
        end_date = input("Дата окончания: ").strip()

        # Проверяем формат дат
        try:
            datetime.strptime(start_date, '%Y-%m-%d')
            datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            print("Неверный формат даты. Используйте формат YYYY-MM-DD")
            return

        # Получаем тестовые данные
        test_data = await api_handler.get_historical_data(
            token_info['id'],
            start_date,
            end_date
        )

        if test_data:
            print(f"\nТестовые данные за период {start_date} - {end_date}:")
            for data in test_data:
                print(f"Дата: {data['date']}")
                print(f"Цена закрытия: ${data['price']:.4f}")
                print(f"Капитализация: ${data['market_cap']:,.2f}")
        else:
            print("Не удалось получить тестовые данные")
            return

        # === Запрос на продолжение ===
        continue_analysis = input("\nПродолжить с полным анализом? (y/n): ").lower()
        if continue_analysis != 'y':
            return

        # === Получение исторических данных ===
        print("\n=== Получение исторических данных ===")
        all_historical_data = []

        print("\nПериоды анализа:")
        for start, end in ANALYSIS_DATES:
            print(f"- {start} to {end}")

        with tqdm(total=len(ANALYSIS_DATES), desc="Прогресс запросов") as pbar:
            for start_date, end_date in ANALYSIS_DATES:
                await asyncio.sleep(1)  # Небольшая задержка между запросами
                period_data = await api_handler.get_historical_data(
                    token_info['id'],
                    start_date,
                    end_date
                )
                if period_data:
                    all_historical_data.extend(period_data)
                else:
                    print(f"\nНе удалось получить данные за период {start_date} - {end_date}")
                pbar.update(1)

        if not all_historical_data:
            print("Не удалось получить исторические данные")
            return

        # Создаем DataFrame с историческими данными токена
        token_df = pd.DataFrame(all_historical_data)

        # Проверяем данные токена
        if token_df.empty:
            print("Ошибка: Данные токена пусты")
            return

        print(f"\nПолучено записей для токена: {len(token_df)}")

        # === Обработка категорий ===
        print("\n=== Обработка данных категорий ===")
        categories_df = data_processor.process_data()

        # Проверяем данные категорий
        if categories_df.empty:
            print("Ошибка: Нет данных категорий для анализа")
            return

        print(f"Получено записей для категорий: {len(categories_df)}")

        # === Сохранение данных ===
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')

        # Сохраняем данные токена
        token_filename = save_token_data(token_df, token_info['symbol'])
        if not token_filename:
            print("Ошибка при сохранении данных токена")
            return
        print(f"\nДанные токена сохранены в {token_filename}")

        # Сохраняем результаты анализа категорий
        analysis_filename = data_processor.save_results(categories_df, token_info['symbol'])
        if analysis_filename:
            print(f"Результаты анализа категорий сохранены в {analysis_filename}")

        # === Создание визуализации ===
        print("\nСоздание визуализации...")

        # Проверяем данные перед визуализацией
        print("\nПроверка данных для визуализации:")
        print(f"Токен {token_info['symbol']}:")
        print(f"- Временной период: с {token_df['date'].min()} по {token_df['date'].max()}")
        print(f"- Диапазон цен: ${token_df['price'].min():.4f} - ${token_df['price'].max():.4f}")
        print("\nКатегории:")
        print(f"- Количество категорий: {len(categories_df['Category'].unique())}")
        print(f"- Временной период: с {categories_df['Date'].min()} по {categories_df['Date'].max()}")

        # Создаем и сохраняем график
        fig = visualizer.create_combined_plot(
            categories_df=categories_df,
            token_df=token_df,
            token_symbol=token_info['symbol']
        )

        # Сохраняем график
        html_filename = visualizer.save_plot(fig, token_info['symbol'])

        if html_filename and os.path.exists(html_filename):
            print(f"\nГрафик сохранен в {html_filename}")
            print(f"Размер файла: {os.path.getsize(html_filename):,} байт")

            # Проверяем содержимое файла
            with open(html_filename, 'r', encoding='utf-8') as f:
                content = f.read()
                if len(content) < 100:  # Минимальный размер валидного HTML
                    print("Предупреждение: Файл графика может быть поврежден")
        else:
            print("Ошибка: Не удалось сохранить график")

        # === Итоговый отчет ===
        print("\nАнализ завершен успешно!")
        print("Созданные файлы:")
        print(f"1. Данные токена: {token_filename}")
        print(f"2. Анализ категорий: {analysis_filename}")
        print(f"3. Интерактивный график: {html_filename}")

    except Exception as e:
        logging.error(f"Ошибка в основной программе: {e}")
        print(f"\nПроизошла ошибка: {e}")
        print("Проверьте лог-файл для деталей")

    finally:
        await api_handler.close()


if __name__ == "__main__":
    if os.name == 'nt':  # для Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())