import pandas as pd
import plotly.express as px
import re  # Для извлечения дат из имени файла

# Файлы данных
category_file = r"C:\Users\User\OneDrive\Рабочий стол\category_tokens_details_2.xlsx"
result_files = [
    r"C:\Users\User\OneDrive\Рабочий стол\result_2024-12-08_to_2024-12-09.xlsx",
    r"C:\Users\User\OneDrive\Рабочий стол\result_2024-12-15_to_2024-12-16.xlsx",
    r"C:\Users\User\OneDrive\Рабочий стол\result_2024-12-22_to_2024-12-23.xlsx",
    r"C:\Users\User\OneDrive\Рабочий стол\result_2024-12-29_to_2024-12-30.xlsx",
    r"C:\Users\User\OneDrive\Рабочий стол\result_2025-01-05_to_2025-01-06.xlsx",
    r"C:\Users\User\OneDrive\Рабочий стол\result_2025-01-12_to_2025-01-13.xlsx",
    r"C:\Users\User\OneDrive\Рабочий стол\result_2025-01-18_to_2025-01-19.xlsx"
]

# Читаем файл категорий
categories_df = pd.read_excel(category_file)

# Убедимся, что категории содержат нужный столбец
if 'Symbol' not in categories_df.columns:
    raise ValueError("В файле категорий отсутствует столбец 'Symbol'. Убедитесь, что файл содержит данные с токенами.")

# Функция для извлечения даты из имени файла
def extract_date_range(filename):
    match = re.search(r"result_(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})", filename)
    if match:
        return match.group(1), match.group(2)  # Возвращаем начальную и конечную дату
    else:
        raise ValueError(f"Невозможно извлечь даты из имени файла: {filename}")


# Подготовка данных для графика
results = []

for category, group in categories_df.groupby('Category'):
    tokens = group['Symbol'].tolist()  # Список токенов в категории
    for file in result_files:
        # Читаем данные из файла
        df = pd.read_excel(file)
        start_date, _ = extract_date_range(file)  # Извлекаем дату
        df['Date'] = pd.to_datetime(start_date)

        # Переименовываем столбцы для удобства
        df.rename(columns={"Symbol": "Symbol", "Price (USD)": "Price", "Market Cap": "MarketCap"}, inplace=True)

        # Фильтруем данные по токенам из категории
        token_data = df[df['Symbol'].isin(tokens)]

        if not token_data.empty:
            # Для данной категории и даты считаем среднее значение метрики (Price или Market Cap)
            avg_price = token_data['Price'].mean()
            avg_market_cap = token_data['MarketCap'].mean()

            results.append({
                "Category": category,
                "Date": start_date,
                "AvgPrice": avg_price,
                "AvgMarketCap": avg_market_cap
            })

# Преобразуем данные в DataFrame
balanced_data = pd.DataFrame(results)

# Сохранение итоговых данных в Excel для проверки
output_file = r"C:\Users\User\OneDrive\Рабочий стол\balanced_data_output_avg.xlsx"
balanced_data.to_excel(output_file, index=False)
print(f"Результаты сохранены в файл: {output_file}")

# Строим график изменения средней цены
fig = px.line(
    balanced_data,
    x='Date',
    y='AvgPrice',
    color='Category',
    title='Изменение средней цены по категориям',
    labels={"AvgPrice": "Average Price (USD)", "Date": "Date", "Category": "Category"}
)
fig.show()
