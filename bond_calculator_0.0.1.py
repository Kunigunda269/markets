import traceback
from datetime import datetime
from openpyxl import Workbook
import os


def bond_yield_calculator():
    try:
        print("\nКалькулятор доходности облигаций\n")

        # Функция для обработки ввода с обработкой ошибок
        def parse_input(prompt, input_type=float, positive=True):
            while True:
                try:
                    user_input = input(prompt).replace(',', '.')
                    value = input_type(user_input)
                    if positive and value < 0:
                        raise ValueError("Значение не может быть отрицательным.")
                    return value
                except ValueError as e:
                    print(f"Ошибка ввода: {e}. Попробуйте снова.")

        # Ввод данных с обработкой ошибок
        while True:
            try:
                purchase_date = input("Введите дату покупки облигации (в формате ДД-ММ-ГГГГ): ")
                purchase_date = datetime.strptime(purchase_date, "%d-%m-%Y")
                break
            except ValueError:
                print("Ошибка: неверный формат даты. Попробуйте снова.")

        while True:
            try:
                sell_date = input("Введите дату продажи/погашения облигации (в формате ДД-ММ-ГГГГ): ")
                sell_date = datetime.strptime(sell_date, "%d-%m-%Y")
                if sell_date <= purchase_date:
                    raise ValueError("Дата продажи должна быть позже даты покупки.")
                break
            except ValueError as e:
                print(f"Ошибка: {e}")

        volume = parse_input("Введите сумму покупки облигаций (например, 100000): ", float)
        purchase_price = parse_input("Введите цену покупки облигации (в % от номинала, например, 98): ") / 100
        coupon_rate = parse_input("Введите размер купона (в %, например, 5 или 0 для бескупонных): ") / 100
        sell_price = parse_input("Введите цену продажи/погашения облигации (в % от номинала, например, 100): ") / 100

        # Расчёты
        holding_period_days = (sell_date - purchase_date).days
        holding_period_years = holding_period_days / 365.0
        nominal = 100

        coupon_income = 0
        if coupon_rate > 0:
            coupon_income = volume * coupon_rate * holding_period_years

        price_diff_income = (sell_price - purchase_price) * volume
        total_income = coupon_income + price_diff_income
        total_yield_percent = (total_income / (purchase_price * volume)) * 100

        # Вывод результатов
        print("\n--- Результаты ---")
        print(f"Срок удержания: {holding_period_days} дней ({holding_period_years:.2f} лет)")
        print(f"Купонный доход: {coupon_income:.2f}")
        print(f"Доход от изменения цены: {price_diff_income:.2f}")
        print(f"Общая доходность в деньгах: {total_income:.2f}")
        print(f"Общая доходность в процентах: {total_yield_percent:.2f}%")

        # Экспорт результатов
        export_choice = input("Хотите экспортировать результаты в файл? (да/нет): ").strip().lower()
        if export_choice == "да":
            save_path = input(
                "Укажите путь для сохранения файла или нажмите Enter для сохранения на рабочий стол: ").strip()

            if not save_path:
                desktop = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop')
                filename = os.path.join(desktop, f"{int(total_income)}.xlsx")
                print("Файл будет сохранён на рабочий стол.")
            else:
                filename = os.path.join(save_path, f"{int(total_income)}.xlsx")

            wb = Workbook()
            ws = wb.active
            ws.title = "Результаты"

            ws.append(["Параметр", "Значение"])
            ws.append(["Срок удержания (дни)", holding_period_days])
            ws.append(["Купонный доход", round(coupon_income, 2)])
            ws.append(["Доход от изменения цены", round(price_diff_income, 2)])
            ws.append(["Общая доходность в деньгах", round(total_income, 2)])
            ws.append(["Общая доходность в процентах", f"{round(total_yield_percent, 2)}%"])

            try:
                wb.save(filename)
                print(f"\nРезультаты успешно сохранены в файл: {filename}")
            except Exception as e:
                print(f"Ошибка при сохранении файла: {e}")

        print("\nСпасибо за использование калькулятора доходности облигаций!")

    except Exception as e:
        # Логируем ошибку в файл и выводим ее
        with open("error_log.txt", "w") as f:
            f.write(traceback.format_exc())
        print("Произошла ошибка. Подробности смотрите в error_log.txt.")


if __name__ == "__main__":
    bond_yield_calculator()
