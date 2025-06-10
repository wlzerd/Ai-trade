import os
import datetime as dt
import requests
import pandas as pd

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")


def fetch_ticks(ticker: str, date: str):
    """Fetch raw tick data for a single trading day using Polygon's v3 endpoint."""
    if not POLYGON_API_KEY:
        raise ValueError("POLYGON_API_KEY not set")
    url = f"https://api.polygon.io/v3/trades/{ticker}"
    params = {
        "timestamp.gte": f"{date}T04:00:00Z",
        "timestamp.lte": f"{date}T20:00:00Z",
        "limit": 50000,
        "apiKey": POLYGON_API_KEY,
    }
    trades = []
    while True:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        trades.extend(data.get("results", []))
        next_url = data.get("next_url")
        if not next_url:
            break
        url = next_url
        params = {"apiKey": POLYGON_API_KEY}
    return trades


def detect_anomalies(ticker: str, date: str, threshold: float = 3.0):
    """Return trade count anomalies for the given ticker and date."""
    trades = fetch_ticks(ticker, date)
    if not trades:
        return pd.Series(dtype=int), 0.0, 0.0
    df = pd.DataFrame(trades)
    df["time"] = pd.to_datetime(df["sip_timestamp"], unit="ns")
    counts = df.resample("1min", on="time").size()
    mean = counts.mean()
    std = counts.std()
    anomalies = counts[counts > mean + threshold * std]
    return anomalies, mean, std


def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: python anomalies.py TICKER [YYYY-MM-DD] [threshold]")
        return
    ticker = sys.argv[1].upper()
    date = sys.argv[2] if len(sys.argv) > 2 else dt.date.today().strftime("%Y-%m-%d")
    threshold = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0

    anomalies, mean, std = detect_anomalies(ticker, date, threshold)
    if anomalies.empty:
        print("No anomalies detected")
    else:
        print(f"Anomalies for {ticker} on {date} (mean {mean:.2f}, std {std:.2f})")
        for ts, count in anomalies.items():
            print(ts.strftime("%H:%M"), int(count))


if __name__ == "__main__":
    main()
