import os
import requests
import json
from datetime import datetime
import pandas as pd
import logging
from pathlib import Path
import time
from tqdm import tqdm
import csv
import concurrent.futures
from typing import Dict, List, Optional
import re
from dataclasses import dataclass
import matplotlib.pyplot as plt
import socket
import tempfile


def _load_dotenv_files() -> None:
    """Load .env from repo root and cwd (best-effort; optional python-dotenv)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(repo_root / ".env")
    load_dotenv(Path.cwd() / ".env")


_load_dotenv_files()


@dataclass
class StockMetrics:
    """Класс для хранения метрик акции"""
    pe_ratio: float
    roe: float
    debt_to_equity: float
    operating_margin: float
    net_margin: float
    industry_pe: float = None
    industry_roe: float = None


class APIError(Exception):
    """Класс для обработки ошибок API"""
    pass


class ValidationError(Exception):
    """Класс для обработки ошибок валидации"""
    pass


def validate_symbol(symbol: str) -> bool:
    """Валидация тикера акции"""
    if not symbol or not isinstance(symbol, str):
        return False
    # Проверяем формат тикера (буквы, цифры, точки)
    return bool(re.match(r'^[A-Z0-9.]+$', symbol))


def validate_date(date_str: str) -> bool:
    """Валидация даты"""
    if not date_str:
        return True
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False


# Настройка логирования
def setup_logging():
    # Используем текущую рабочую директорию вместо хардкода
    log_dir = Path.cwd()

    log_file = log_dir / f"guru_marina_{datetime.now().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


class GuruFocusAPI:
    def __init__(self, api_key: str = None, max_retries: int = 3, 
                 cache_expiry_hours: int = 24):
        self.logger = setup_logging()

        # API key: explicit arg > GURUFOCUS_API_KEY from .env / environment
        if api_key:
            self.api_key = api_key
        else:
            self.api_key = os.getenv("GURUFOCUS_API_KEY", "")

        self.cache_dir = Path("cache")
        self.cache_dir.mkdir(exist_ok=True)
        self.max_retries = max_retries
        self.cache_expiry_hours = cache_expiry_hours

        # Инициализация сессии с правильными заголовками
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/120.0.0.0 Safari/537.36'),
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Referer': 'https://www.gurufocus.com/'
        })
        
        # Настраиваем адаптер для автоматической декодировки сжатия
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            
            # Настраиваем ретраи
            retry_strategy = Retry(
                total=3,
                status_forcelist=[429, 500, 502, 503, 504],
                backoff_factor=1
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)
            
        except ImportError:
            self.logger.warning("Библиотека brotli не установлена, brotli сжатие может не работать")

        # Создаем директории для данных
        self.data_dirs = {
            'historical': Path("historical_data"),
            'analysis': Path("analysis_results"),
            'charts': Path("charts")
        }
        for directory in self.data_dirs.values():
            directory.mkdir(exist_ok=True)

        try:
            self.criteria_df = pd.read_excel('Marina_guru.xlsx', sheet_name='Критерии анализа')
            self.logger.info("Успешно загружены критерии анализа из Excel")
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке Excel файла: {e}")
            raise

    def get_cache_path(self, endpoint):
        """Получение пути к файлу кэша"""
        return self.cache_dir / f"{endpoint.replace('/', '_')}.json"

    def get_cached_data(self, endpoint, max_age_hours=24):
        """Получение данных из кэша с валидацией"""
        cache_path = self.get_cache_path(endpoint)
        if cache_path.exists():
            cache_age = time.time() - cache_path.stat().st_mtime
            if cache_age < max_age_hours * 3600:
                try:
                    with open(cache_path, 'r') as f:
                        data = json.load(f)
                        # Валидация данных
                        if self._validate_cached_data(data):
                            return data
                        else:
                            self.logger.warning(f"Кэшированные данные для {endpoint} невалидны")
                            cache_path.unlink()  # Удаляем невалидный кэш
                except Exception as e:
                    self.logger.error(f"Ошибка при чтении кэша: {e}")
                    cache_path.unlink()  # Удаляем поврежденный кэш
        return None

    def _validate_cached_data(self, data):
        """Валидация кэшированных данных"""
        if not isinstance(data, (dict, list)):
            return False
        if isinstance(data, list) and len(data) == 0:
            return False
        return True

    def save_to_cache(self, endpoint, data):
        """Сохранение данных в кэш с валидацией"""
        try:
            if not self._validate_cached_data(data):
                self.logger.warning(f"Попытка сохранить невалидные данные в кэш для {endpoint}")
                return False

            cache_path = self.get_cache_path(endpoint)
            with open(cache_path, 'w') as f:
                json.dump(data, f)
            self.logger.info(f"Данные сохранены в кэш: {endpoint}")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении в кэш: {e}")
            return False

    def make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Простой метод для выполнения запросов к API с поддержкой сжатия"""
        try:
            # Проверяем кэш
            cached_data = self.get_cached_data(endpoint)
            if cached_data:
                self.logger.info(f"Используем кэшированные данные для {endpoint}")
                return cached_data

            # Правильный формат URL для GuruFocus API
            url = f"https://api.gurufocus.com/public/user/{self.api_key}/{endpoint}"

            self.logger.info(f"Запрос: {url}")

            response = self.session.get(url, params=params, timeout=10)
            
            # Логируем статус ответа
            print(f"Статус ответа: {response.status_code}")
            
            if response.status_code == 403:
                print("403 Forbidden - API ключ недействителен или заблокирован")
                print("Проверьте ключ на "
                      "https://www.gurufocus.com/api/authentication")
                return None
            elif response.status_code == 401:
                print(f"401 Unauthorized - Неверный API ключ")
                return None
            elif response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                print(f"429 Too Many Requests - Ожидание {retry_after} секунд")
                time.sleep(retry_after)
                return self.make_request(endpoint, params)  # Повторяем запрос
            
            response.raise_for_status()
            
            # Проверяем размер и содержимое ответа
            print(f"Размер ответа: {len(response.content)} байт")
            print(f"Content-Type: {response.headers.get('Content-Type', 'не указан')}")
            
            # Проверяем, что получили данные
            if not response.content:
                print(f"Получен пустой ответ")
                return None
            
            # Проверяем, не получили ли мы HTML вместо JSON
            content_type = response.headers.get('Content-Type', '').lower()
            if 'html' in content_type or 'html' in response.text.lower()[:100]:
                print(f"Получен HTML вместо JSON - проблема с API ключом или доступом")
                print(f"Первые 200 символов: {response.text[:200]}")
                return None
            
            try:
                # Попробуем сначала стандартный JSON
                try:
                    data = response.json()
                    print("✅ JSON успешно декодирован")
                except json.JSONDecodeError:
                    # Если не получилось, проверяем сжатие
                    content_encoding = response.headers.get('Content-Encoding', '').lower()
                    if content_encoding == 'br':
                        try:
                            import brotli
                            content = brotli.decompress(response.content)
                            data = json.loads(content.decode('utf-8'))
                            print("✅ JSON декодирован из Brotli")
                        except ImportError:
                            print("⚠️ Brotli не установлен, попробуем без декодирования")
                            # Попробуем декодировать как есть
                            data = json.loads(response.text)
                    elif content_encoding == 'gzip':
                        import gzip
                        content = gzip.decompress(response.content)
                        data = json.loads(content.decode('utf-8'))
                        print("✅ JSON декодирован из Gzip")
                    else:
                        # Последняя попытка - читаем как текст
                        data = json.loads(response.text)
                        print("✅ JSON декодирован из текста")
                
                # Показываем структуру ответа для диагностики
                if isinstance(data, dict):
                    print(f"Получен словарь с ключами: {list(data.keys())}")
                    if not any(data.values()):
                        print("⚠️  Словарь содержит только пустые значения")
                elif isinstance(data, list):
                    print(f"Получен список с {len(data)} элементами")
                    if len(data) == 0:
                        print("⚠️  Список пуст")
                else:
                    print(f"Получен объект типа: {type(data)}")
                
            except json.JSONDecodeError as e:
                print(f"❌ Ошибка декодирования JSON: {e}")
                print(f"Первые 200 символов ответа: {response.text[:200]}")
                return None
            
            # Проверяем, не пустые ли структуры
            if isinstance(data, dict) and not any(data.values()):
                print(f"⚠️  API вернул словарь с пустыми значениями")
                return data  # Возвращаем даже пустые данные для анализа
            elif isinstance(data, list) and len(data) == 0:
                print(f"⚠️  API вернул пустой список")
                return None

            # Валидация и нормализация данных
            normalized_data = self._normalize_response_data(data)

            # Сохраняем в кэш только если данные валидны
            if normalized_data:
                self.save_to_cache(endpoint, normalized_data)
                return normalized_data
            else:
                print(f"Получены данные, но нормализация не удалась")
                return data  # Возвращаем исходные данные для анализа
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Ошибка запроса: {e}")
            return None
        except Exception as e:
            print(f"❌ Неожиданная ошибка: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _normalize_response_data(self, data):
        """Нормализация данных ответа API"""
        if isinstance(data, list):
            if len(data) == 0:
                return None
            if isinstance(data[0], list):
                # Преобразуем список списков в словарь
                try:
                    return {str(i): item for i, item in enumerate(data)}
                except Exception as e:
                    self.logger.error(f"Ошибка при нормализации списка списков: {e}")
                    return None
            return data[0] if len(data) == 1 else data
        return data

    def extract_latest_metric(self, metric_dict):
        """Извлечение последнего значения метрики по дате"""
        if isinstance(metric_dict, dict):
            try:
                latest_date = max(metric_dict.keys())
                return metric_dict[latest_date]
            except (KeyError, ValueError, TypeError):
                return "NO DATA"
        return "NO DATA"

    def get_stock_data(self, symbol: str) -> Dict:
        """Получение данных по акции"""
        if not validate_symbol(symbol):
            raise ValidationError(f"Некорректный тикер: {symbol}")

        try:
            # Получаем ключевые метрики
            keyratios_data = self.make_request(f"stock/{symbol}/key_ratios")

            # Если API вернул список, проверяем его содержимое
            if isinstance(keyratios_data, list):
                if len(keyratios_data) > 0:
                    if isinstance(keyratios_data[0], dict):
                        keyratios_data = keyratios_data[0]
                    elif isinstance(keyratios_data[0], list):
                        # Сохраняем список списков в Excel в корневую папку
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        excel_path = Path(
                            os.getenv("GURU_OUTPUT_DIR", "output")) / f"raw_keyratios_{symbol}_{timestamp}.xlsx"
                        df = pd.DataFrame(keyratios_data)
                        df.to_excel(excel_path, index=False)
                        self.logger.info(f'Список списков для {symbol} сохранён в Excel: {excel_path}')
                        raise APIError(
                            f'API вернул список списков для {symbol}. Данные сохранены в Excel: {excel_path}')
                    else:
                        # Сохраняем неожиданный список в Excel в корневую папку
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        excel_path = Path(
                            os.getenv("GURU_OUTPUT_DIR", "output")) / f"raw_keyratios_{symbol}_{timestamp}.xlsx"
                        df = pd.DataFrame(keyratios_data)
                        df.to_excel(excel_path, index=False)
                        self.logger.info(f'Неожиданный список для {symbol} сохранён в Excel: {excel_path}')
                        raise APIError(
                            f'API вернул список с неожиданным форматом для {symbol}. Данные сохранены в Excel: {excel_path}')
                else:
                    self.logger.error(f'API вернул пустой список для {symbol}')
                    raise APIError(
                        f'API вернул пустой список для {symbol}. Проверьте формат ответа или используйте функцию test_api_request для диагностики.')

            # Проверяем, получили ли мы обычные данные или сырые бинарные данные
            if isinstance(keyratios_data, dict) and keyratios_data.get("_raw_response", False):
                self.logger.info(f"Получены сырые данные для {symbol}, невозможно выполнить анализ")

                # Сохраняем бинарные данные для дальнейшего анализа
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                bin_file = Path(f"{symbol}_keyratios_{timestamp}.bin")
                with open(bin_file, 'wb') as f:
                    f.write(keyratios_data.get("binary_content", b''))

                # Создаем заглушку данных
                empty_metrics = {
                    "pe_ratio": "NO DATA",
                    "pb_ratio": "NO DATA",
                    "ps_ratio": "NO DATA",
                    "debt_to_equity": "NO DATA",
                    "current_ratio": "NO DATA",
                    "quick_ratio": "NO DATA",
                    "interest_coverage": "NO DATA",
                    "roe": "NO DATA",
                    "roa": "NO DATA",
                    "operating_margin": "NO DATA",
                    "net_margin": "NO DATA",
                    "gross_margin": "NO DATA",
                    "revenue_growth": "NO DATA",
                    "earnings_growth": "NO DATA",
                    "dividend_yield": "NO DATA",
                    "payout_ratio": "NO DATA"
                }

                # Нормализуем метрики в ожидаемый формат
                normalized_metrics = {}
                for name, raw_value in empty_metrics.items():
                    normalized_metrics[name] = {
                        "value": None,
                        "rating": "Нет данных",
                        "score": 0.0,
                        "industry_value": None
                    }

                return {
                    "metrics": normalized_metrics,
                    "company_name": symbol,
                    "sector": "Данные недоступны",
                    "industry": "Данные недоступны",
                    "raw_response": True,
                    "message": "API вернул данные в неизвестном формате. Используйте функцию test_api_request для анализа."
                }

            # Извлекаем нужные метрики из keyratios
            raw_metrics = {
                "pe_ratio": self.extract_latest_metric(keyratios_data.get("Valuation Ratio", {}).get("PE Ratio")),
                "pb_ratio": self.extract_latest_metric(keyratios_data.get("Valuation Ratio", {}).get("PB Ratio")),
                "ps_ratio": self.extract_latest_metric(keyratios_data.get("Valuation Ratio", {}).get("PS Ratio")),
                "debt_to_equity": self.extract_latest_metric(
                    keyratios_data.get("Financial Strength", {}).get("Debt-to-Equity")),
                "current_ratio": self.extract_latest_metric(
                    keyratios_data.get("Financial Strength", {}).get("Current Ratio")),
                "quick_ratio": self.extract_latest_metric(
                    keyratios_data.get("Financial Strength", {}).get("Quick Ratio")),
                "interest_coverage": self.extract_latest_metric(
                    keyratios_data.get("Financial Strength", {}).get("Interest Coverage")),
                "roe": self.extract_latest_metric(keyratios_data.get("Profitability", {}).get("ROE")),
                "roa": self.extract_latest_metric(keyratios_data.get("Profitability", {}).get("ROA")),
                "operating_margin": self.extract_latest_metric(
                    keyratios_data.get("Profitability", {}).get("Operating Margin")),
                "net_margin": self.extract_latest_metric(keyratios_data.get("Profitability", {}).get("Net Margin")),
                "gross_margin": self.extract_latest_metric(keyratios_data.get("Profitability", {}).get("Gross Margin")),
                "revenue_growth": self.extract_latest_metric(keyratios_data.get("Growth", {}).get("Revenue Growth")),
                "earnings_growth": self.extract_latest_metric(keyratios_data.get("Growth", {}).get("Earnings Growth")),
                "dividend_yield": self.extract_latest_metric(keyratios_data.get("Dividend", {}).get("Dividend Yield")),
                "payout_ratio": self.extract_latest_metric(keyratios_data.get("Dividend", {}).get("Payout Ratio"))
            }

            # Нормализуем метрики в ожидаемый формат
            normalized_metrics = {}
            for name, raw_value in raw_metrics.items():
                try:
                    value = float(raw_value) if raw_value != "NO DATA" else None
                except (ValueError, TypeError):
                    value = None

                normalized_metrics[name] = {
                    "value": value,
                    "rating": self._get_rating(name, value),
                    "score": self._get_score(name, value),
                    "industry_value": None  # Можно добавить позже, если доступно
                }

            # Объединяем все данные
            stock_data = {
                "metrics": normalized_metrics,
                "company_name": keyratios_data.get("Company Name", "N/A"),
                "sector": keyratios_data.get("Sector", "N/A"),
                "industry": keyratios_data.get("Industry", "N/A")
            }

            return stock_data

        except APIError as e:
            self.logger.error(f"Ошибка при получении данных для {symbol}: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при получении данных для {symbol}: {e}")
            raise APIError(f"Неожиданная ошибка при получении данных для {symbol}: {e}")

    def analyze_stock(self, symbol: str) -> Dict:
        """Анализ акции на основе полученных метрик"""
        try:
            data = self.get_stock_data(symbol)
            if not data:
                raise APIError(f"Не удалось получить данные для {symbol}")

            # Проверяем, получили ли мы сырые данные
            if data.get("raw_response", False):
                self.logger.warning(
                    f"Невозможно провести анализ для {symbol}: {data.get('message', 'Неизвестный формат данных')}")
                return {
                    "symbol": symbol,
                    "company_name": data.get("company_name", symbol),
                    "error": True,
                    "message": data.get("message", "Неизвестный формат данных"),
                    "recommendation": "Используйте функцию test_api_request для получения и анализа сырых данных API."
                }

            # Получаем метрики
            metrics = data["metrics"]

            # Рассчитываем итоговый скор
            total_score = 0
            valid_metrics_count = 0

            for metric_name, metric_data in metrics.items():
                score = metric_data.get("score", 0)
                if score > 0:  # Считаем только метрики с валидными данными
                    total_score += score
                    valid_metrics_count += 1

            final_score = 0
            if valid_metrics_count > 0:
                final_score = (total_score / (valid_metrics_count * 5)) * 100  # Нормализуем к 100%

            # Определяем итоговый рейтинг
            if final_score >= 80:
                final_rating = "Отлично"
            elif final_score >= 60:
                final_rating = "Хорошо"
            elif final_score >= 40:
                final_rating = "Удовлетворительно"
            elif final_score >= 20:
                final_rating = "Ниже среднего"
            else:
                final_rating = "Плохо"

            # Анализ с учетом метрик
            analysis_results = {
                "symbol": symbol,
                "company_name": data["company_name"],
                "sector": data["sector"],
                "industry": data["industry"],
                "metrics": metrics,
                "final_score": final_score,
                "final_rating": final_rating,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            # Добавляем интерпретацию метрик
            analysis_results["interpretation"] = {
                "Valuation": self._interpret_valuation_ratios(metrics),
                "Financial Strength": self._interpret_financial_strength(metrics),
                "Profitability": self._interpret_profitability(metrics),
                "Growth": self._interpret_growth(metrics),
                "Dividend": self._interpret_dividend(metrics)
            }

            # Создаем визуализации
            self._create_charts(symbol, data, analysis_results)

            return analysis_results

        except Exception as e:
            self.logger.error(f"Ошибка при анализе {symbol}: {e}")
            raise

    def _interpret_valuation_ratios(self, metrics: Dict) -> Dict:
        """Интерпретация мультипликаторов"""
        interpretation = {}

        # P/E Ratio
        pe_data = metrics.get("pe_ratio", {})
        interpretation["P/E"] = pe_data.get("rating", "Нет данных")

        # P/B Ratio
        pb_data = metrics.get("pb_ratio", {})
        interpretation["P/B"] = pb_data.get("rating", "Нет данных")

        # P/S Ratio
        ps_data = metrics.get("ps_ratio", {})
        interpretation["P/S"] = ps_data.get("rating", "Нет данных")

        return interpretation

    def _interpret_financial_strength(self, metrics: Dict) -> Dict:
        """Интерпретация показателей финансовой устойчивости"""
        interpretation = {}

        # Debt-to-Equity
        dte_data = metrics.get("debt_to_equity", {})
        interpretation["Debt-to-Equity"] = dte_data.get("rating", "Нет данных")

        # Current Ratio
        cr_data = metrics.get("current_ratio", {})
        interpretation["Current Ratio"] = cr_data.get("rating", "Нет данных")

        return interpretation

    def _interpret_profitability(self, metrics: Dict) -> Dict:
        """Интерпретация показателей прибыльности"""
        interpretation = {}

        # ROE
        roe_data = metrics.get("roe", {})
        interpretation["ROE"] = roe_data.get("rating", "Нет данных")

        # Operating Margin
        om_data = metrics.get("operating_margin", {})
        interpretation["Operating Margin"] = om_data.get("rating", "Нет данных")

        return interpretation

    def _interpret_growth(self, metrics: Dict) -> Dict:
        """Интерпретация показателей роста"""
        interpretation = {}

        # Revenue Growth
        rg_data = metrics.get("revenue_growth", {})
        interpretation["Revenue Growth"] = rg_data.get("rating", "Нет данных")

        # Earnings Growth
        eg_data = metrics.get("earnings_growth", {})
        interpretation["Earnings Growth"] = eg_data.get("rating", "Нет данных")

        return interpretation

    def _interpret_dividend(self, metrics: Dict) -> Dict:
        """Интерпретация показателей дивидендов"""
        interpretation = {}

        # Dividend Yield
        dy_data = metrics.get("dividend_yield", {})
        interpretation["Dividend Yield"] = dy_data.get("rating", "Нет данных")

        # Payout Ratio
        pr_data = metrics.get("payout_ratio", {})
        interpretation["Payout Ratio"] = pr_data.get("rating", "Нет данных")

        return interpretation

    def _create_charts(self, symbol: str, data: Dict, analysis_results: Dict):
        """Создание визуализаций для анализа"""
        # Настройка стиля графиков
        plt.style.use('seaborn-v0_8')

        # Создаем директорию для графиков
        charts_dir = self.data_dirs['charts'] / symbol
        charts_dir.mkdir(exist_ok=True)

        # График исторических цен
        if "historical" in data and data["historical"]:
            df_historical = pd.DataFrame(data["historical"])
            plt.figure(figsize=(12, 6))
            plt.plot(df_historical['date'], df_historical['close'])
            plt.title(f'Исторические цены {symbol}')
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(charts_dir / 'historical_prices.png')
            plt.close()

        # График сравнения с отраслью
        metrics = analysis_results["metrics"]
        industry_values_exist = any(m.get("industry_value") is not None for m in metrics.values())

        if industry_values_exist:
            plt.figure(figsize=(10, 6))
            metric_names = []
            company_values = []
            industry_values = []

            for metric_name, metric_data in metrics.items():
                if metric_data.get("value") is not None:
                    metric_names.append(metric_name)
                    company_values.append(metric_data.get("value", 0))
                    industry_values.append(metric_data.get("industry_value", 0))

            x = range(len(metric_names))
            plt.bar(x, company_values, width=0.35, label='Компания')
            plt.bar([i + 0.35 for i in x], industry_values, width=0.35, label='Отрасль')
            plt.xticks([i + 0.175 for i in x], metric_names, rotation=45)
            plt.legend()
            plt.title(f'Сравнение с отраслью - {symbol}')
            plt.tight_layout()
            plt.savefig(charts_dir / 'industry_comparison.png')
            plt.close()

        # График оценок метрик
        plt.figure(figsize=(12, 6))
        metric_names = []
        scores = []

        for metric_name, metric_data in metrics.items():
            if metric_data.get("score") is not None:
                metric_names.append(metric_name)
                scores.append(metric_data.get("score", 0))

        if metric_names:
            colors = ['green' if s >= 4 else 'blue' if s >= 3 else 'orange' if s >= 2 else 'red' for s in scores]
            plt.bar(metric_names, scores, color=colors)
            plt.axhline(y=2.5, color='r', linestyle='--', alpha=0.3)
            plt.title(f'Оценка метрик - {symbol}')
            plt.xticks(rotation=45)
            plt.ylim(0, 5)
            plt.tight_layout()
            plt.savefig(charts_dir / 'metrics_scores.png')
            plt.close()

    def analyze_multiple_stocks(self, symbols: List[str]) -> Dict[str, Dict]:
        """Анализ нескольких акций параллельно"""
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_symbol = {
                executor.submit(self.analyze_stock, symbol): symbol
                for symbol in symbols
            }

            for future in tqdm(concurrent.futures.as_completed(future_to_symbol),
                               total=len(symbols),
                               desc="Анализ акций"):
                symbol = future_to_symbol[future]
                try:
                    results[symbol] = future.result()
                except Exception as e:
                    self.logger.error(f"Ошибка при анализе {symbol}: {e}")
                    results[symbol] = {"error": str(e)}

        return results

    def save_to_excel(self, analysis_results: Dict) -> Optional[str]:
        """Улучшенное сохранение результатов в Excel"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            excel_path = Path(
                os.getenv("GURU_OUTPUT_DIR", "output")) / f"analysis_{analysis_results['symbol']}_{timestamp}.xlsx"

            with pd.ExcelWriter(excel_path) as writer:
                # Лист с метриками
                metrics_data = []
                for metric_name, metric_data in analysis_results["metrics"].items():
                    metrics_data.append({
                        "Метрика": metric_name,
                        "Значение": metric_data.get("value", "None"),
                        "Отраслевое значение": metric_data.get("industry_value", "None"),
                        "Оценка": metric_data.get("rating", "None"),
                        "Балл": metric_data.get("score", "None")
                    })

                df_metrics = pd.DataFrame(metrics_data)
                df_metrics.to_excel(writer, sheet_name="Метрики", index=False)

                # Лист с итогами
                df_summary = pd.DataFrame([{
                    "Тикер": analysis_results.get("symbol", "None"),
                    "Компания": analysis_results.get("company_name", "None"),
                    "Итоговый скоринг": f"{analysis_results.get('final_score', 0):.1f}%" if "final_score" in analysis_results else "None",
                    "Рейтинг": analysis_results.get("final_rating", "None"),
                    "Дата анализа": analysis_results.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                }])
                df_summary.to_excel(writer, sheet_name="Итоги", index=False)

                # Лист с графиками
                charts_sheet = writer.book.add_worksheet("Графики")

                # Проверяем наличие графиков перед вставкой
                historical_path = self.data_dirs['charts'] / analysis_results.get('symbol',
                                                                                  '') / 'historical_prices.png'
                industry_path = self.data_dirs['charts'] / analysis_results.get('symbol',
                                                                                '') / 'industry_comparison.png'

                if historical_path.exists():
                    charts_sheet.insert_image('A1', str(historical_path))

                if industry_path.exists():
                    charts_sheet.insert_image('A20', str(industry_path))

            self.logger.info(f"Результаты сохранены в {excel_path}")
            return str(excel_path)

        except Exception as e:
            self.logger.error(f"Ошибка при сохранении в Excel: {e}")
            return None

    def download_historical_data(self, symbol, start_date=None, end_date=None):
        """Загрузка исторических данных в CSV формате"""
        self.logger.info(f"Загрузка исторических данных для {symbol}")

        # Формируем параметры запроса
        params = {}

        if start_date:
            params['start_date'] = start_date
        if end_date:
            params['end_date'] = end_date

        try:
            # Загружаем данные используя сессию и новый формат URL
            url = f"https://api.gurufocus.com/public/user/{self.api_key}/stock/{symbol}/price"

            # Добавляем заголовки для запроса
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9'
            }

            response = self.session.get(url, params=params, headers=headers)
            response.raise_for_status()

            # Создаем директорию для сохранения если её нет
            data_dir = Path("historical_data")
            data_dir.mkdir(exist_ok=True)

            # Формируем имя файла
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            try:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    # Получаем заголовки из первого элемента
                    headers = data[0].keys()
                    # Сохраняем в CSV, заменяя None на строку "None"
                    filename = data_dir / f"{symbol}_historical_{timestamp}.csv"
                    with open(filename, 'w', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=headers)
                        writer.writeheader()
                        # Обрабатываем пустые значения
                        processed_data = []
                        for row in data:
                            processed_row = {k: "None" if v is None else v for k, v in row.items()}
                            processed_data.append(processed_row)
                        writer.writerows(processed_data)
                    self.logger.info(f"Исторические данные сохранены в {filename}")
                    return str(filename)
                else:
                    self.logger.error("Получены пустые данные")
                    # Если данные пустые, но формат JSON, сохраняем как есть
                    json_file = data_dir / f"{symbol}_historical_{timestamp}.json"
                    with open(json_file, 'w') as f:
                        json.dump(data, f, indent=2)
                    self.logger.info(f"Пустые JSON данные сохранены в {json_file}")
                    return None
            except json.JSONDecodeError:
                # Если не JSON, сохраняем как бинарный файл
                self.logger.warning(f"Ответ API не является JSON, сохраняем как бинарный файл")
                bin_file = data_dir / f"{symbol}_historical_raw_{timestamp}.bin"
                with open(bin_file, 'wb') as f:
                    f.write(response.content)
                return str(bin_file)

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Ошибка при загрузке исторических данных: {e}")
            return None

    def check_api_key_status(self) -> Dict:
        """Проверка статуса API ключа с расширенной диагностикой"""
        results = []

        try:
            # Определяем IP-адрес хоста
            try:
                host_ip = socket.gethostbyname(socket.gethostname())
            except socket.error:
                host_ip = "Не удалось определить"

            # Пробуем получить данные для тестового тикера
            test_url = f"https://api.gurufocus.com/public/user/{self.api_key}/stock/AAPL/key_ratios"
            self.logger.info(f"Проверка API-ключа: {test_url}")
            self.logger.info(f"IP-адрес хоста: {host_ip}")

            # Добавляем заголовок User-Agent
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }

            response = self.session.get(test_url, headers=headers)

            status = {
                "key_type": "Полный ключ",
                "api_key": self.api_key,
                "is_valid": response.status_code == 200,
                "status_code": response.status_code,
                "message": "",
                "details": {
                    "test_url": test_url,
                    "host_ip": host_ip
                }
            }

            if response.status_code == 403:
                status["message"] = "API ключ неактивен или заблокирован"
                response_text = response.text[:500] if response.text else "Нет текста ответа"
                self.logger.error(f"Текст ответа 403: {response_text}")
                status["details"].update({
                    "possible_reasons": [
                        "Ключ неактивен или заблокирован",
                        "IP адрес не в whitelist",
                        "Исчерпан лимит запросов"
                    ],
                    "action_required": "Проверьте статус API ключа на https://www.gurufocus.com/account",
                    "response_text": response_text
                })
            elif response.status_code == 401:
                status["message"] = "Неверный API ключ (401 Unauthorized)"
                response_text = response.text[:500] if response.text else "Нет текста ответа"
                self.logger.error(f"Текст ответа 401: {response_text}")
                status["details"].update({
                    "possible_reasons": [
                        "API-ключ недействителен или устарел",
                        "API-ключ не активирован на странице аутентификации",
                        "API-ключ был отозван"
                    ],
                    "action_required": "Перейдите на https://www.gurufocus.com/api/authentication, авторизуйтесь и получите действующий API-ключ",
                    "response_text": response_text
                })
            elif response.status_code == 429:
                status["message"] = "Превышен лимит запросов"
                retry_after = response.headers.get('Retry-After', 'неизвестно')
                status["details"].update({
                    "retry_after": retry_after,
                    "action_required": f"Подождите {retry_after} секунд перед следующим запросом"
                })
            elif response.status_code == 200:
                status["message"] = "API ключ активен"
                status["details"].update({
                    "api_version": response.headers.get('X-API-Version', 'неизвестно'),
                    "rate_limit": response.headers.get('X-RateLimit-Limit', 'неизвестно'),
                    "rate_remaining": response.headers.get('X-RateLimit-Remaining', 'неизвестно')
                })
            else:
                status["message"] = f"Неожиданный статус: {response.status_code}"
                status["details"].update({
                    "response_text": response.text[:200]  # Первые 200 символов ответа
                })

            results.append(status)

        except Exception as e:
            self.logger.error(f"Ошибка при проверке API: {str(e)}")
            results.append({
                "key_type": "Полный ключ",
                "api_key": self.api_key,
                "is_valid": False,
                "status_code": None,
                "message": f"Ошибка при проверке статуса: {str(e)}",
                "details": {"error": str(e)}
            })

        # Определяем, валиден ли ключ
        any_valid = any(result["is_valid"] for result in results)

        # Формируем итоговый результат
        if any_valid:
            return {
                "is_valid": True,
                "message": "API ключ активен",
                "status_code": 200,
                "details": {
                    "key_results": results
                }
            }
        else:
            return {
                "is_valid": False,
                "message": "API ключ недействителен",
                "status_code": None,
                "details": {
                    "key_results": results
                }
            }

    def test_api_request(self, symbol: str) -> str:
        """Тестовый запрос к API с сохранением полного ответа"""
        self.logger.info(f"Выполнение тестового запроса для {symbol}")

        output_path = Path(os.getenv("GURU_OUTPUT_DIR", "output"))
        output_path.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Используем только текстовый файл для результатов
        raw_file = output_path / f"{symbol}_api_raw_{timestamp}.txt"

        # Данные для Excel
        request_info_data = []
        binary_data = []

        # Попробуем все доступные типы запросов для этого тикера
        endpoints = [
            f"stock/{symbol}/key_ratios",
            f"stock/{symbol}/summary",
            f"stock/{symbol}/financials",
            f"stock/{symbol}/price"
        ]

        # Добавляем заголовки для запросов
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9'
        }

        # Открываем файл для записи сырых данных
        with open(raw_file, 'w', encoding='utf-8') as raw_output:
            raw_output.write(f"=== Тестовые запросы API GuruFocus для {symbol} ===\n\n")

            for endpoint in endpoints:
                try:
                    url = f"https://api.gurufocus.com/public/user/{self.api_key}/{endpoint}"
                    self.logger.info(f"Выполняем тестовый запрос к {url}")

                    # Записываем информацию о запросе в текстовый файл
                    raw_output.write(f"\n\n=== ЗАПРОС: {url} ===\n")
                    raw_output.write(f"API ключ: {self.api_key}\n")

                    response = self.session.get(url, headers=headers, timeout=10)

                    # Создаем безопасное имя для файлов с результатами
                    safe_endpoint = endpoint.replace("/", "_").replace(":", "_")

                    # Логируем статус ответа
                    self.logger.info(f"Статус ответа: {response.status_code}")
                    raw_output.write(f"Статус ответа: {response.status_code}\n")
                    raw_output.write(f"Заголовки ответа:\n")
                    for header, value in response.headers.items():
                        raw_output.write(f"  {header}: {value}\n")

                    # Информация о запросе для Excel
                    request_info = {
                        "Endpoint": endpoint,
                        "Статус": response.status_code,
                        "Тип содержимого": response.headers.get("Content-Type", ""),
                        "Размер (байт)": len(response.content),
                        "Время запроса": datetime.now().strftime("%H:%M:%S")
                    }
                    request_info_data.append(request_info)

                    # Определяем тип содержимого
                    content_type = response.headers.get("Content-Type", "")
                    is_json = content_type.startswith("application/json")
                    is_text = content_type.startswith(("text/", "application/json"))

                    # Анализируем содержимое ответа
                    raw_output.write(f"\nТип содержимого: {content_type}\n")
                    raw_output.write(f"Размер содержимого: {len(response.content)} байт\n")

                    # Добавляем подробную информацию о содержимом в зависимости от типа
                    if is_text:
                        # Для текста показываем первые 1000 символов
                        raw_output.write(f"\nСодержимое ответа (первые 1000 символов):\n")
                        text_preview = response.text[:1000] if response.text else "Пустой ответ"
                        raw_output.write(text_preview)

                        # Сохраняем для Excel
                        binary_item = {
                            "Endpoint": endpoint,
                            "Тип": "Текст",
                            "Содержимое (первые 200 символов)": text_preview[:200] + "..." if len(
                                text_preview) > 200 else text_preview
                        }
                        binary_data.append(binary_item)

                    # Всегда добавляем шестнадцатеричный дамп для анализа
                    raw_output.write(f"\n\nДвоичное представление (первые 100 байт):\n")
                    hex_dump = ' '.join(f'{b:02x}' for b in response.content[:100])
                    raw_output.write(hex_dump)

                    # Если не текст, сохраняем HEX для Excel
                    if not is_text:
                        binary_item = {
                            "Endpoint": endpoint,
                            "Тип": "Бинарные данные",
                            "Содержимое (HEX, первые 100 байт)": hex_dump
                        }
                        binary_data.append(binary_item)

                    # Сохраняем бинарные данные в отдельный файл
                    bin_file = output_path / f"{symbol}_{safe_endpoint}_{timestamp}.bin"
                    with open(bin_file, 'wb') as f:
                        f.write(response.content)
                    raw_output.write(f"\n\nСохранено в бинарный файл: {bin_file}\n")
                    self.logger.info(f"Сохранены бинарные данные в {bin_file}")

                    # Если это JSON, пробуем сохранить в отдельный JSON-файл
                    if is_json:
                        try:
                            data = response.json()
                            json_file = output_path / f"{symbol}_{safe_endpoint}_{timestamp}.json"
                            with open(json_file, 'w', encoding='utf-8') as f:
                                json.dump(data, f, indent=2)
                            raw_output.write(f"\nДанные успешно распарсены как JSON и сохранены в: {json_file}\n")
                            self.logger.info(f"Сохранены JSON данные в {json_file}")
                        except json.JSONDecodeError as e:
                            raw_output.write(f"\nОшибка парсинга JSON: {str(e)}\n")
                            self.logger.error(f"Ошибка парсинга JSON: {str(e)}")

                except Exception as e:
                    self.logger.error(f"Ошибка запроса для {endpoint}: {str(e)}")
                    raw_output.write(f"\n\nОшибка запроса: {str(e)}\n")

                    # Добавляем информацию об ошибке в Excel
                    request_info = {
                        "Endpoint": endpoint,
                        "Статус": "Ошибка",
                        "Тип содержимого": "Ошибка",
                        "Размер (байт)": 0,
                        "Время запроса": datetime.now().strftime("%H:%M:%S")
                    }
                    request_info_data.append(request_info)

                    binary_item = {
                        "Endpoint": endpoint,
                        "Тип": "Ошибка",
                        "Содержимое": str(e)
                    }
                    binary_data.append(binary_item)

        # Создаем Excel-файл с результатами
        try:
            # Создаем DataFrame из собранных данных
            summary_df = pd.DataFrame(request_info_data)
            content_df = pd.DataFrame(binary_data)

            # Собираем информацию о созданных файлах
            files_info = []
            for file in output_path.glob(f"{symbol}_*_{timestamp}.*"):
                if file.exists():
                    files_info.append({
                        "Имя файла": file.name,
                        "Размер (байт)": file.stat().st_size,
                        "Путь": str(file)
                    })

            files_df = pd.DataFrame(files_info)

            # Заменяем пустые значения на None в DataFrame
            summary_df = summary_df.fillna("None")
            content_df = content_df.fillna("None")
            files_df = files_df.fillna("None")

            # Создаем простой Excel-файл
            excel_file = output_path / f"{symbol}_api_excel_{timestamp}.xlsx"
            with pd.ExcelWriter(excel_file) as writer:
                summary_df.to_excel(writer, sheet_name="Сводка", index=False)
                content_df.to_excel(writer, sheet_name="Содержимое", index=False)
                files_df.to_excel(writer, sheet_name="Файлы", index=False)

            self.logger.info(f"Excel-файл с результатами создан: {excel_file}")
            return f"Результаты тестирования сохранены в:\n- Текстовый файл: {raw_file}\n- Excel файл: {excel_file}\n- Отдельные файлы для каждого успешного запроса"

        except Exception as e:
            self.logger.error(f"Ошибка при создании Excel: {str(e)}")
            return f"Текстовый файл сохранен: {raw_file}\nНо произошла ошибка при создании Excel: {str(e)}"

    def _get_rating(self, name: str, value: Optional[float]) -> str:
        """Получение рейтинга для метрики"""
        if value is None:
            return "Нет данных"

        if name == "pe_ratio":
            return "Низкий" if value < 15 else "Средний" if value < 25 else "Высокий"
        elif name == "pb_ratio":
            return "Низкий" if value < 1 else "Средний" if value < 3 else "Высокий"
        elif name == "ps_ratio":
            return "Низкий" if value < 1 else "Средний" if value < 3 else "Высокий"
        elif name == "debt_to_equity":
            return "Низкий" if value < 0.5 else "Средний" if value < 1.0 else "Высокий"
        elif name == "current_ratio":
            return "Хороший" if value > 2 else "Средний" if value > 1 else "Низкий"
        elif name == "roe":
            return "Высокий" if value > 15 else "Средний" if value > 10 else "Низкий"
        elif name == "operating_margin":
            return "Высокий" if value > 15 else "Средний" if value > 10 else "Низкий"
        elif name == "revenue_growth":
            return "Высокий" if value > 15 else "Средний" if value > 5 else "Низкий"
        elif name == "earnings_growth":
            return "Высокий" if value > 15 else "Средний" if value > 5 else "Низкий"
        elif name == "dividend_yield":
            return "Высокий" if value > 4 else "Средний" if value > 2 else "Низкий"
        elif name == "payout_ratio":
            return "Низкий" if value < 50 else "Средний" if value < 75 else "Высокий"

        return "Средний"  # Для остальных метрик возвращаем средний рейтинг

    def _get_score(self, name: str, value: Optional[float]) -> float:
        """Получение числового скора для метрики"""
        if value is None:
            return 0.0

        # Базовая система оценки от 0 до 5
        if name == "pe_ratio":
            # Для P/E чем меньше, тем лучше (до определенного предела)
            if value <= 0:  # Отрицательный P/E не является хорошим знаком
                return 0.0
            elif value < 10:
                return 5.0
            elif value < 15:
                return 4.0
            elif value < 20:
                return 3.0
            elif value < 25:
                return 2.0
            elif value < 30:
                return 1.0
            else:
                return 0.0
        elif name == "roe":
            # Для ROE чем больше, тем лучше
            if value <= 0:
                return 0.0
            elif value < 5:
                return 1.0
            elif value < 10:
                return 2.0
            elif value < 15:
                return 3.0
            elif value < 20:
                return 4.0
            else:
                return 5.0
        elif name == "debt_to_equity":
            # Для D/E чем меньше, тем лучше
            if value < 0:
                return 0.0
            elif value < 0.3:
                return 5.0
            elif value < 0.5:
                return 4.0
            elif value < 0.8:
                return 3.0
            elif value < 1.0:
                return 2.0
            elif value < 1.5:
                return 1.0
            else:
                return 0.0

        # По умолчанию используем простую формулу для остальных метрик
        return round(min(max((value / 5), 0), 5), 1)

    def debug_api_response(self, symbol: str):
        """Отладочная функция для анализа структуры ответа API"""
        print(f"\n=== ОТЛАДКА API для {symbol} ===")
        
        endpoints = [f'stock/{symbol}/summary', f'stock/{symbol}/key_ratios']
        
        for endpoint in endpoints:
            print(f"\n--- Анализ {endpoint} ---")
            data = self.make_request(endpoint)
            
            if data:
                print("Структура данных:")
                self._print_structure(data, level=0, max_level=3)
            else:
                print("Нет данных")
    
    def _print_structure(self, obj, level=0, max_level=3):
        """Рекурсивный вывод структуры данных"""
        indent = "  " * level
        
        if level > max_level:
            print(f"{indent}...")
            return
            
        if isinstance(obj, dict):
            print(f"{indent}dict({len(obj)} ключей):")
            for key, value in list(obj.items())[:5]:  # Только первые 5
                print(f"{indent}  '{key}':")
                if isinstance(value, (dict, list)):
                    self._print_structure(value, level + 2, max_level)
                else:
                    print(f"{indent}    {type(value).__name__}: {str(value)[:50]}")
            if len(obj) > 5:
                print(f"{indent}  ... и еще {len(obj) - 5} ключей")
                
        elif isinstance(obj, list):
            print(f"{indent}list({len(obj)} элементов):")
            if obj:
                print(f"{indent}  [0]:")
                self._print_structure(obj[0], level + 2, max_level)
                if len(obj) > 1:
                    print(f"{indent}  ... и еще {len(obj) - 1} элементов")
        else:
            print(f"{indent}{type(obj).__name__}: {str(obj)[:50]}")

    def get_metric_by_path(self, data, path):
        """Получить значение по явному пути (список ключей)"""
        try:
            for key in path:
                data = data[key]
            return data
        except (KeyError, TypeError):
            return "Нет данных"

    def get_required_metrics(self, symbol: str, api_key: str = None):
        """Получить только нужные метрики из summary по документации GuruFocus API"""
        if api_key:
            self.api_key = api_key

        # Очищаем кэш для свежих данных
        import shutil
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(exist_ok=True)

        # Функция для безопасного извлечения значений
        def safe_get_value(data_dict, path_list):
            """Безопасно извлекает значение по пути в словаре"""
            try:
                current = data_dict
                for key in path_list:
                    current = current[key]
                # Дополнительная обработка для словарей с временными данными
                if isinstance(current, dict):
                    # Если это словарь с датами как ключами, берем последнее значение
                    date_keys = [k for k in current.keys() if isinstance(k, str) and '-' in k]
                    if date_keys:
                        latest_date = max(date_keys)
                        return current[latest_date]
                    # Если это словарь с числовыми ключами
                    elif current:
                        return list(current.values())[-1]
                return current
            except (KeyError, TypeError, AttributeError, IndexError):
                return None

        required_metrics = [
            'P/E', 'Forward P/E', 'PEG Ratio', 'Price to Book', 
            'Current Ratio', 'Quick ratio', 'D/E', 'Interest Coverage',
            'Net Margin', 'Operating Margin', 'ROE', 'ROA', 
            'Revenue Growth', 'EPS Growth', 'F-Score'
        ]
        
        found_metrics = {metric: "Нет данных" for metric in required_metrics}

        print(f"\n=== Поиск метрик для {symbol} ===")
        print(f"Используемый API ключ: {self.api_key}")

        # Пробуем разные эндпоинты для получения данных
        endpoints_to_try = [
            f'stock/{symbol}/summary',
            f'stock/{symbol}/keyratios',
            f'stock/{symbol}/key_ratios',
            f'stock/{symbol}/financials'
        ]
        
        raw_data = None
        successful_endpoint = None
        
        for endpoint in endpoints_to_try:
            print(f"\nПробуем эндпоинт: {endpoint}...")
            data = self.make_request(endpoint)
            if data and isinstance(data, dict):
                raw_data = data
                successful_endpoint = endpoint
                print(f"✅ Успешно получены данные из {endpoint}")
                break
            else:
                print(f"❌ Нет данных из {endpoint}")

        if not raw_data:
            print("❌ Не удалось получить данные ни из одного эндпоинта")
            return found_metrics

        # Выводим структуру полученных данных для анализа
        print(f"\n=== АНАЛИЗ СТРУКТУРЫ ДАННЫХ ({successful_endpoint}) ===")
        self._print_structure(raw_data, level=0, max_level=2)

        # Попробуем найти метрики в различных частях структуры данных
        # Список возможных путей для каждой метрики на основе реальной структуры данных
        metric_search_paths = {
            'P/E': [
                ['summary', 'ratio', 'P/E(ttm)', 'value'],
                ['summary', 'ratio', 'PE(NRI)', 'value'],
                ['summary', 'Valuation', 'PE Ratio'],
                ['Valuation Ratio', 'PE Ratio']
            ],
            'Forward P/E': [
                ['summary', 'ratio', 'Forward P/E', 'value'],
                ['summary', 'Valuation', 'Forward PE'],
                ['Valuation Ratio', 'Forward PE']
            ],
            'PEG Ratio': [
                ['summary', 'ratio', 'PEG', 'value'],
                ['summary', 'ratio', 'PEG Ratio', 'value'],
                ['summary', 'Valuation', 'PEG Ratio'],
                ['Valuation Ratio', 'PEG Ratio']
            ],
            'Price to Book': [
                ['summary', 'ratio', 'P/B', 'value'],
                ['summary', 'ratio', 'Price to Book', 'value'],
                ['summary', 'Valuation', 'PB Ratio'],
                ['Valuation Ratio', 'PB Ratio']
            ],
            'Current Ratio': [
                ['summary', 'ratio', 'Current Ratio', 'value'],
                ['summary', 'Financial Strength', 'Current Ratio'],
                ['Financial Strength', 'Current Ratio']
            ],
            'Quick ratio': [
                ['summary', 'ratio', 'Quick Ratio', 'value'],
                ['summary', 'ratio', 'Acid Test Ratio', 'value'],
                ['summary', 'Financial Strength', 'Quick Ratio'],
                ['Financial Strength', 'Quick Ratio']
            ],
            'D/E': [
                ['summary', 'ratio', 'Debt-to-Equity', 'value'],
                ['summary', 'ratio', 'Debt to Equity', 'value'],
                ['summary', 'Financial Strength', 'Debt-to-Equity'],
                ['Financial Strength', 'Debt-to-Equity']
            ],
            'Interest Coverage': [
                ['summary', 'ratio', 'Interest Coverage', 'value'],
                ['summary', 'Financial Strength', 'Interest Coverage'],
                ['Financial Strength', 'Interest Coverage']
            ],
            'Net Margin': [
                ['summary', 'ratio', 'Net-margin (%)', 'value'],
                ['summary', 'ratio', 'Net Margin (%)', 'value'],
                ['summary', 'ratio', 'Net Margin', 'value'],
                ['summary', 'Profitability', 'Net Margin'],
                ['Profitability', 'Net Margin']
            ],
            'Operating Margin': [
                ['summary', 'ratio', 'Operating margin (%)', 'value'],
                ['summary', 'ratio', 'Operating Margin (%)', 'value'],
                ['summary', 'ratio', 'Operating Margin', 'value'],
                ['summary', 'Profitability', 'Operating Margin'],
                ['Profitability', 'Operating Margin']
            ],
            'ROE': [
                ['summary', 'ratio', 'ROE (%)', 'value'],
                ['summary', 'ratio', 'Return on Equity', 'value'],
                ['summary', 'ratio', 'ROE', 'value'],
                ['summary', 'Profitability', 'ROE'],
                ['Profitability', 'ROE']
            ],
            'ROA': [
                ['summary', 'ratio', 'ROA (%)', 'value'],
                ['summary', 'ratio', 'Return on Assets', 'value'],
                ['summary', 'ratio', 'ROA', 'value'],
                ['summary', 'Profitability', 'ROA'],
                ['Profitability', 'ROA']
            ],
            'Revenue Growth': [
                ['summary', 'ratio', 'Revenue Growth (%)', 'value'],
                ['summary', 'ratio', 'Revenue Growth', 'value'],
                ['summary', 'Growth', 'Revenue Growth'],
                ['Growth', 'Revenue Growth']
            ],
            'EPS Growth': [
                ['summary', 'ratio', 'EPS Growth (%)', 'value'],
                ['summary', 'ratio', 'EPS Growth', 'value'],
                ['summary', 'ratio', 'Earnings Growth', 'value'],
                ['summary', 'Growth', 'EPS Growth'],
                ['Growth', 'EPS Growth']
            ],
            'F-Score': [
                ['summary', 'ratio', 'F-Score', 'value'],
                ['summary', 'ratio', 'Piotroski F-Score', 'value'],
                ['summary', 'Quality', 'F-Score'],
                ['Quality', 'F-Score']
            ]
        }

        print(f"\n=== ПОИСК МЕТРИК ===")
        
        for metric_name in required_metrics:
            found_value = None
            found_path = None
            
            # Перебираем все возможные пути для данной метрики
            for path in metric_search_paths.get(metric_name, []):
                value = safe_get_value(raw_data, path)
                if value is not None and value not in ["N/A", "", "None", "null"]:
                    found_value = value
                    found_path = path
                    break
            
            if found_value is not None:
                found_metrics[metric_name] = found_value
                print(f"  ✅ {metric_name}: {found_value} (путь: {' -> '.join(found_path)})")
            else:
                print(f"  ❌ {metric_name}: Нет данных")

        # Выводим итоговые результаты
        print(f"\n=== ИТОГОВЫЕ МЕТРИКИ ДЛЯ {symbol} ===")
        for metric, value in found_metrics.items():
            print(f"{metric}: {value}")

        # Сохраняем результаты и сырые данные
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Сохраняем в Excel
        excel_path = Path.cwd() / f"metrics_{symbol}_{timestamp}.xlsx"
        df = pd.DataFrame([{**{"Тикер": symbol}, **found_metrics}])
        df.to_excel(excel_path, index=False)
        print(f"\n✅ Результаты сохранены: {excel_path}")
        
        # Сохраняем сырые данные для анализа
        raw_json_path = Path.cwd() / f"raw_data_{symbol}_{timestamp}.json"
        with open(raw_json_path, 'w', encoding='utf-8') as f:
            json.dump(raw_data, f, indent=2, ensure_ascii=False)
        print(f"✅ Сырые данные сохранены: {raw_json_path}")
        
        return found_metrics

    def analyze_api_structure(self, symbol: str):
        """Детальный анализ структуры данных API для понимания доступных метрик"""
        print(f"\n=== ДЕТАЛЬНЫЙ АНАЛИЗ API СТРУКТУРЫ ДЛЯ {symbol} ===")
        
        # Список всех возможных эндпоинтов для анализа
        endpoints_to_analyze = [
            f'stock/{symbol}/summary',
            f'stock/{symbol}/keyratios', 
            f'stock/{symbol}/key_ratios',
            f'stock/{symbol}/financials',
            f'stock/{symbol}/valuation',
            f'stock/{symbol}/profitability',
            f'stock/{symbol}/growth',
            f'stock/{symbol}/dividend'
        ]
        
        results = {}
        
        for endpoint in endpoints_to_analyze:
            print(f"\n--- Анализ эндпоинта: {endpoint} ---")
            data = self.make_request(endpoint)
            
            if data and isinstance(data, dict):
                print(f"✅ Получены данные ({len(data)} ключей верхнего уровня)")
                results[endpoint] = data
                
                # Выводим структуру данных
                self._print_structure(data, level=0, max_level=3)
                
                # Ищем потенциальные метрики
                potential_metrics = self._find_potential_metrics(data)
                if potential_metrics:
                    print(f"\n🔍 Найденные потенциальные метрики:")
                    for metric, value in potential_metrics.items():
                        print(f"  - {metric}: {value}")
                
            else:
                print(f"❌ Нет данных или неверный формат")
        
        # Сохраняем результаты анализа
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        analysis_file = Path.cwd() / f"api_structure_analysis_{symbol}_{timestamp}.json"
        
        with open(analysis_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Результаты анализа сохранены в: {analysis_file}")
        return results
    
    def _find_potential_metrics(self, data, prefix="", max_depth=3):
        """Рекурсивно ищет потенциальные метрики в структуре данных"""
        metrics = {}
        
        if max_depth <= 0:
            return metrics
            
        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{prefix}.{key}" if prefix else key
                
                # Если значение - число, это потенциальная метрика
                if isinstance(value, (int, float)) and value != 0:
                    metrics[current_path] = value
                    
                # Если значение - строка, которая может быть числом
                elif isinstance(value, str):
                    try:
                        num_value = float(value.replace('%', '').replace(',', ''))
                        metrics[current_path] = num_value
                    except (ValueError, AttributeError):
                        pass
                        
                # Рекурсивно ищем в подструктурах
                elif isinstance(value, dict) and max_depth > 1:
                    sub_metrics = self._find_potential_metrics(value, current_path, max_depth - 1)
                    metrics.update(sub_metrics)
                    
        return metrics

    def compare_endpoints(self, symbol: str):
        """Сравнение данных от разных эндпоинтов API для понимания различий"""
        print(f"\n=== СРАВНЕНИЕ ЭНДПОИНТОВ API ДЛЯ {symbol} ===")
        
        # Основные эндпоинты для сравнения
        endpoints = {
            'summary': f'stock/{symbol}/summary',
            'keyratios': f'stock/{symbol}/keyratios',
            'key_ratios': f'stock/{symbol}/key_ratios',
            'financials': f'stock/{symbol}/financials'
        }
        
        endpoint_data = {}
        
        # Получаем данные от каждого эндпоинта
        for name, endpoint in endpoints.items():
            print(f"\n--- Тестирование {name} ({endpoint}) ---")
            data = self.make_request(endpoint)
            
            if data:
                endpoint_data[name] = data
                print(f"✅ Получены данные: {type(data)}, размер: {len(str(data))} символов")
                
                # Показываем основную структуру
                if isinstance(data, dict):
                    print(f"   Ключи верхнего уровня: {list(data.keys())}")
                    
                    # Ищем числовые значения (потенциальные метрики)
                    metrics_found = self._count_numeric_values(data)
                    print(f"   Найдено числовых значений: {metrics_found}")
                    
            else:
                print(f"❌ Нет данных")
        
        # Анализ различий
        if len(endpoint_data) > 1:
            print(f"\n=== АНАЛИЗ РАЗЛИЧИЙ ===")
            
            # Сравниваем размеры данных
            sizes = {name: len(str(data)) for name, data in endpoint_data.items()}
            print(f"Размеры данных: {sizes}")
            
            # Находим общие ключи
            all_keys = {}
            for name, data in endpoint_data.items():
                if isinstance(data, dict):
                    all_keys[name] = set(self._get_all_keys(data))
            
            if len(all_keys) > 1:
                common_keys = set.intersection(*all_keys.values())
                print(f"Общие ключи: {len(common_keys)} - {list(common_keys)[:10]}")
                
                # Уникальные ключи для каждого эндпоинта
                for name, keys in all_keys.items():
                    unique = keys - set().union(*[k for n, k in all_keys.items() if n != name])
                    if unique:
                        print(f"Уникальные ключи для {name}: {len(unique)} - {list(unique)[:10]}")
        
        # Сохраняем результаты сравнения
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        comparison_file = Path.cwd() / f"endpoint_comparison_{symbol}_{timestamp}.json"
        
        with open(comparison_file, 'w', encoding='utf-8') as f:
            json.dump(endpoint_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Результаты сравнения сохранены в: {comparison_file}")
        return endpoint_data
    
    def _count_numeric_values(self, data, count=0):
        """Рекурсивно считает числовые значения в структуре данных"""
        if isinstance(data, dict):
            for value in data.values():
                count = self._count_numeric_values(value, count)
        elif isinstance(data, list):
            for item in data:
                count = self._count_numeric_values(item, count)
        elif isinstance(data, (int, float)):
            count += 1
        elif isinstance(data, str):
            try:
                float(data.replace('%', '').replace(',', ''))
                count += 1
            except (ValueError, AttributeError):
                pass
        return count
    
    def _get_all_keys(self, data, keys=None):
        """Рекурсивно получает все ключи из структуры данных"""
        if keys is None:
            keys = set()
            
        if isinstance(data, dict):
            keys.update(data.keys())
            for value in data.values():
                if isinstance(value, dict):
                    self._get_all_keys(value, keys)
        return keys

    def run_comprehensive_tests(self, test_symbol: str = "AAPL"):
        """Комплексное тестирование всех компонентов системы"""
        print(f"\n{'='*60}")
        print("🔧 КОМПЛЕКСНАЯ ДИАГНОСТИКА СИСТЕМЫ")
        print(f"{'='*60}")
        print(f"Тестовый тикер: {test_symbol}")
        print(f"API ключ: {self.api_key[:20]}...")
        
        test_results = {
            "api_connectivity": False,
            "data_retrieval": False,
            "data_parsing": False,
            "metric_extraction": False,
            "file_operations": False,
            "caching": False,
            "error_handling": False
        }
        
        total_tests = len(test_results)
        passed_tests = 0
        
        # 1. Тест подключения к API
        print(f"\n1️⃣ Тестирование подключения к API...")
        try:
            response = self.session.get(
                f"https://api.gurufocus.com/public/user/{self.api_key}/stock/{test_symbol}/summary",
                timeout=10
            )
            if response.status_code == 200:
                test_results["api_connectivity"] = True
                passed_tests += 1
                print("   ✅ Подключение к API работает")
            else:
                print(f"   ❌ API вернул статус: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Ошибка подключения: {str(e)[:100]}")
        
        # 2. Тест получения данных
        print(f"\n2️⃣ Тестирование получения данных...")
        test_data = None
        try:
            test_data = self.make_request(f"stock/{test_symbol}/summary")
            if test_data and isinstance(test_data, dict) and len(test_data) > 0:
                test_results["data_retrieval"] = True
                passed_tests += 1
                print(f"   ✅ Данные получены: {len(test_data)} ключей верхнего уровня")
            else:
                print("   ❌ Не удалось получить валидные данные")
        except Exception as e:
            print(f"   ❌ Ошибка получения данных: {str(e)[:100]}")
        
        # 3. Тест парсинга данных
        print(f"\n3️⃣ Тестирование парсинга данных...")
        try:
            if test_data:
                # Проверяем структуру данных
                if 'summary' in test_data and isinstance(test_data['summary'], dict):
                    test_results["data_parsing"] = True
                    passed_tests += 1
                    print("   ✅ Структура данных корректна")
                else:
                    print(f"   ❌ Неожиданная структура: {list(test_data.keys())}")
            else:
                print("   ⚠️  Нет данных для парсинга")
        except Exception as e:
            print(f"   ❌ Ошибка парсинга: {str(e)[:100]}")
        
        # 4. Тест извлечения метрик
        print(f"\n4️⃣ Тестирование извлечения метрик...")
        extracted_metrics = 0
        try:
            if test_data:
                # Пробуем найти хотя бы одну метрику
                metrics = self._find_potential_metrics(test_data, max_depth=3)
                extracted_metrics = len(metrics)
                if extracted_metrics > 0:
                    test_results["metric_extraction"] = True
                    passed_tests += 1
                    print(f"   ✅ Извлечено {extracted_metrics} потенциальных метрик")
                    # Показываем первые 5 найденных метрик
                    for i, (key, value) in enumerate(list(metrics.items())[:5]):
                        print(f"      - {key}: {value}")
                    if extracted_metrics > 5:
                        print(f"      ... и еще {extracted_metrics - 5}")
                else:
                    print("   ❌ Не найдено ни одной метрики")
            else:
                print("   ⚠️  Нет данных для извлечения метрик")
        except Exception as e:
            print(f"   ❌ Ошибка извлечения метрик: {str(e)[:100]}")
        
        # 5. Тест файловых операций
        print(f"\n5️⃣ Тестирование файловых операций...")
        try:
            # Тест создания временного файла
            test_data_simple = {"test": "data", "number": 123}
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data_simple, f)
                temp_file = f.name
            
            # Проверяем чтение
            with open(temp_file, 'r') as f:
                loaded_data = json.load(f)
            
            if loaded_data == test_data_simple:
                test_results["file_operations"] = True
                passed_tests += 1
                print("   ✅ Файловые операции работают")
            
            # Удаляем временный файл
            Path(temp_file).unlink()
            
        except Exception as e:
            print(f"   ❌ Ошибка файловых операций: {str(e)[:100]}")
        
        # 6. Тест кэширования
        print(f"\n6️⃣ Тестирование кэширования...")
        try:
            test_endpoint = f"stock/{test_symbol}/summary"
            
            # Очищаем кэш
            cache_path = self.get_cache_path(test_endpoint)
            if cache_path.exists():
                cache_path.unlink()
            
            # Первый запрос (должен создать кэш)
            data1 = self.make_request(test_endpoint)
            cache_exists_after_first = cache_path.exists()
            
            # Второй запрос (должен использовать кэш)
            data2 = self.make_request(test_endpoint)
            
            if cache_exists_after_first and data1 == data2:
                test_results["caching"] = True
                passed_tests += 1
                print("   ✅ Кэширование работает корректно")
            else:
                print("   ❌ Проблемы с кэшированием")
                
        except Exception as e:
            print(f"   ❌ Ошибка тестирования кэша: {str(e)[:100]}")
        
        # 7. Тест обработки ошибок
        print(f"\n7️⃣ Тестирование обработки ошибок...")
        try:
            # Тест с недействительным тикером
            invalid_data = self.make_request("stock/INVALID_TICKER_123/summary")
            
            # Тест с недействительным эндпоинтом
            invalid_endpoint = self.make_request("invalid/endpoint/test")
            
            # Если мы дошли до этой точки без исключений, обработка ошибок работает
            test_results["error_handling"] = True
            passed_tests += 1
            print("   ✅ Обработка ошибок работает")
            
        except Exception as e:
            # Это нормально - мы ожидаем некоторые ошибки
            test_results["error_handling"] = True
            passed_tests += 1
            print("   ✅ Обработка ошибок работает (перехвачены ожидаемые ошибки)")
        
        # Итоги тестирования
        print(f"\n{'='*60}")
        print("📊 РЕЗУЛЬТАТЫ ДИАГНОСТИКИ")
        print(f"{'='*60}")
        
        success_rate = (passed_tests / total_tests) * 100
        print(f"Пройдено тестов: {passed_tests}/{total_tests} ({success_rate:.1f}%)")
        
        if success_rate >= 80:
            status = "🟢 ОТЛИЧНО"
        elif success_rate >= 60:
            status = "🟡 УДОВЛЕТВОРИТЕЛЬНО"
        else:
            status = "🔴 ТРЕБУЕТ ВНИМАНИЯ"
        
        print(f"Общая оценка: {status}")
        
        print(f"\nДетальные результаты:")
        for test_name, result in test_results.items():
            icon = "✅" if result else "❌"
            print(f"  {icon} {test_name.replace('_', ' ').title()}")
        
        # Рекомендации
        print(f"\n🔧 РЕКОМЕНДАЦИИ:")
        
        if not test_results["api_connectivity"]:
            print("  • Проверьте интернет-соединение и API ключ")
        
        if not test_results["data_retrieval"]:
            print("  • Проверьте правильность API ключа и доступность эндпоинтов")
        
        if not test_results["metric_extraction"]:
            print("  • Структура данных API могла измениться, требуется обновление")
        
        if extracted_metrics > 0:
            print(f"  • Найдено {extracted_metrics} потенциальных метрик - можно улучшить извлечение")
        
        if success_rate < 100:
            print("  • Запустите пункт 5 (Детальный анализ) для изучения структуры данных")
        
        return test_results

    def diagnose_metric_extraction(self, symbol: str):
        """Специализированная диагностика проблем с извлечением метрик"""
        print(f"\n🔍 ДИАГНОСТИКА ИЗВЛЕЧЕНИЯ МЕТРИК ДЛЯ {symbol}")
        print("="*50)
        
        # Получаем данные
        data = self.make_request(f"stock/{symbol}/summary")
        if not data:
            print("❌ Не удалось получить данные от API")
            return
        
        print(f"✅ Получены данные от API")
        
        # Анализируем структуру
        print(f"\n📊 АНАЛИЗ СТРУКТУРЫ ДАННЫХ:")
        print(f"Тип данных: {type(data)}")
        print(f"Размер данных: {len(str(data))} символов")
        
        if isinstance(data, dict):
            print(f"Ключи верхнего уровня: {list(data.keys())}")
            
            # Детальный анализ каждого ключа
            for key, value in data.items():
                print(f"\n📁 Анализ ключа '{key}':")
                print(f"   Тип: {type(value)}")
                
                if isinstance(value, dict):
                    print(f"   Подключи: {list(value.keys())[:10]}")
                    if len(value) > 10:
                        print(f"   ... и еще {len(value) - 10}")
                    
                    # Ищем числовые значения в этом разделе
                    metrics_in_section = self._find_potential_metrics(value, max_depth=2)
                    print(f"   Найдено метрик: {len(metrics_in_section)}")
                    
                    if metrics_in_section:
                        print("   Примеры метрик:")
                        for i, (metric_key, metric_value) in enumerate(list(metrics_in_section.items())[:5]):
                            print(f"     - {metric_key}: {metric_value}")
                        if len(metrics_in_section) > 5:
                            print(f"     ... и еще {len(metrics_in_section) - 5}")
                
                elif isinstance(value, list):
                    print(f"   Элементов в списке: {len(value)}")
                    if value:
                        print(f"   Тип первого элемента: {type(value[0])}")
                else:
                    print(f"   Значение: {str(value)[:100]}")
        
        # Тестируем наши поисковые пути
        print(f"\n🎯 ТЕСТИРОВАНИЕ ПУТЕЙ ПОИСКА МЕТРИК:")
        
        test_metrics = {
            'P/E': [
                ['summary', 'Valuation', 'PE Ratio'],
                ['Valuation Ratio', 'PE Ratio'],
                ['PE Ratio']
            ],
            'ROE': [
                ['summary', 'Profitability', 'ROE'],
                ['Profitability', 'ROE'],
                ['ROE']
            ],
            'Current Ratio': [
                ['summary', 'Financial Strength', 'Current Ratio'],
                ['Financial Strength', 'Current Ratio'],
                ['Current Ratio']
            ]
        }
        
        for metric_name, paths in test_metrics.items():
            print(f"\n🔍 Поиск {metric_name}:")
            found = False
            
            for path in paths:
                try:
                    current = data
                    for key in path:
                        current = current[key]
                    
                    print(f"   ✅ Найден по пути {' -> '.join(path)}: {current}")
                    found = True
                    break
                    
                except (KeyError, TypeError):
                    print(f"   ❌ Не найден по пути: {' -> '.join(path)}")
            
            if not found:
                print(f"   ⚠️  {metric_name} не найден ни по одному пути")
        
        # Предлагаем альтернативные пути
        print(f"\n💡 ПОИСК АЛЬТЕРНАТИВНЫХ ПУТЕЙ:")
        all_metrics = self._find_potential_metrics(data, max_depth=4)
        
        target_keywords = ['pe', 'ratio', 'roe', 'current', 'debt', 'margin', 'yield']
        
        for keyword in target_keywords:
            matching_metrics = {k: v for k, v in all_metrics.items() 
                              if keyword.lower() in k.lower()}
            
            if matching_metrics:
                print(f"\n🏷️  Метрики содержащие '{keyword}':")
                for key, value in list(matching_metrics.items())[:3]:
                    print(f"   - {key}: {value}")
                if len(matching_metrics) > 3:
                    print(f"   ... и еще {len(matching_metrics) - 3}")
        
        # Итоговые рекомендации
        print(f"\n📋 РЕКОМЕНДАЦИИ:")
        
        total_metrics = len(all_metrics)
        if total_metrics > 0:
            print(f"✅ В данных найдено {total_metrics} потенциальных метрик")
            print("   Рекомендация: Обновить пути поиска на основе найденных структур")
        else:
            print("❌ Не найдено числовых метрик в данных")
            print("   Возможные причины:")
            print("   • Данные в текстовом формате вместо числового")
            print("   • Метрики находятся глубже чем 4 уровня вложенности")
            print("   • API изменил структуру данных")
        
        return all_metrics

    def auto_update_metric_paths(self, symbol: str):
        """Автоматическое обновление путей поиска метрик на основе реальной структуры данных"""
        print(f"\n🤖 АВТОМАТИЧЕСКОЕ ОБНОВЛЕНИЕ ПУТЕЙ МЕТРИК ДЛЯ {symbol}")
        print("="*60)
        
        # Получаем данные
        data = self.make_request(f"stock/{symbol}/summary")
        if not data:
            print("❌ Не удалось получить данные от API")
            return None
        
        # Находим все потенциальные метрики
        all_metrics = self._find_potential_metrics(data, max_depth=5)
        print(f"✅ Найдено {len(all_metrics)} потенциальных метрик")
        
        # Определяем целевые метрики и ключевые слова для их поиска
        target_metrics = {
            'P/E': ['pe', 'price.*earnings', 'earnings.*ratio'],
            'Forward P/E': ['forward.*pe', 'forward.*price.*earnings'],
            'Div. yield': ['dividend.*yield', 'div.*yield', 'yield'],
            'PEG Ratio': ['peg', 'price.*earnings.*growth'],
            'Price to Book': ['pb', 'price.*book', 'book.*value'],
            'Payout Ratio': ['payout', 'dividend.*payout'],
            'Beta (5y)': ['beta', 'beta.*5y', 'beta.*five'],
            'Net Margin': ['net.*margin', 'margin.*net'],
            'D/E': ['debt.*equity', 'debt.*to.*equity', 'leverage'],
            'Quick ratio': ['quick.*ratio', 'acid.*test'],
            'Current Ratio': ['current.*ratio', 'liquidity.*ratio'],
            'ROE': ['roe', 'return.*equity'],
            'Altman Z-Score': ['altman', 'z.*score'],
            'Beneish M-Score': ['beneish', 'm.*score']
        }
        
        updated_paths = {}
        
        print(f"\n🔍 ПОИСК СООТВЕТСТВИЙ:")
        
        for metric_name, keywords in target_metrics.items():
            print(f"\n📊 Анализ метрики: {metric_name}")
            
            best_matches = []
            
            # Ищем соответствия по ключевым словам
            for metric_path, value in all_metrics.items():
                for keyword in keywords:
                    import re
                    if re.search(keyword, metric_path.lower()):
                        confidence = self._calculate_match_confidence(metric_path, keywords)
                        best_matches.append((metric_path, value, confidence))
                        break
            
            # Сортируем по уровню соответствия
            best_matches.sort(key=lambda x: x[2], reverse=True)
            
            if best_matches:
                best_match = best_matches[0]
                path_parts = best_match[0].split('.')
                updated_paths[metric_name] = path_parts
                
                print(f"   ✅ Найдено соответствие:")
                print(f"      Путь: {' -> '.join(path_parts)}")
                print(f"      Значение: {best_match[1]}")
                print(f"      Уверенность: {best_match[2]:.1%}")
                
                if len(best_matches) > 1:
                    print(f"   📋 Альтернативы:")
                    for i, (path, value, conf) in enumerate(best_matches[1:3]):
                        print(f"      {i+2}. {path.split('.')[-1]}: {value} ({conf:.1%})")
            else:
                print(f"   ❌ Соответствие не найдено")
        
        # Генерируем код для обновления
        if updated_paths:
            print(f"\n💾 ПРЕДЛАГАЕМЫЕ ОБНОВЛЕНИЯ:")
            print("="*50)
            print("# Обновленные пути поиска метрик:")
            print("metric_search_paths = {")
            
            for metric_name, path in updated_paths.items():
                path_str = "[" + ", ".join([f"'{p}'" for p in path]) + "]"
                print(f"    '{metric_name}': [{path_str}],")
            
            print("}")
            
            # Сохраняем в файл
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            update_file = Path.cwd() / f"metric_paths_update_{symbol}_{timestamp}.py"
            
            with open(update_file, 'w', encoding='utf-8') as f:
                f.write(f"# Автоматически сгенерированные пути метрик для {symbol}\n")
                f.write(f"# Сгенерировано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("updated_metric_search_paths = {\n")
                
                for metric_name, path in updated_paths.items():
                    path_str = "[" + ", ".join([f"'{p}'" for p in path]) + "]"
                    f.write(f"    '{metric_name}': [{path_str}],\n")
                
                f.write("}\n")
            
            print(f"\n✅ Обновления сохранены в: {update_file}")
            
            # Тестируем новые пути
            print(f"\n🧪 ТЕСТИРОВАНИЕ НОВЫХ ПУТЕЙ:")
            test_results = {}
            
            for metric_name, path in updated_paths.items():
                try:
                    current = data
                    for key in path:
                        current = current[key]
                    test_results[metric_name] = current
                    print(f"   ✅ {metric_name}: {current}")
                except (KeyError, TypeError) as e:
                    test_results[metric_name] = f"Ошибка: {e}"
                    print(f"   ❌ {metric_name}: Ошибка извлечения")
            
            success_rate = len([v for v in test_results.values() 
                              if not str(v).startswith("Ошибка")]) / len(test_results)
            
            print(f"\n📊 Успешность новых путей: {success_rate:.1%}")
            
            return updated_paths
        
        else:
            print(f"\n❌ Не удалось найти соответствия для метрик")
            print("   Возможные причины:")
            print("   • Структура данных API кардинально изменилась")
            print("   • Метрики имеют нестандартные названия")
            print("   • Требуется ручная настройка путей")
            
            return None
    
    def _calculate_match_confidence(self, metric_path: str, keywords: list) -> float:
        """Вычисляет уровень соответствия метрики ключевым словам"""
        import re
        
        path_lower = metric_path.lower()
        confidence = 0.0
        
        # Базовое соответствие
        for keyword in keywords:
            if re.search(keyword, path_lower):
                confidence += 0.3
                
                # Бонус за точное совпадение
                if keyword in path_lower:
                    confidence += 0.2
                
                # Бонус за нахождение в конце пути (название метрики)
                if path_lower.endswith(keyword):
                    confidence += 0.3
        
        # Штраф за очень длинный путь
        path_depth = len(metric_path.split('.'))
        if path_depth > 4:
            confidence *= 0.8
        
        # Бонус за распространенные финансовые термины
        financial_terms = ['ratio', 'margin', 'yield', 'return', 'debt', 'equity']
        for term in financial_terms:
            if term in path_lower:
                confidence += 0.1
        
        return min(confidence, 1.0)  # Максимум 100%


def test_gurufocus_example(symbol: str = "WMT", api_key: str = None):
    """
    Тестовая функция на основе официального примера GuruFocus API
    Исправлена для работы с Brotli сжатием и правильной декодировки
    """
    import urllib.request
    import json
    import gzip
    import brotli  # Нужно установить: pip install brotli
    
    # Используем переданный API ключ или дефолтный
    if not api_key:
        api_key = os.getenv("GURUFOCUS_API_KEY", "")
    
    # Правильный URL согласно официальной документации
    url = f'https://api.gurufocus.com/public/user/{api_key}/stock/{symbol}/keyratios'
    
    print(f"=== Тест официального примера GuruFocus для {symbol} ===")
    print(f"URL: {url}")
    print(f"API ключ: {api_key}")
    
    try:
        # Создаем запрос с правильными заголовками
        req = urllib.request.Request(
            url=url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive'
            }
        )
        
        print("Выполняем запрос...")
        response = urllib.request.urlopen(req)
        
        print(f"Статус ответа: {response.getcode()}")
        print(f"Заголовки ответа:")
        for header, value in response.headers.items():
            print(f"  {header}: {value}")
        
        content = response.read()
        print(f"Размер сжатого ответа: {len(content)} байт")
        
        # Определяем тип сжатия и декодируем
        content_encoding = response.headers.get('Content-Encoding', '').lower()
        print(f"Тип сжатия: {content_encoding}")
        
        try:
            if content_encoding == 'br':
                try:
                    # Декодируем Brotli
                    import brotli
                    content = brotli.decompress(content)
                    print(f"Размер после Brotli декодирования: {len(content)} байт")
                except ImportError:
                    print("⚠️ Brotli не установлен, используем содержимое как есть")
            elif content_encoding == 'gzip':
                # Декодируем Gzip
                import gzip
                content = gzip.decompress(content)
                print(f"Размер после Gzip декодирования: {len(content)} байт")
            
            # Декодируем в строку
            text_content = content.decode('utf-8')
            print(f"Размер текста: {len(text_content)} символов")
            
            # Проверяем, что получили
            if not text_content.strip():
                print("⚠️  Получен пустой ответ")
                return None
            
            print("Первые 200 символов ответа:")
            print(text_content[:200])
            
        except Exception as decode_error:
            print(f"Ошибка декодирования: {decode_error}")
            # Попробуем декодировать как есть
            try:
                text_content = content.decode('utf-8', errors='ignore')
                print("Декодировано с игнорированием ошибок")
            except:
                print("Не удалось декодировать содержимое")
                return None
        
        # Пытаемся декодировать JSON
        try:
            data = json.loads(text_content)
            print("✅ JSON успешно декодирован!")
            
            # Показываем структуру данных
            print(f"\nСтруктура данных:")
            if isinstance(data, dict):
                print(f"Тип: словарь с {len(data)} ключами")
                for key in data.keys():
                    print(f"  - {key}")
                    if key == 'Valuation Ratio' and isinstance(data[key], dict):
                        for subkey in data[key].keys():
                            print(f"    - {subkey}")
            elif isinstance(data, list):
                print(f"Тип: список с {len(data)} элементами")
                if len(data) > 0:
                    print(f"Первый элемент: {type(data[0])}")
            
            # Пытаемся получить PS Ratio как в официальном примере
            try:
                if isinstance(data, dict) and 'Valuation Ratio' in data:
                    ps_ratio = data['Valuation Ratio']['PS Ratio']
                    print(f"\n✅ PS Ratio для {symbol}: {ps_ratio}")
                else:
                    print(f"\n⚠️  Структура данных отличается от ожидаемой")
                
            except KeyError as e:
                print(f"⚠️  Не найден ключ {e} в структуре данных")
            
            # Сохраняем полные данные в файл
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            json_file = Path(os.getenv("GURU_OUTPUT_DIR", "output")) / f"gurufocus_example_{symbol}_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"✅ Полные данные сохранены в: {json_file}")
            
            return data
                
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка декодирования JSON: {e}")
            print("Первые 500 символов ответа:")
            print(repr(text_content[:500]))
            
            # Сохраняем сырой ответ
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            raw_file = Path(os.getenv("GURU_OUTPUT_DIR", "output")) / f"gurufocus_raw_{symbol}_{timestamp}.txt"
            with open(raw_file, 'w', encoding='utf-8') as f:
                f.write(text_content)
            print(f"Сырой ответ сохранен в: {raw_file}")
            return None
            
    except ImportError:
        print("❌ Ошибка: необходимо установить библиотеку brotli")
        print("Выполните: pip install brotli")
        return None
        
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP ошибка: {e.code} - {e.reason}")
        if e.code == 403:
            print("403 Forbidden - возможные причины:")
            print("1. API ключ недействителен или заблокирован")
            print("2. IP адрес не в whitelist")
            print("3. Превышен лимит запросов")
        elif e.code == 401:
            print("401 Unauthorized - неверный API ключ")
        return None
        
    except urllib.error.URLError as e:
        print(f"❌ URL ошибка: {e.reason}")
        return None
        
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    print("=== GuruFocus API - Получение метрик ===")
    
    try:
        # Используем фиксированный API ключ
        api = GuruFocusAPI()
            
        while True:
            print("\nВыберите действие:")
            print("1. Получить нужные метрики для акции")
            print("2. Тест API ключа")
            print("3. Тест официального примера GuruFocus (urllib)")
            print("4. ОТЛАДКА: Анализ структуры ответа API")
            print("5. НОВОЕ: Детальный анализ структуры API")
            print("6. НОВОЕ: Сравнение эндпоинтов API")
            print("7. 🔧 КОМПЛЕКСНАЯ ДИАГНОСТИКА СИСТЕМЫ")
            print("8. 🔍 ДИАГНОСТИКА ИЗВЛЕЧЕНИЯ МЕТРИК")
            print("9. 🤖 АВТООБНОВЛЕНИЕ ПУТЕЙ МЕТРИК")
            print("q. Выход")
            choice = input("\nВаш выбор: ").lower()

            if choice == 'q':
                break
            elif choice == '1':
                symbol = input("\nВведите тикер акции: ").upper()
                if symbol:
                    api.get_required_metrics(symbol)
                else:
                    print("Введите корректный тикер!")
            elif choice == '2':
                print("\nТестирование API ключа...")
                test_symbol = "AAPL"
                data = api.make_request(f"stock/{test_symbol}/summary")
                if data:
                    print(f"API ключ работает!")
                    print(f"Получены данные для {test_symbol}")
                else:
                    print(f"API ключ не работает")
            elif choice == '3':
                symbol = input("\nВведите тикер для теста (по умолчанию WMT): ").upper()
                if not symbol:
                    symbol = "WMT"
                print(f"\nТестирование официального примера для {symbol}...")
                test_gurufocus_example(symbol)
            elif choice == '4':
                symbol = input("\nВведите тикер для отладки: ").upper()
                if symbol:
                    api.debug_api_response(symbol)
                else:
                    print("Введите корректный тикер!")
            elif choice == '5':
                symbol = input("\nВведите тикер для детального анализа API: ").upper()
                if symbol:
                    api.analyze_api_structure(symbol)
                else:
                    print("Введите корректный тикер!")
            elif choice == '6':
                symbol = input("\nВведите тикер для сравнения эндпоинтов: ").upper()
                if symbol:
                    api.compare_endpoints(symbol)
                else:
                    print("Введите корректный тикер!")
            elif choice == '7':
                symbol = input("\nВведите тикер для комплексной диагностики (по умолчанию AAPL): ").upper()
                if not symbol:
                    symbol = "AAPL"
                api.run_comprehensive_tests(symbol)
            elif choice == '8':
                symbol = input("\nВведите тикер для диагностики метрик: ").upper()
                if symbol:
                    api.diagnose_metric_extraction(symbol)
                else:
                    print("Введите корректный тикер!")
            elif choice == '9':
                symbol = input("\nВведите тикер для автообновления путей: ").upper()
                if symbol:
                    updated_paths = api.auto_update_metric_paths(symbol)
                    if updated_paths:
                        print("\n💡 Подсказка: Скопируйте сгенерированные пути из созданного .py файла")
                        print("    и обновите функцию get_required_metrics в коде")
                else:
                    print("Введите корректный тикер!")
            else:
                print("Неверный выбор!")
                
    except Exception as e:
        print(f"\nКритическая ошибка: {e}")
        import traceback
        traceback.print_exc()


# Простая функция для быстрого получения метрик
def get_metrics(symbol: str, api_key: str = None):
    """Простая функция для получения метрик одной строкой"""
    api = GuruFocusAPI(api_key=api_key)
    return api.get_required_metrics(symbol)


if __name__ == "__main__":
    main()
