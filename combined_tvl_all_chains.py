import os
import logging
from datetime import datetime
import pandas as pd
import sys
import asyncio
import aiohttp

# Настройка логирования только в консоль
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Базовые блокчейны (на случай, если не удастся загрузить полный список)
DEFAULT_CHAINS = {
    'ETH': {
        'name': 'Ethereum',
        'defillama_id': 'Ethereum',
    },
    'BSC': {
        'name': 'BNB Chain',
        'defillama_id': 'BSC',
    },
    'OPTIMISM': {
        'name': 'Optimism',
        'defillama_id': 'Optimism',
    },
}

# Эндпоинты API
API_URL = 'https://api.llama.fi/chains'

# Путь к директории для сохранения файлов
OUTPUT_DIR = r"C:\Users\Main\Pitonio\crypto_etf"
os.makedirs(OUTPUT_DIR, exist_ok=True)

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

class BlockchainMetricsAPI:
    def __init__(self):
        self.chain_configs = {}

    async def _make_request(self, url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"Ошибка при запросе к {url}: {response.status}")
                        return {}
        except Exception as e:
            logger.error(f"Ошибка при выполнении запроса к {url}: {str(e)}")
            return {}

    async def load_all_chains(self):
        """Загрузка всех доступных блокчейнов из DeFiLlama API"""
        chains_response = await self._make_request(API_URL)

        if not chains_response:
            logger.warning("Не удалось загрузить список блокчейнов, используем стандартный набор")
            return DEFAULT_CHAINS

        result = {}
        for chain in chains_response:
            # Проверяем наличие TVL и имени
            if chain.get('name') and chain.get('tvl', 0) > 0:
                chain_id = chain['name'].upper().replace(' ', '_')
                result[chain_id] = {
                    'name': chain['name'],
                    'defillama_id': chain['name'],
                    'tvl': chain.get('tvl', 0)
                }

        return result

    def save_to_excel(self, metrics, filename='blockchain_metrics.xlsx'):
        df = pd.DataFrame(metrics)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        output_path = os.path.join(OUTPUT_DIR, filename)
        df.to_excel(output_path, index=False, sheet_name='Metrics')
        print(f"Метрики сохранены в файл: {output_path}")

async def main():
    api = BlockchainMetricsAPI()

    # Загружаем список всех блокчейнов
    print("Загрузка списка блокчейнов...")
    api.chain_configs = await api.load_all_chains()

    chains_count = len(api.chain_configs)
    print(f"Загружено {chains_count} блокчейнов\n")

    # Сортируем блокчейны по имени (в алфавитном порядке)
    sorted_chains = sorted(
        api.chain_configs.items(),
        key=lambda x: x[1]['name']
    )

    # Отображаем список блокчейнов
    chain_options = {}
    print("\nСписок доступных блокчейнов:")
    
    for i, (key, chain) in enumerate(sorted_chains, 1):
        chain_options[str(i)] = key
        print(f"{i}) {chain['name']}")

    # Пользователь выбирает блокчейн по номеру
    selected_chain = input("\nВыберите номер блокчейна: ").strip()
    
    if selected_chain not in chain_options:
        print("Неверный выбор. Завершение работы.")
        return

    selected_chain_id = chain_options[selected_chain]
    chain_info = api.chain_configs[selected_chain_id]
    
    # Выводим TVL выбранного блокчейна
    chain_name = chain_info['name']
    tvl = chain_info['tvl']
    
    print(f"\n===== TVL для сети {chain_name} =====")
    print(f"TVL: ${tvl:,.2f}")
    
    # Формируем метрики для сохранения
    metrics = [{
        'chain_id': selected_chain_id,
        'name': chain_name,
        'tvl': tvl,
        'timestamp': datetime.now().isoformat()
    }]

    # Спрашиваем пользователя о сохранении в Excel
    save_excel = input("\nСохранить данные в Excel? (y/n): ").lower().strip()
    if save_excel == 'y':
        api.save_to_excel(metrics)
    else:
        print("Данные не сохранены. Завершение работы.")

if __name__ == "__main__":
    asyncio.run(main())
