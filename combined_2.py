import os
import logging
from datetime import datetime
import pandas as pd
import hashlib
import time
import json
import sys
import asyncio
import aiohttp
from typing import Dict, Optional

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('metrics.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Класс для кэширования данных
class Cache:
    def __init__(self, cache_dir: str, expiry: int):
        self.cache_dir = cache_dir
        self.expiry = expiry
        os.makedirs(cache_dir, exist_ok=True)

    def _get_cache_path(self, key: str) -> str:
        hash_key = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{hash_key}.json")

    def get(self, key: str) -> Optional[Dict]:
        cache_path = self._get_cache_path(key)
        try:
            if os.path.exists(cache_path):
                if time.time() - os.path.getctime(cache_path) < self.expiry:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                else:
                    os.remove(cache_path)
                    logger.debug(f"Удален устаревший кэш для ключа: {key}")
        except Exception as e:
            logger.error(f"Ошибка при чтении кэша: {str(e)}")
        return None

    def set(self, key: str, value: Dict) -> None:
        cache_path = self._get_cache_path(key)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(value, f, ensure_ascii=False, indent=2)
            logger.debug(f"Данные сохранены в кэш для ключа: {key}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении в кэш: {str(e)}")


# Базовые блокчейны (на случай, если не удастся загрузить полный список)
DEFAULT_CHAINS = {
    'ETH': {
        'name': 'Ethereum',
        'defillama_id': 'Ethereum',
        'coingecko_id': 'ethereum',
    },
    'BSC': {
        'name': 'BNB Chain',
        'defillama_id': 'BSC',
        'coingecko_id': 'binance-smart-chain',
    },
    'OPTIMISM': {
        'name': 'Optimism',
        'defillama_id': 'Optimism',
        'coingecko_id': 'optimism',
    },
}

# Эндпоинты API
API_ENDPOINTS = {
    'defillama': 'https://api.llama.fi',
    'defilama_chains': 'https://api.llama.fi/chains',
    'defilama_protocols': 'https://api.llama.fi/protocols',
}

# Типы метрик
METRIC_TYPES = {
    '1': {'id': 'tvl', 'name': 'Суммарный TVL'},
    '2': {'id': 'dex_tvl', 'name': 'TVL в DEX'},
    '3': {'id': 'wallets', 'name': 'Количество кошельков (оценка)'},
    '4': {'id': 'protocols', 'name': 'Количество протоколов'},
    '5': {'id': 'fees', 'name': 'Комиссии за 24ч'},
    '6': {'id': 'staking', 'name': 'Стейкинг'},
    '7': {'id': 'mcap_tvl', 'name': 'Отношение MCap/TVL'}
}

# Путь к директории для сохранения файлов
OUTPUT_DIR = r"C:\Users\Илья\PycharmProjects\crypto etf"
CACHE_DIR = os.path.join(OUTPUT_DIR, "cache")
LOG_DIR = os.path.join(OUTPUT_DIR, "logs")
CACHE_EXPIRY = 3600

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class BlockchainMetricsAPI:
    def __init__(self):
        self.cache = Cache(CACHE_DIR, CACHE_EXPIRY)
        self.chain_configs = {}

    async def _make_request(self, url, headers=None, params=None):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                        url, headers=headers, params=params
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(
                            f"Ошибка при запросе к {url}: {response.status}"
                        )
                        return {}
        except Exception as e:
            logger.error(f"Ошибка при выполнении запроса к {url}: {str(e)}")
            return {}

    async def load_all_chains(self):
        """Загрузка всех доступных блокчейнов из DeFiLlama API"""
        chains_url = f"{API_ENDPOINTS['defilama_chains']}"
        chains_response = await self._make_request(chains_url)

        if not chains_response:
            logger.warning("Не удалось загрузить список блокчейнов, "
                           "используем стандартный набор")
            return DEFAULT_CHAINS

        result = {}
        for chain in chains_response:
            # Проверяем наличие TVL и имени
            if chain.get('name') and chain.get('tvl', 0) > 0:
                chain_id = chain['name'].upper().replace(' ', '_')
                result[chain_id] = {
                    'name': chain['name'],
                    'defillama_id': chain['name'],
                    'coingecko_id': chain.get('gecko_id', ''),
                    'tvl': chain.get('tvl', 0),
                    'mcap': chain.get('mcap', 0)
                }

        return result

    async def get_chain_data(self, chain_id):
        """Получение данных о блокчейне"""
        chain_config = self.chain_configs[chain_id]

        # Получаем данные по TVL
        chain_data = await self.get_tvl_data(chain_id)

        # Получаем данные о протоколах
        protocols_data = await self.get_protocols_data(chain_id)

        # Комбинируем все данные
        return {
            'chain_id': chain_id,
            'name': chain_config['name'],
            'timestamp': datetime.now().isoformat(),
            **chain_data,
            **protocols_data,
        }

    async def get_tvl_data(self, chain_id):
        """Получение TVL сети через DefiLlama API"""
        chain_config = self.chain_configs[chain_id]

        # Через эндпоинт /protocols получаем общий TVL и TVL в DEX
        protocols_url = f"{API_ENDPOINTS['defillama']}/protocols"
        protocols_response = await self._make_request(protocols_url)

        tvl = 0
        dex_tvl = 0
        protocols_count = 0
        staking = 0

        if protocols_response:
            for protocol in protocols_response:
                if protocol.get('chain') == chain_config['defillama_id']:
                    protocol_tvl = protocol.get('tvl', 0)
                    tvl += protocol_tvl

                    if protocol_tvl > 0:
                        protocols_count += 1

                    if protocol.get('category') == 'Dexes':
                        dex_tvl += protocol_tvl

                    if protocol.get('category') == 'Staking':
                        staking += protocol_tvl

        # Через эндпоинт /chains получаем дополнительные данные
        chains_url = f"{API_ENDPOINTS['defilama_chains']}"
        chains_response = await self._make_request(chains_url)

        chain_specific_tvl = 0
        fees_24h = 0
        mcap = 0

        if chains_response:
            for chain in chains_response:
                if chain.get('name') == chain_config['defillama_id']:
                    chain_specific_tvl = chain.get('tvl', 0)
                    fees_24h = chain.get('fees', {}).get('total24h', 0)
                    mcap = chain.get('mcap', 0)
                    break

        # Берем максимальное значение TVL
        final_tvl = max(tvl, chain_specific_tvl)

        # Оценка количества кошельков (примерная)
        # В реальности нужно использовать специализированные API каждой сети
        wallets_count = int(final_tvl * 0.01)  # Примерная оценка

        # Вычисляем отношение Market Cap к TVL
        mcap_tvl_ratio = 0
        if final_tvl > 0 and mcap > 0:
            mcap_tvl_ratio = mcap / final_tvl

        return {
            'tvl': final_tvl,
            'dex_tvl': dex_tvl,
            'wallets': wallets_count,
            'fees': fees_24h,
            'staking': staking,
            'mcap_tvl': mcap_tvl_ratio
        }

    async def get_protocols_data(self, chain_id):
        """Получение данных о протоколах"""
        chain_config = self.chain_configs[chain_id]

        protocols_url = f"{API_ENDPOINTS['defillama']}/protocols"
        response = await self._make_request(protocols_url)

        protocols_count = 0
        if response:
            for protocol in response:
                if protocol.get('chain') == chain_config['defillama_id']:
                    if protocol.get('tvl', 0) > 0:
                        protocols_count += 1

        return {
            'protocols': protocols_count
        }

    def save_to_excel(self, metrics, filename='blockchain_metrics.xlsx'):
        df = pd.DataFrame(metrics)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('chain_id')

        output_path = os.path.join(OUTPUT_DIR, filename)
        df.to_excel(output_path, index=False, sheet_name='Metrics')
        logger.info(f"Метрики сохранены в файл: {output_path}")
        print(f"Метрики сохранены в файл: {output_path}")


async def main():
    api = BlockchainMetricsAPI()

    # Загружаем список всех блокчейнов
    print("Загрузка списка блокчейнов...")
    api.chain_configs = await api.load_all_chains()

    chains_count = len(api.chain_configs)
    print(f"Загружено {chains_count} блокчейнов\n")

    all_metrics = []

    # Выбор метрик для отображения
    print("\nВыберите метрики для отображения (введите номера через запятую):")
    for key, metric in METRIC_TYPES.items():
        print(f"{key}) {metric['name']}")

    selected_metrics = input("Ваш выбор: ").strip().split(',')
    selected_metric_ids = [
        METRIC_TYPES[m.strip()]['id']
        for m in selected_metrics
        if m.strip() in METRIC_TYPES
    ]

    # Выбор блокчейнов для анализа
    print("\nВыберите блокчейны для анализа (введите номера через запятую):")
    chain_options = {}

    # Сортируем блокчейны по TVL (если доступно) или по имени
    sorted_chains = sorted(
        api.chain_configs.items(),
        key=lambda x: x[1]['name']
    )

    for i, (key, chain) in enumerate(sorted_chains, 1):
        tvl_str = ""
        if 'tvl' in chain and chain['tvl'] > 0:
            tvl_str = f" - TVL: ${chain['tvl']:,.2f}"

        chain_options[str(i)] = key
        print(f"{i}) {chain['name']}{tvl_str}")

    selected_chains = input("Ваш выбор: ").strip().split(',')
    selected_chain_ids = [
        chain_options[c.strip()]
        for c in selected_chains
        if c.strip() in chain_options
    ]

    if not selected_chains or not selected_metric_ids:
        print("Не выбраны метрики или блокчейны. Завершение работы.")
        return

    # Получаем данные для выбранных блокчейнов
    for chain_id in selected_chain_ids:
        metrics = await api.get_chain_data(chain_id)
        all_metrics.append(metrics)

        # Вывод информации о выбранных метриках
        chain_name = api.chain_configs[chain_id]['name']
        print(f"\n===== Данные для сети {chain_name} =====")

        for metric_id in selected_metric_ids:
            metric_name = next(
                m['name'] for m in METRIC_TYPES.values()
                if m['id'] == metric_id
            )

            if metric_id in ['tvl', 'dex_tvl', 'fees', 'staking']:
                print(f"{metric_name}: ${metrics.get(metric_id, 0):,.2f}")
            elif metric_id == 'mcap_tvl':
                print(f"{metric_name}: {metrics.get(metric_id, 0):,.2f}")
            else:
                print(f"{metric_name}: {metrics.get(metric_id, 0):,}")

    # Спрашиваем пользователя о сохранении в Excel
    save_excel = input("\nСохранить данные в Excel? (y/n): ").lower().strip()
    if save_excel == 'y':
        api.save_to_excel(all_metrics)


if __name__ == "__main__":
    asyncio.run(main())
