import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import yfinance as yf
from scipy import stats
from datetime import datetime, timedelta
import re
import os
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

class PortfolioVolatilityAnalyzer:
    def __init__(self, portfolio_data, benchmark_ticker='^IXIC', start_date=None, end_date=None, risk_free_rate=0.04):
        """
        Инициализация анализатора волатильности портфеля
        
        Args:
            portfolio_data (list): Список словарей с данными о позициях в портфеле.
                Каждый словарь должен содержать 'ticker', 'position', 'price' и опционально 'type', 'expiry', 'strike'
            benchmark_ticker (str, optional): Тикер бенчмарка. По умолчанию - индекс NASDAQ (^IXIC).
            start_date (str, optional): Начальная дата для анализа в формате 'YYYY-MM-DD'
            end_date (str, optional): Конечная дата для анализа в формате 'YYYY-MM-DD'
            risk_free_rate (float, optional): Безрисковая ставка для расчета коэффициента Шарпа. По умолчанию - 4%.
        """
        self.portfolio_data = portfolio_data
        self.benchmark_ticker = benchmark_ticker
        self.risk_free_rate = risk_free_rate
        self.output_dir = r"C:\Users\Main\Pitonio\market"
        
        # Обновляем цены закрытия для всех инструментов
        self._update_current_prices()
        
        # Если даты не указаны, используем период с начала года
        if end_date is None:
            self.end_date = datetime.now()
        else:
            self.end_date = datetime.strptime(end_date, '%Y-%m-%d')
            
        if start_date is None:
            self.start_date = datetime(self.end_date.year, 1, 1)
        else:
            self.start_date = datetime.strptime(start_date, '%Y-%m-%d')
        
        # Извлекаем тикеры и рассчитываем веса
        self.stock_tickers = self._extract_stock_tickers()
        self.option_data = self._extract_option_data()
        self.portfolio_weights = self._calculate_weights()
        
        # Загружаем данные
        self.data = None
        self.returns = None
        self.benchmark_returns = None
        self.load_data()
    
    def _update_current_prices(self):
        """Обновляет текущие цены для всех инструментов"""
        for item in self.portfolio_data:
            ticker = item['ticker']
            if 'type' not in item or item['type'] == 'stock':
                try:
                    stock = yf.Ticker(ticker)
                    current_price = stock.history(period='1d')['Close'].iloc[-1]
                    item['current_price'] = current_price
                except:
                    item['current_price'] = item['price']
            else:
                # Для опционов пока оставляем указанную цену
                item['current_price'] = item['price']
    
    def _extract_stock_tickers(self):
        """Извлекает список уникальных тикеров акций (без опционов)"""
        tickers = []
        for item in self.portfolio_data:
            if 'type' not in item or item['type'] == 'stock':
                tickers.append(item['ticker'])
        return list(set(tickers))
    
    def _extract_option_data(self):
        """Извлекает данные об опционах в портфеле"""
        options = []
        for item in self.portfolio_data:
            if 'type' in item and item['type'] == 'option':
                options.append(item)
        return options
    
    def _calculate_weights(self):
        """Расчет весов активов в портфеле на основе их позиций и цен"""
        total_value = 0
        weights = {}
        
        # Сначала рассчитываем общую стоимость портфеля
        for item in self.portfolio_data:
            position = item['position']
            price = item['current_price']
            value = abs(position) * price  # Берем абсолютное значение позиции
            total_value += value
        
        # Затем вычисляем вес каждого актива
        for item in self.portfolio_data:
            ticker = item['ticker']
            position = item['position']
            price = item['current_price']
            value = abs(position) * price
            
            if ticker not in weights:
                weights[ticker] = 0
            
            # Для опционов учитываем направление (PUT/CALL)
            if 'type' in item and item['type'] == 'option':
                option_type = item.get('option_type', '')
                # Для PUT опционов с короткой позицией или CALL с длинной - положительная бета
                # Для PUT опционов с длинной позицией или CALL с короткой - отрицательная бета
                sign = 1
                if (option_type == 'PUT' and position > 0) or (option_type == 'CALL' and position < 0):
                    sign = -1
                weights[ticker] += sign * (value / total_value)
            else:
                # Для акций учитываем знак позиции
                sign = 1 if position > 0 else -1
                weights[ticker] += sign * (value / total_value)
        
        return weights
    
    def load_data(self):
        """Загрузка исторических данных о ценах"""
        tickers = self.stock_tickers + [self.benchmark_ticker]
        start_date_str = self.start_date.strftime('%Y-%m-%d')
        end_date_str = self.end_date.strftime('%Y-%m-%d')
        
        # Загружаем данные и получаем цены закрытия
        raw_data = yf.download(tickers, start=start_date_str, end=end_date_str)
        self.data = raw_data['Close']  # Используем 'Close' вместо 'Adj Close'
        
        # Расчет дневных доходностей
        self.returns = self.data[self.stock_tickers].pct_change().dropna()
        self.benchmark_returns = self.data[self.benchmark_ticker].pct_change().dropna()
    
    def _get_ticker_weight(self, ticker):
        """Получает вес указанного тикера в портфеле"""
        return self.portfolio_weights.get(ticker, 0)
    
    def calculate_portfolio_returns(self):
        """Расчет доходности портфеля на основе весов"""
        portfolio_returns = pd.Series(0, index=self.returns.index)
        
        for ticker in self.stock_tickers:
            weight = self._get_ticker_weight(ticker)
            if weight != 0 and ticker in self.returns.columns:
                portfolio_returns += self.returns[ticker] * weight
        
        # Учитываем влияние опционов (упрощенно через дельту)
        for option in self.option_data:
            underlying = option.get('underlying', option['ticker'].split()[0])
            delta = option.get('delta', 0.5)  # Если дельта не указана, берем примерно 0.5
            weight = self._get_ticker_weight(option['ticker'])
            
            if weight != 0 and underlying in self.returns.columns:
                # Для опционов влияние пропорционально дельте
                portfolio_returns += self.returns[underlying] * weight * delta
        
        return portfolio_returns
    
    def calculate_beta(self):
        """Расчет бета-коэффициента портфеля относительно бенчмарка"""
        portfolio_returns = self.calculate_portfolio_returns()
        
        # Расчет бета для всего портфеля
        slope, _, _, _, _ = stats.linregress(self.benchmark_returns, portfolio_returns)
        
        # Расчет бета для отдельных активов
        asset_betas = {}
        for ticker in self.stock_tickers:
            weight = self._get_ticker_weight(ticker)
            if abs(weight) > 0 and ticker in self.returns.columns:
                asset_slope, _, _, _, _ = stats.linregress(self.benchmark_returns, self.returns[ticker])
                asset_betas[ticker] = asset_slope
        
        # Бета для опционов (упрощенно)
        for option in self.option_data:
            ticker = option['ticker']
            underlying = option.get('underlying', ticker.split()[0])
            delta = option.get('delta', 0.5)
            
            if underlying in self.returns.columns:
                underlying_beta, _, _, _, _ = stats.linregress(self.benchmark_returns, self.returns[underlying])
                # Бета опциона примерно равна бета базового актива * дельта
                asset_betas[ticker] = underlying_beta * delta
        
        return {
            'portfolio_beta': slope,
            'asset_betas': asset_betas
        }
    
    def calculate_volatility(self):
        """Расчет волатильности (стандартного отклонения) портфеля и бенчмарка"""
        portfolio_returns = self.calculate_portfolio_returns()
        
        # Волатильность портфеля и бенчмарка (годовая)
        portfolio_volatility = portfolio_returns.std() * np.sqrt(252)
        benchmark_volatility = self.benchmark_returns.std() * np.sqrt(252)
        
        # Волатильность отдельных активов (годовая)
        asset_volatility = {}
        for ticker in self.stock_tickers:
            weight = self._get_ticker_weight(ticker)
            if abs(weight) > 0 and ticker in self.returns.columns:
                asset_volatility[ticker] = self.returns[ticker].std() * np.sqrt(252)
        
        # Волатильность опционов (упрощенно)
        for option in self.option_data:
            ticker = option['ticker']
            underlying = option.get('underlying', ticker.split()[0])
            delta = option.get('delta', 0.5)
            
            if underlying in self.returns.columns:
                # Для опционов волатильность выше из-за левериджа
                underlying_vol = self.returns[underlying].std() * np.sqrt(252)
                # Упрощенная формула - для более точного расчета нужно использовать модель ценообразования опционов
                asset_volatility[ticker] = underlying_vol * abs(delta) * 2
        
        return {
            'portfolio_volatility': portfolio_volatility,
            'benchmark_volatility': benchmark_volatility,
            'asset_volatility': asset_volatility,
            'relative_volatility': portfolio_volatility / benchmark_volatility
        }
    
    def calculate_correlation(self):
        """Расчет корреляции между портфелем и бенчмарком"""
        portfolio_returns = self.calculate_portfolio_returns()
        corr = np.corrcoef(portfolio_returns, self.benchmark_returns)[0, 1]
        
        # Корреляция отдельных активов с бенчмарком
        asset_correlations = {}
        for ticker in self.stock_tickers:
            weight = self._get_ticker_weight(ticker)
            if abs(weight) > 0 and ticker in self.returns.columns:
                asset_correlations[ticker] = np.corrcoef(self.returns[ticker], self.benchmark_returns)[0, 1]
        
        # Корреляция опционов с бенчмарком (упрощенно через базовый актив)
        for option in self.option_data:
            ticker = option['ticker']
            underlying = option.get('underlying', ticker.split()[0])
            
            if underlying in self.returns.columns:
                asset_correlations[ticker] = np.corrcoef(self.returns[underlying], self.benchmark_returns)[0, 1]
        
        return {
            'portfolio_correlation': corr,
            'asset_correlations': asset_correlations
        }
    
    def calculate_var(self, confidence_level=0.95):
        """Расчет Value-at-Risk (VaR) портфеля"""
        portfolio_returns = self.calculate_portfolio_returns()
        
        # Исторический VaR
        hist_var = np.percentile(portfolio_returns, 100 * (1 - confidence_level))
        
        # Параметрический VaR (предполагается нормальное распределение)
        z_score = stats.norm.ppf(1 - confidence_level)
        param_var = portfolio_returns.mean() + z_score * portfolio_returns.std()
        
        return {
            'historical_var': hist_var,
            'parametric_var': param_var
        }
    
    def calculate_sharpe_ratio(self):
        """Расчет коэффициента Шарпа для портфеля и бенчмарка"""
        portfolio_returns = self.calculate_portfolio_returns()
        
        # Годовая доходность
        annual_portfolio_return = portfolio_returns.mean() * 252
        annual_benchmark_return = self.benchmark_returns.mean() * 252
        
        # Годовая волатильность
        annual_portfolio_volatility = portfolio_returns.std() * np.sqrt(252)
        annual_benchmark_volatility = self.benchmark_returns.std() * np.sqrt(252)
        
        # Коэффициент Шарпа
        portfolio_sharpe = (annual_portfolio_return - self.risk_free_rate) / annual_portfolio_volatility
        benchmark_sharpe = (annual_benchmark_return - self.risk_free_rate) / annual_benchmark_volatility
        
        return {
            'portfolio_sharpe': portfolio_sharpe,
            'benchmark_sharpe': benchmark_sharpe,
            'relative_sharpe': portfolio_sharpe / benchmark_sharpe if benchmark_sharpe != 0 else float('inf')
        }
    
    def calculate_tracking_error(self):
        """Расчет ошибки слежения (tracking error) портфеля относительно бенчмарка"""
        portfolio_returns = self.calculate_portfolio_returns()
        tracking_diff = portfolio_returns - self.benchmark_returns
        tracking_error = tracking_diff.std() * np.sqrt(252)
        
        return tracking_error
    
    def calculate_risk_metrics(self, returns_series, name=""):
        """Расчет расширенных метрик риска"""
        daily_std = returns_series.std()
        daily_returns = returns_series
        
        # Базовые метрики
        metrics = {
            f'{name} Daily Std Dev': daily_std,
            f'{name} Annual Std Dev': daily_std * np.sqrt(252),
            f'{name} Average Daily Return': daily_returns[daily_returns > 0].mean(),
            f'{name} Average Daily Loss': daily_returns[daily_returns < 0].mean(),
        }
        
        # Расчет просадки
        cumulative_returns = (1 + daily_returns).cumprod()
        rolling_max = cumulative_returns.cummax()
        drawdowns = cumulative_returns / rolling_max - 1
        metrics[f'{name} Max Drawdown'] = drawdowns.min()
        
        # Расчет VaR и CVaR
        confidence_level = 0.01  # 1%
        var_1 = np.percentile(daily_returns, confidence_level * 100)
        cvar_1 = daily_returns[daily_returns <= var_1].mean()
        metrics[f'{name} VaR (1%)'] = var_1
        metrics[f'{name} CVaR (1%)'] = cvar_1
        
        # Коэффициенты
        excess_returns = daily_returns - self.risk_free_rate / 252
        downside_returns = daily_returns[daily_returns < 0]
        
        # Sharpe Ratio
        metrics[f'{name} Sharpe Ratio'] = excess_returns.mean() / daily_returns.std() * np.sqrt(252)
        
        # Sortino Ratio
        metrics[f'{name} Sortino Ratio'] = excess_returns.mean() / downside_returns.std() * np.sqrt(252)
        
        # Calmar Ratio
        annual_return = (1 + daily_returns).prod() ** (252/len(daily_returns)) - 1
        metrics[f'{name} Calmar Ratio'] = annual_return / abs(metrics[f'{name} Max Drawdown'])
        
        # Omega Ratio
        threshold_return = 0
        gain_returns = daily_returns[daily_returns > threshold_return] - threshold_return
        loss_returns = threshold_return - daily_returns[daily_returns < threshold_return]
        metrics[f'{name} Omega Ratio'] = gain_returns.sum() / loss_returns.sum() if loss_returns.sum() != 0 else np.inf
        
        # Kaplan Ratio
        metrics[f'{name} Kaplan Ratio'] = daily_returns.mean() / downside_returns.std() * np.sqrt(252)
        
        # Rainy Day Ratio
        extreme_movements = daily_returns[(daily_returns < daily_returns.quantile(0.01)) |
                                       (daily_returns > daily_returns.quantile(0.99))]
        metrics[f'{name} Rainy Ratio'] = extreme_movements.std() / daily_returns.std()
        
        return metrics

    def _calculate_portfolio_statistics(self):
        """Рассчитывает статистику по портфелю и бенчмарку"""
        portfolio_returns = self.calculate_portfolio_returns()
        
        stats = {
            'Портфель': {
                'Средняя дневная доходность': portfolio_returns.mean() * 100,
                'Медианная дневная доходность': portfolio_returns.median() * 100,
                'Максимальная дневная доходность': portfolio_returns.max() * 100,
                'Минимальная дневная доходность': portfolio_returns.min() * 100,
                'Стандартное отклонение (дневное)': portfolio_returns.std() * 100,
                'Годовая волатильность': portfolio_returns.std() * np.sqrt(252) * 100,
                'Годовая доходность': ((1 + portfolio_returns).prod() ** (252/len(portfolio_returns)) - 1) * 100,
                'Количество положительных дней': len(portfolio_returns[portfolio_returns > 0]),
                'Количество отрицательных дней': len(portfolio_returns[portfolio_returns < 0]),
                'Коэффициент асимметрии': stats.skew(portfolio_returns),
                'Коэффициент эксцесса': stats.kurtosis(portfolio_returns)
            },
            'Бенчмарк': {
                'Средняя дневная доходность': self.benchmark_returns.mean() * 100,
                'Медианная дневная доходность': self.benchmark_returns.median() * 100,
                'Максимальная дневная доходность': self.benchmark_returns.max() * 100,
                'Минимальная дневная доходность': self.benchmark_returns.min() * 100,
                'Стандартное отклонение (дневное)': self.benchmark_returns.std() * 100,
                'Годовая волатильность': self.benchmark_returns.std() * np.sqrt(252) * 100,
                'Годовая доходность': ((1 + self.benchmark_returns).prod() ** (252/len(self.benchmark_returns)) - 1) * 100,
                'Количество положительных дней': len(self.benchmark_returns[self.benchmark_returns > 0]),
                'Количество отрицательных дней': len(self.benchmark_returns[self.benchmark_returns < 0]),
                'Коэффициент асимметрии': stats.skew(self.benchmark_returns),
                'Коэффициент эксцесса': stats.kurtosis(self.benchmark_returns)
            }
        }
        
        # Создаем DataFrame
        stats_df = pd.DataFrame(stats)
        
        # Форматируем числовые значения
        for col in stats_df.columns:
            stats_df[col] = stats_df[col].apply(lambda x: f"{x:,.2f}%" if "доходность" in x.lower() or "волатильность" in x.lower()
                                               else f"{x:,.2f}" if isinstance(x, (float, np.float64))
                                               else x)
        
        return stats_df

    def generate_portfolio_html_report(self):
        """Генерирует HTML отчет с интерактивными графиками Plotly"""
        position_df = self._calculate_position_values()
        stats_df = self._calculate_portfolio_statistics()
        
        # Переименовываем столбцы на русский язык
        position_df = position_df.rename(columns={
            'ticker': 'Тикер',
            'type': 'Тип',
            'position': 'Позиция',
            'price': 'Цена',
            'value': 'Стоимость',
            'direction': 'Направление',
            'percentage': 'Доля (%)'
        })
        
        # Заменяем английские значения на русские
        position_df['Тип'] = position_df['Тип'].replace({
            'stock': 'акция',
            'option': 'опцион'
        })
        position_df['Направление'] = position_df['Направление'].replace({
            'Long': 'Длинная',
            'Short': 'Короткая'
        })
        
        # Форматируем числовые столбцы
        position_df['Цена'] = position_df['Цена'].apply(lambda x: f"${x:,.2f}")
        position_df['Стоимость'] = position_df['Стоимость'].apply(lambda x: f"${x:,.2f}")
        position_df['Доля (%)'] = position_df['Доля (%)'].apply(lambda x: f"{x:.2f}%")
        
        # Создаем HTML с улучшенным форматированием
        html_template = f"""
        <html>
        <head>
            <title>Анализ портфеля</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body {{ 
                    padding: 20px; 
                    font-family: Arial, sans-serif;
                }}
                .table {{ 
                    margin-top: 20px;
                    width: 100%;
                    border-collapse: collapse;
                }}
                .table th {{
                    background-color: #f8f9fa;
                    text-align: center;
                    vertical-align: middle;
                    font-weight: bold;
                    padding: 12px;
                }}
                .table td {{
                    text-align: center;
                    vertical-align: middle;
                    padding: 10px;
                }}
                .table-hover tbody tr:hover {{
                    background-color: #f5f5f5;
                }}
                .container {{
                    max-width: 1400px;
                    margin: 0 auto;
                }}
                h1, h2 {{
                    text-align: center;
                    margin: 30px 0;
                    color: #333;
                }}
                .stats-table {{
                    margin-top: 40px;
                }}
                .section {{
                    margin-bottom: 50px;
                    background-color: white;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="section">
                    <h1>Структура портфеля</h1>
                    {position_df.to_html(classes='table table-striped table-hover', index=False, escape=False)}
                </div>
                
                <div class="section">
                    <h2>Статистика портфеля и бенчмарка</h2>
                    {stats_df.to_html(classes='table table-striped table-hover stats-table', escape=False)}
                </div>
            </div>
        </body>
        </html>
        """
        
        # Сохраняем HTML
        with open(os.path.join(self.output_dir, 'portfolio_positions.html'), 'w', encoding='utf-8') as f:
            f.write(html_template)

    def generate_extended_report(self):
        """Генерация расширенного отчета с дополнительными метриками риска"""
        portfolio_returns = self.calculate_portfolio_returns()
        
        # Рассчитываем метрики для портфеля и бенчмарка
        portfolio_metrics = self.calculate_risk_metrics(portfolio_returns, "Portfolio")
        benchmark_metrics = self.calculate_risk_metrics(self.benchmark_returns, "Benchmark")
        
        # Создаем DataFrame с разделением на столбцы A/B для портфеля и C/D для бенчмарка
        portfolio_df = pd.DataFrame.from_dict(portfolio_metrics, orient='index')
        portfolio_df.columns = ['A']
        portfolio_df['B'] = portfolio_df['A']  # Дублируем значения для сравнения
        
        benchmark_df = pd.DataFrame.from_dict(benchmark_metrics, orient='index')
        benchmark_df.columns = ['C']
        benchmark_df['D'] = benchmark_df['C']  # Дублируем значения для сравнения
        
        # Объединяем метрики
        metrics_df = pd.concat([portfolio_df, benchmark_df], axis=1)
        metrics_df = metrics_df.round(4)
        
        # Сохраняем в HTML и Excel
        html_path = os.path.join(self.output_dir, 'risk_metrics_report.html')
        excel_path = os.path.join(self.output_dir, 'risk_metrics_report.xlsx')
        
        # Создаем HTML с улучшенным форматированием
        html_template = f"""
        <html>
        <head>
            <title>Метрики риска</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body {{ padding: 20px; }}
                .table {{ margin-top: 20px; }}
                .positive {{ color: green; }}
                .negative {{ color: red; }}
            </style>
        </head>
        <body>
            <h1>Метрики риска портфеля и бенчмарка</h1>
            <div class="row">
                <div class="col-12">
                    {metrics_df.to_html(classes='table table-striped')}
                </div>
            </div>
        </body>
        </html>
        """
        
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_template)
        
        metrics_df.to_excel(excel_path)
        
        # Генерируем отчет по структуре портфеля
        self.generate_portfolio_html_report()
        
        # Генерируем графики
        self._generate_plotly_charts()
        
        return metrics_df

    def _generate_plotly_charts(self):
        """Генерирует интерактивные графики с помощью Plotly"""
        portfolio_returns = self.calculate_portfolio_returns()
        
        # Кумулятивная доходность
        cumulative_portfolio = (1 + portfolio_returns).cumprod()
        cumulative_benchmark = (1 + self.benchmark_returns).cumprod()
        
        # График кумулятивной доходности
        fig_returns = go.Figure()
        fig_returns.add_trace(go.Scatter(
            x=cumulative_portfolio.index,
            y=cumulative_portfolio,
            name='Портфель',
            line=dict(color='blue')
        ))
        fig_returns.add_trace(go.Scatter(
            x=cumulative_benchmark.index,
            y=cumulative_benchmark,
            name='NASDAQ',
            line=dict(color='red')
        ))
        
        fig_returns.update_layout(
            title='Сравнение кумулятивной доходности',
            xaxis_title='Дата',
            yaxis_title='Кумулятивная доходность',
            template='plotly_white'
        )
        
        fig_returns.write_html(os.path.join(self.output_dir, 'cumulative_returns.html'))
        
        # График волатильности
        rolling_vol = self._calculate_rolling_volatility()
        fig_vol = go.Figure()
        
        fig_vol.add_trace(go.Scatter(
            x=rolling_vol.index,
            y=rolling_vol['portfolio'],
            name='Портфель',
            line=dict(color='blue')
        ))
        fig_vol.add_trace(go.Scatter(
            x=rolling_vol.index,
            y=rolling_vol['benchmark'],
            name='NASDAQ',
            line=dict(color='red')
        ))
        
        fig_vol.update_layout(
            title='Сравнение волатильности (30-дневное скользящее окно)',
            xaxis_title='Дата',
            yaxis_title='Годовая волатильность',
            template='plotly_white'
        )
        
        fig_vol.write_html(os.path.join(self.output_dir, 'volatility_comparison.html'))

    def _calculate_rolling_volatility(self, window=30):
        """Рассчитывает скользящую волатильность"""
        portfolio_returns = self.calculate_portfolio_returns()
        
        rolling_portfolio_vol = portfolio_returns.rolling(window=window).std() * np.sqrt(252)
        rolling_benchmark_vol = self.benchmark_returns.rolling(window=window).std() * np.sqrt(252)
        
        return pd.DataFrame({
            'portfolio': rolling_portfolio_vol,
            'benchmark': rolling_benchmark_vol
        })

    def _calculate_position_values(self):
        """Рассчитывает стоимость и процентное распределение позиций"""
        position_values = []
        total_value = 0
        
        # Сначала рассчитываем общую стоимость портфеля
        for item in self.portfolio_data:
            position = item['position']
            price = item['current_price']
            value = abs(position * price)  # Используем абсолютное значение
            total_value += value
        
        # Затем рассчитываем значения для каждой позиции
        for item in self.portfolio_data:
            position = item['position']
            price = item['current_price']
            value = abs(position * price)
            percentage = (value / total_value) * 100 if total_value > 0 else 0
            
            position_values.append({
                'ticker': item['ticker'],
                'type': item.get('type', 'stock'),
                'position': position,
                'price': price,
                'value': value,
                'direction': 'Long' if position > 0 else 'Short',
                'percentage': percentage
            })
        
        return pd.DataFrame(position_values)

    def _calculate_instrument_type_distribution(self):
        """Рассчитывает распределение по типам инструментов"""
        position_df = self._calculate_position_values()
        return position_df.groupby('type')['value'].sum()

    def _calculate_long_short_distribution(self):
        """Рассчитывает распределение по Long/Short"""
        position_df = self._calculate_position_values()
        return position_df.groupby('direction')['value'].sum()

def parse_option_ticker(ticker):
    """
    Парсит строку с тикером опциона, извлекая базовый актив, дату истечения и страйк
    Пример: 'AMZN Jun20'25 180 PUT' -> {'underlying': 'AMZN', 'expiry': '2025-06-20', 'strike': 180, 'option_type': 'PUT'}
    """
    try:
        # Используем регулярные выражения для извлечения информации
        pattern = r'(\w+)\s+(\w+)(\d+)\'(\d+)\s+(\d+(?:\.\d+)?)\s+(PUT|CALL)'
        match = re.match(pattern, ticker)
        
        if match:
            underlying, month, day, year, strike, option_type = match.groups()
            
            # Преобразуем месяц в числовой формат
            month_map = {
                'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
                'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
            }
            month_num = month_map.get(month, '01')
            
            # Форматируем дату истечения
            year = '20' + year  # Предполагаем, что год в формате '25' -> '2025'
            expiry_date = f"{year}-{month_num}-{day.zfill(2)}"
            
            return {
                'underlying': underlying,
                'expiry': expiry_date,
                'strike': float(strike),
                'option_type': option_type
            }
        
    except Exception as e:
        print(f"Error parsing option ticker '{ticker}': {e}")
    
    # Если не удалось распарсить, возвращаем базовый актив как первое слово
    underlying = ticker.split()[0]
    return {'underlying': underlying}

def extract_portfolio_from_screenshots(screenshots_data):
    """
    Извлекает информацию о портфеле из скриншотов
    Это заглушка - в реальном сценарии здесь был бы парсинг данных со скриншотов
    """
    # Примерный формат данных на основе скриншотов
    portfolio = []
    
    # Акции
    stocks = [
        {'ticker': 'AAPL', 'position': 21, 'price': 169.99},
        {'ticker': 'AMD', 'position': 36, 'price': 152.48},
        {'ticker': 'AMZN', 'position': 12, 'price': 171.98},
        {'ticker': 'ASML', 'position': 7, 'price': 909.12},
        {'ticker': 'AVGO', 'position': 50, 'price': 28.41},
        {'ticker': 'CRUS', 'position': 35, 'price': 107.45},
        {'ticker': 'DELL', 'position': 36, 'price': 147.59},
        {'ticker': 'DY', 'position': 40, 'price': 201.56},
        {'ticker': 'GOOGL', 'position': 17, 'price': 132.56},
        {'ticker': 'HYG', 'position': 50, 'price': 79.98},
        {'ticker': 'LRCX', 'position': 20, 'price': 78.01},
        {'ticker': 'META', 'position': 12, 'price': 426.01},
        {'ticker': 'MSFT', 'position': 13, 'price': 391.74},
        {'ticker': 'MU', 'position': 10, 'price': 140.31},
        {'ticker': 'NVDA', 'position': 40, 'price': 81.64},
        {'ticker': 'QCOM', 'position': 20, 'price': 196.77},
        {'ticker': 'QTUM', 'position': 30, 'price': 80.75},
        {'ticker': 'RMD', 'position': 8, 'price': 228.99},
        {'ticker': 'SMCI', 'position': 30, 'price': 41.14},
        {'ticker': 'SNPS', 'position': 7, 'price': 466.23},
        {'ticker': 'SPGI', 'position': 2, 'price': 475.17},
        {'ticker': 'SPY', 'position': 20, 'price': 571.76},
        {'ticker': 'TER', 'position': 30, 'price': 109.25},
        {'ticker': 'TSLA', 'position': 2, 'price': 244.72},
        {'ticker': 'TSM', 'position': 15, 'price': 183.73},
        {'ticker': 'VRT', 'position': 46, 'price': 124.52},
        {'ticker': 'ZIM', 'position': 120, 'price': 26.10},
        {'ticker': 'ABBV', 'position': 15, 'price': 143.15},
        {'ticker': 'PFE', 'position': 130, 'price': 28.12},
        {'ticker': 'ROST', 'position': 15, 'price': 162.13}
    ]
    
    for stock in stocks:
        stock['type'] = 'stock'
        portfolio.append(stock)
    
    # Опционы
    options = [
        {'ticker': 'AMZN Jun20\'25 180 PUT', 'position': 1, 'price': 13.85},
        {'ticker': 'CRUS Jun20\'25 115 PUT', 'position': 1, 'price': 16.22},
        {'ticker': 'NVDA Jun20\'25 134 PUT', 'position': 1, 'price': 24.41},
        {'ticker': 'UAL Jun20\'25 110 CALL', 'position': 1, 'price': 13.85},
        {'ticker': 'SPY Apr11\'25 539 PUT', 'position': -1, 'price': 1.28},
        {'ticker': 'TSLA Nov21\'25 200 PUT', 'position': -1, 'price': 26.80},
        {'ticker': 'GOOGL May16\'25 170 PUT', 'position': -1, 'price': 6.88},
        {'ticker': 'MSFT Jul18\'25 335 PUT', 'position': -1, 'price': 8.48},
        {'ticker': 'QQQ Apr04\'25 430 CALL', 'position': -1, 'price': 3.73},
        {'ticker': 'QQQ May16\'25 420 CALL', 'position': -1, 'price': 7.29},
        {'ticker': 'QQQ May30\'25 435 CALL', 'position': -1, 'price': 9.61},
        {'ticker': 'DY Apr17\'25 175 CALL', 'position': -1, 'price': 1.99},
        {'ticker': 'TER Apr17\'25 100 CALL', 'position': -3, 'price': 0.50}
    ]
    
    for option in options:
        option['type'] = 'option'
        # Парсим информацию об опционе из тикера
        option_info = parse_option_ticker(option['ticker'])
        for key, value in option_info.items():
            option[key] = value
        
        # Добавляем примерную дельту для опционов
        # В реальном сценарии нужно было бы получить эти данные из рыночных данных
        if option['option_type'] == 'PUT':
            option['delta'] = -0.5 if option['position'] > 0 else 0.5
        else:  # CALL
            option['delta'] = 0.5 if option['position'] > 0 else -0.5
        
        portfolio.append(option)
    
    return portfolio

# Пример использования:
if __name__ == "__main__":
    # Извлекаем данные о портфеле из скриншотов
    portfolio_data = extract_portfolio_from_screenshots(None)
    
    # Создаем анализатор с периодом с начала года
    analyzer = PortfolioVolatilityAnalyzer(
        portfolio_data=portfolio_data,
        benchmark_ticker='^IXIC',  # NASDAQ
        start_date=datetime(2024, 1, 1).strftime('%Y-%m-%d'),  # С начала года
        end_date=None  # По текущую дату
    )
    
    # Генерируем расширенный отчет с метриками риска
    metrics_df = analyzer.generate_extended_report()
    print("Анализ портфеля завершен. Отчеты и графики сохранены в директории:", analyzer.output_dir)
