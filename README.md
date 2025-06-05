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

Then navigate to `http://localhost:5000/stock/MSFT` replacing `MSFT` with the ticker you want to view.
