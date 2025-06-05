# Ai-trade

This project provides a simple example of fetching stock data from Yahoo Finance and displaying it on the web. The `/stock/<ticker>` page now renders an interactive Plotly chart with selectable time periods and chart types (line or candlestick) similar to options found in trading apps.

## Requirements

Install dependencies with:

```bash
pip install -r requirements.txt
```

## Usage

Run the Flask application:

```bash
python app.py
```

The home page at `http://localhost:5000/` lets you save tickers and search existing ones.
Click any saved ticker to view the interactive chart at `/stock/<ticker>`.
