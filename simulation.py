import sys
import yfinance as yf

from stocks import fetch_news, analyze_sentiment, predict_prices


def simulate(ticker, balance=10000, days=5):
    """Run an adaptive trading simulation using predicted prices."""
    stock = yf.Ticker(ticker)
    data = stock.history(period='1mo')
    if data.empty or 'Close' not in data:
        print('No data available for', ticker)
        return
    last_close = float(data['Close'].iloc[-1])
    news = fetch_news(ticker, stock)
    sentiment = analyze_sentiment(news)
    predictions = predict_prices(data, days=days, sentiment=sentiment)
    if not predictions:
        print('Unable to generate predictions')
        return

    current_price = last_close
    cash = balance
    shares = 0.0
    bought = False
    for i, price in enumerate(predictions, start=1):
        action = 'HOLD'
        if price > current_price and cash >= current_price:
            shares_to_buy = cash / current_price
            cash -= shares_to_buy * current_price
            shares += shares_to_buy
            action = 'BUY'
            bought = True
        elif price < current_price and shares > 0:
            cash += shares * current_price
            shares = 0
            action = 'SELL'
        value = cash + shares * price
        print(f'Day {i}: predicted {price:.2f}, action {action}, shares {shares:.2f}, value ${value:.2f}')
        current_price = price

    if shares > 0:
        cash += shares * current_price
        print(f'Final sell {shares:.2f} shares at {current_price:.2f}, total ${cash:.2f}')
    if not bought:
        print('No buy signal during simulation period.')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python simulation.py TICKER [balance] [days]')
        sys.exit(1)
    ticker = sys.argv[1].upper()
    balance = float(sys.argv[2]) if len(sys.argv) > 2 else 10000
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    simulate(ticker, balance, days)
