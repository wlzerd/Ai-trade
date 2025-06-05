import sys
import yfinance as yf

from stocks import fetch_news, analyze_sentiment, predict_prices


def simulate(ticker, balance=10000, days=5):
    """Run a simple buy-and-hold simulation using predicted prices."""
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
    shares = balance / last_close
    print(f'Starting with ${balance:.2f} and buying {shares:.2f} shares at ${last_close:.2f}')
    for i, price in enumerate(predictions, start=1):
        value = shares * price
        print(f'Day {i}: predicted close ${price:.2f}, portfolio value ${value:.2f}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python simulation.py TICKER [balance] [days]')
        sys.exit(1)
    ticker = sys.argv[1].upper()
    balance = float(sys.argv[2]) if len(sys.argv) > 2 else 10000
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    simulate(ticker, balance, days)
