from flask import (
    Blueprint,
    render_template_string,
    request,
    redirect,
    url_for,
)
import os
import re
import yfinance as yf
import plotly.graph_objects as go
import plotly.io as pio
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import openai

from db import get_db
from auth import login_required

bp = Blueprint('stocks', __name__)


def gpt_predict_prices(data, days, sentiment):
    key = os.getenv("OPENAI_API_KEY")
    if not key or data is None or data.empty or 'Close' not in data:
        return None
    try:
        openai.api_key = key
        closes = [round(float(c), 2) for c in data['Close'].tail(30).tolist()]
        prompt = (
            "Predict the next "
            f"{days} closing prices based on this series: {closes} "
            f"and an average news sentiment of {sentiment:.3f}. "
            "Respond with numbers only."
        )
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        text = resp.choices[0].message["content"]
        nums = re.findall(r"-?\d+\.\d+|-?\d+", text)
        out = [float(n) for n in nums][:days]
        if len(out) == days:
            return out
    except Exception:
        pass
    return None


def predict_prices(data, days=5, sentiment=0.0):
    """Predict future close prices using GPT or naive averaging."""
    if data is None or data.empty or 'Close' not in data:
        return []

    preds = gpt_predict_prices(data, days, sentiment)
    if preds is not None:
        return preds

    closes = data['Close']
    if len(closes) < 2:
        return []

    diffs = closes.diff().dropna()
    avg_change = diffs.tail(5).mean()
    last = closes.iloc[-1]
    predictions = []
    for _ in range(days):
        last += avg_change
        if sentiment > 0.1:
            last *= 1.01
        elif sentiment < -0.1:
            last *= 0.99
        predictions.append(float(last))
    return predictions


def fetch_news(ticker, stock):
    """Return a list of recent news articles for the given ticker."""
    news = []
    try:
        fetched = []
        if hasattr(stock, "get_news"):
            fetched = stock.get_news()
        elif hasattr(stock, "news"):
            fetched = stock.news

        if hasattr(fetched, "to_dict"):
            fetched = fetched.to_dict("records")

        for item in list(fetched)[:5]:
            title = item.get("title", "")
            link = item.get("link") or item.get("canonicalUrl", {}).get("url")
            if not link:
                link = item.get("clickThroughUrl", {}).get("url")
            publisher = item.get("publisher") or item.get("provider", {}).get(
                "displayName"
            )
            if title and link:
                news.append({"title": title, "link": link, "publisher": publisher})
        if news:
            return news
    except Exception:
        pass

    # Fallback to Yahoo RSS feed if yfinance fails
    try:
        feed_url = (
            f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        )
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:5]:
            news.append(
                {
                    "title": entry.title,
                    "link": entry.link,
                    "publisher": entry.get("source", {}).get("title"),
                }
            )
    except Exception:
        pass
    return news


def gpt_sentiment(news):
    """Return sentiment score using GPT if API key set."""
    key = os.getenv("OPENAI_API_KEY")
    if not key or not news:
        return None
    try:
        openai.api_key = key
        text = "\n".join(n["title"] for n in news)
        prompt = (
            "Give a single sentiment score between -1 and 1 for these headlines:"\
            f"\n{text}\nScore:"
        )
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        out = resp.choices[0].message["content"].strip()
        match = re.search(r"-?\d+\.\d+|-?\d+", out)
        if match:
            return float(match.group())
    except Exception:
        pass
    return None


def analyze_sentiment(news):
    """Return sentiment score averaged over news titles or via GPT."""
    if not news:
        return 0.0
    score = gpt_sentiment(news)
    if score is not None:
        return score
    analyzer = SentimentIntensityAnalyzer()
    scores = [analyzer.polarity_scores(n["title"])['compound'] for n in news]
    return sum(scores) / len(scores)


def run_simulation(data, predictions, balance):
    """Return portfolio values and trade log for a buy-and-hold simulation."""
    if data is None or data.empty or 'Close' not in data or not predictions:
        return [], []
    last_close = float(data['Close'].iloc[-1])
    shares = balance / last_close
    trades = [f"Day 0: buy {shares:.2f} shares at ${last_close:.2f}"]
    results = []
    for i, price in enumerate(predictions, start=1):
        value = shares * price
        profit = value - balance
        results.append({'day': i, 'predicted': price, 'value': value, 'profit': profit})
        trades.append(f"Day {i}: value ${value:.2f}, profit ${profit:.2f}")
    return results, trades

index_template = """
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
  <title>Saved Stocks</title>
</head>
<body class=\"bg-light\">
<nav class=\"navbar navbar-expand-lg navbar-dark bg-primary\">
  <div class=\"container\">
    <a class=\"navbar-brand\" href=\"{{ url_for('stocks.index') }}\">Ai-Trade</a>
    <div class=\"d-flex\">
      <span class=\"navbar-text me-3\">Logged in as {{ g.user['username'] }}</span>
      <a class=\"btn btn-outline-light btn-sm\" href=\"{{ url_for('auth.logout') }}\">Logout</a>
    </div>
  </div>
</nav>

<div class=\"container py-4\">
  <h1 class=\"mb-4\">Saved Tickers</h1>
  <form method=\"post\" class=\"row gy-2 gx-2 align-items-center mb-3\">
    <div class=\"col-auto\">
      <input name=\"ticker\" class=\"form-control\" placeholder=\"Add ticker\">
    </div>
    <div class=\"col-auto\">
      <button class=\"btn btn-success\" type=\"submit\">Add</button>
    </div>
  </form>
  {% if message %}
  <div class=\"alert alert-danger\">{{ message }}</div>
  {% endif %}
  <form method=\"get\" class=\"mb-3\">
    <div class=\"input-group\">
      <input name=\"q\" class=\"form-control\" placeholder=\"Search\" value=\"{{ search }}\">
      <button class=\"btn btn-outline-secondary\" type=\"submit\">Search</button>
    </div>
  </form>
  <ul class=\"list-group\">
    {% for t in tickers %}
      <li class=\"list-group-item\"><a href=\"{{ url_for('stocks.stock', ticker=t) }}\">{{ t }}</a></li>
    {% else %}
      <li class=\"list-group-item\">No tickers found.</li>
    {% endfor %}
  </ul>
</div>
</body>
</html>
"""

template = """
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
  <title>{{ ticker }} Data</title>
</head>
<body class=\"bg-light\">
<nav class=\"navbar navbar-expand-lg navbar-dark bg-primary\">
  <div class=\"container\">
    <a class=\"navbar-brand\" href=\"{{ url_for('stocks.index') }}\">Ai-Trade</a>
    <div class=\"d-flex\">
      <span class=\"navbar-text me-3\">Logged in as {{ g.user['username'] }}</span>
      <a class=\"btn btn-outline-light btn-sm\" href=\"{{ url_for('auth.logout') }}\">Logout</a>
    </div>
  </div>
</nav>

<div class=\"container py-4\">
  <h1 class=\"mb-4\">{{ ticker }} Data</h1>
  {% if error %}
  <div class=\"alert alert-danger\">{{ error }}</div>
  {% else %}
    <form method=\"get\" class=\"row gy-2 gx-2 align-items-center mb-3\">
      <div class=\"col-auto\">
        <select name=\"period\" class=\"form-select\" onchange=\"this.form.submit()\">
          {% for p in ['5d', '1mo', '3mo', '6mo', '1y'] %}
          <option value=\"{{ p }}\" {% if p == period %}selected{% endif %}>{{ p }}</option>
          {% endfor %}
        </select>
      </div>
      <div class=\"col-auto\">
        <select name=\"chart_type\" class=\"form-select\" onchange=\"this.form.submit()\">
          <option value=\"line\" {% if chart_type == 'line' %}selected{% endif %}>Line</option>
          <option value=\"candlestick\" {% if chart_type == 'candlestick' %}selected{% endif %}>Candlestick</option>
        </select>
      </div>
    </form>
    {{ graph|safe }}
    <div class=\"table-responsive\">
      <table class=\"table table-striped\">
        <thead>
          <tr><th>Date</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th></tr>
        </thead>
        <tbody>
        {% for date, row in data.iterrows() %}
          <tr>
            <td>{{ date.date() }}</td>
            <td>{{ '{:.2f}'.format(row['Open']) }}</td>
            <td>{{ '{:.2f}'.format(row['High']) }}</td>
            <td>{{ '{:.2f}'.format(row['Low']) }}</td>
            <td>{{ '{:.2f}'.format(row['Close']) }}</td>
            <td>{{ row['Volume']|int }}</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    <h2 class=\"mt-4\">Predicted Close Prices (Next {{ days }} days)</h2>
    <ul>
      {% for price in predictions %}
      <li>Day {{ loop.index }}: {{ '{:.2f}'.format(price) }}</li>
      {% endfor %}
    </ul>
    <h2 class=\"mt-4\">Simulation</h2>
    <form method=\"post\" class=\"row gy-2 gx-2 align-items-center mb-3\">
      <div class=\"col-auto\">
        <input name=\"seed\" class=\"form-control\" placeholder=\"Seed\" value=\"{{ seed }}\">
      </div>
      <div class=\"col-auto\">
        <input name=\"days\" class=\"form-control\" placeholder=\"Days\" value=\"{{ days }}\">
      </div>
      <div class=\"col-auto\">
        <button class=\"btn btn-warning\" type=\"submit\">시뮬레이션 하기</button>
      </div>
    </form>
    {% if simulation %}
    <div class=\"table-responsive\">
      <table class=\"table table-bordered\">
        <thead>
          <tr><th>Day</th><th>Predicted Close</th><th>Value</th><th>Profit</th></tr>
        </thead>
        <tbody>
          {% for r in simulation %}
          <tr>
            <td>{{ r.day }}</td>
            <td>{{ '{:.2f}'.format(r.predicted) }}</td>
            <td>{{ '{:.2f}'.format(r.value) }}</td>
            <td>{{ '{:.2f}'.format(r.profit) }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}
    {% if trades %}
    <h3 class=\"mt-3\">모의투자 거래내역</h3>
    <ul>
      {% for t in trades %}
      <li>{{ t }}</li>
      {% endfor %}
    </ul>
    {% endif %}
    <h2 class=\"mt-4\">Average News Sentiment: {{ sentiment|round(3) }}</h2>
    <h2 class=\"mt-4\">Latest News</h2>
    <ul>
      {% for n in news %}
      <li><a href="{{ n['link'] }}" target="_blank">{{ n['title']|truncate(100) }}</a>{% if n.get('publisher') %} ({{ n['publisher'] }}){% endif %}</li>
      {% else %}
      <li>No recent news found.</li>
      {% endfor %}
    </ul>
  {% endif %}
</div>
</body>
</html>
"""


@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    conn = get_db()
    cursor = conn.cursor()
    message = None
    if request.method == 'POST':
        ticker = request.form.get('ticker', '').upper().strip()
        if ticker:
            try:
                cursor.execute('INSERT INTO tickers (ticker) VALUES (?)', (ticker,))
                conn.commit()
                conn.close()
                return redirect(url_for('stocks.index'))
            except Exception:
                message = 'Ticker already saved.'
    search = request.args.get('q', '').upper()
    if search:
        cursor.execute('SELECT ticker FROM tickers WHERE ticker LIKE ?', (f"%{search}%",))
    else:
        cursor.execute('SELECT ticker FROM tickers')
    tickers = [row['ticker'] for row in cursor.fetchall()]
    conn.close()
    return render_template_string(index_template, tickers=tickers, search=search, message=message)


@bp.route('/stock/<ticker>', methods=['GET', 'POST'])
@login_required
def stock(ticker):
    period = request.args.get('period', '5d')
    chart_type = request.args.get('chart_type', 'line')
    seed = 10000.0
    days = 5
    if request.method == 'POST':
        seed = float(request.form.get('seed', 10000))
        days = int(request.form.get('days', 5))
    try:
        stock = yf.Ticker(ticker)
        data = stock.history(period=period)
        if data.empty:
            raise ValueError("No data found for ticker")

        if chart_type == 'candlestick':
            fig = go.Figure(data=[go.Candlestick(x=data.index,
                                                 open=data['Open'],
                                                 high=data['High'],
                                                 low=data['Low'],
                                                 close=data['Close'])])
        else:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=data.index, y=data['Close'], mode='lines', name='Close'))

        fig.update_layout(title=f"{ticker} Price", xaxis_title="Date", yaxis_title="Price", template="plotly_white")
        graph_html = pio.to_html(fig, full_html=False)
        news = fetch_news(ticker, stock)
        sentiment = analyze_sentiment(news)
        preds = predict_prices(data, days=days, sentiment=sentiment)
        simulation, trades = (run_simulation(data, preds, seed)
                              if request.method == 'POST' else ([], []))

        return render_template_string(
            template,
            ticker=ticker,
            data=data,
            period=period,
            chart_type=chart_type,
            graph=graph_html,
            predictions=preds,
            news=news,
            sentiment=sentiment,
            simulation=simulation,
            trades=trades,
            seed=seed,
            days=days,
            error=None,
        )
    except Exception as e:
        return render_template_string(
            template,
            ticker=ticker,
            data=None,
            period=period,
            chart_type=chart_type,
            graph='',
            predictions=[],
            news=[],
            sentiment=0.0,
            simulation=[],
            trades=[],
            seed=seed,
            days=days,
            error=str(e),
        )

