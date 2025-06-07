# Ai-trade

This project provides a simple example of fetching stock data from Alpha Vantage and displaying it on the web. The `/stock/<ticker>` page now renders an interactive Plotly chart with selectable time periods and chart types (line or candlestick) similar to options found in trading apps.

## Requirements

Install dependencies with:

```bash
pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in your environment to enable GPT-powered sentiment
analysis and price predictions.
Set `ALPHA_VANTAGE_KEY` to fetch stock prices and news from Alpha Vantage. If
this key is not provided or the Alpha Vantage request fails, the application
automatically falls back to the free Yahoo Finance RSS feed for headlines.
Set `FLASK_SECRET_KEY` to configure the Flask session secret.
To send verification emails during registration you must configure Mailgun by
setting `MAILGUN_API_KEY` and `MAILGUN_DOMAIN`. Specify `MAILGUN_FROM` if you
want to customize the sender address.

## Usage

Run the Flask application:

```bash
python app.py
```

The home page at `http://localhost:5000/` lets you save tickers and search existing ones.
Click any saved ticker to view the interactive chart at `/stock/<ticker>`.

Social platforms such as KakaoTalk or Discord display a preview card when you share a page link. Each page now includes Open Graph meta tags so the preview shows the site title, description and a placeholder image hosted on `via.placeholder.com`.

Each stock page includes average sentiment from the latest news headlines.
If an `OPENAI_API_KEY` environment variable is set, GPT is used to analyze
the headlines and provide price forecasts. Otherwise VADER performs a simple
sentiment check to adjust the naive predictions.

## Login

The application now supports user accounts. Visit `/register` to create an account and `/login` to sign in. Registration requires an email address. After signing up a verification link is emailed to you; open the link to activate your account before logging in. Once logged in, you can add and view saved tickers. Use `/logout` to end the session.

## Simulation

A command line script `simulation.py` runs an adaptive trading simulation using the predicted closing prices.
Provide a ticker and optionally an initial balance and number of days:

```bash
python simulation.py AAPL 10000 5
```

This fetches recent data for `AAPL`, predicts the next 5 closing prices and shows the portfolio value while automatically buying or selling based on the forecast. If prices are expected to fall throughout the period, the simulation displays "지속적인 하락새로 인한 해당기간내에 매수의견이 없습니다."

On each stock page you can also run this simulation in the browser. Enter a seed
amount and number of days in the **시뮬레이션 하기** form to see a table of
predicted portfolio value and a simple trade log.

## Docker

You can run the application in Docker. Build the image and start the container
using Docker Compose:

```bash
docker compose up --build
```

The web server will be available at `http://localhost:5000/`. The SQLite
database file is stored on the host in the `data` directory so that your saved
tickers persist between runs.

