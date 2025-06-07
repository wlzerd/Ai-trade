from flask import (
    Blueprint,
    render_template_string,
    request,
    redirect,
    url_for,
)
import os
import re
import requests
import plotly.graph_objects as go
import plotly.io as pio
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import openai
import pandas as pd
from dotenv import load_dotenv
load_dotenv()
# Placeholder image used for social previews
OG_IMAGE_URL = os.getenv("LOGO")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")

from db import get_db
from auth import login_required

bp = Blueprint('stocks', __name__)


def fetch_stock_history(ticker, period='5d'):
    """Fetch historical stock prices from Finnhub."""
    if not FINNHUB_API_KEY:
        raise ValueError("FINNHUB_API_KEY not set")

    end = int(pd.Timestamp.utcnow().timestamp())
    start = int((pd.Timestamp.utcnow() - pd.Timedelta(days=365)).timestamp())
    params = {
        "symbol": ticker,
        "resolution": "D",
        "from": start,
        "to": end,
        "token": FINNHUB_API_KEY,
    }
    resp = requests.get("https://finnhub.io/api/v1/stock/candle", params=params, timeout=10)
    data = resp.json()
    if data.get("s") != "ok":
        raise ValueError(f"Finnhub error: {data}")

    df = pd.DataFrame(
        {
            "Open": data["o"],
            "High": data["h"],
            "Low": data["l"],
            "Close": data["c"],
            "Volume": data["v"],
        },
        index=pd.to_datetime(data["t"], unit="s"),
    )
    df = df.sort_index()
    days_map = {"5d": 5, "1mo": 22, "3mo": 66, "6mo": 132, "1y": 264}
    days = days_map.get(period, 5)
    return df.tail(days)


def gpt_predict_prices(data, days, sentiment):
    key = os.getenv("OPENAI_API_KEY")
    if not key or data is None or data.empty or 'Close' not in data:
        return None
    try:
        openai.api_key = key
        closes = [round(float(c), 2) for c in data['Close'].tail(180).tolist()]
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
    avg_change = diffs.tail(180).mean()
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


def fetch_news(ticker):
    """Return a list of recent news articles for the given ticker.

    Uses Finnhub's company news endpoint when a ``FINNHUB_API_KEY`` is
    configured. If the key is missing or the request fails, headlines are
    retrieved from the Yahoo Finance RSS feed instead.
    """
    news = []
    if FINNHUB_API_KEY:
        try:
            today = pd.Timestamp.utcnow().date()
            start = (today - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
            params = {
                "symbol": ticker,
                "from": start,
                "to": today.strftime("%Y-%m-%d"),
                "token": FINNHUB_API_KEY,
            }
            resp = requests.get("https://finnhub.io/api/v1/company-news", params=params, timeout=10)
            data = resp.json()
            for item in data[:5]:
                title = item.get("headline", "")
                link = item.get("url")
                publisher = item.get("source")
                if title and link:
                    news.append({"title": title, "link": link, "publisher": publisher})
            if news:
                return news
        except Exception:
            pass

    # Fallback to Yahoo RSS feed if Finnhub request fails
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


def sentiment_to_label(score):
    """Return human readable sentiment label."""
    if score > 0.1:
        return "긍정적"
    if score < -0.1:
        return "부정적"
    return "보통"


def run_simulation(data, predictions, balance):
    """Simulate adaptive trading based on predicted prices."""
    if data is None or data.empty or 'Close' not in data or not predictions:
        return [], [], ""

    last_date = data.index[-1]
    start_price = float(data['Close'].iloc[-1])
    current_price = start_price
    no_buy_expected = not any(p > start_price for p in predictions)
    cash = balance
    shares = 0.0
    trades = []
    results = []
    bought = False

    for i, price in enumerate(predictions, start=1):
        date = (last_date + pd.Timedelta(days=i)).strftime('%Y-%m-%d')
        action = None

        if price > current_price and price > start_price and cash >= current_price:
            # Buy as price expected to rise beyond the starting price
            shares_to_buy = cash / current_price
            cash -= shares_to_buy * current_price
            shares += shares_to_buy
            action = 'BUY'
            bought = True
        elif price < current_price and shares > 0:
            # Sell if price expected to drop
            cash += shares * current_price
            shares = 0
            action = 'SELL'

        value = cash + shares * price
        results.append({'date': date, 'value': value})

        if action:
            trades.append({
                'date': date,
                'action': action,
                'shares': shares,
                'price': current_price,
                'value': value,
            })

        current_price = price

    # Final sell if still holding shares
    if shares > 0:
        cash += shares * current_price
        trades.append({
            'date': (last_date + pd.Timedelta(days=len(predictions))).strftime('%Y-%m-%d'),
            'action': 'SELL',
            'shares': shares,
            'price': current_price,
            'value': cash,
        })
        shares = 0

    note = '' if bought and not no_buy_expected else '지속적인 하락새로 인한 해당기간내에 매수의견이 없습니다.'
    return results, trades, note

index_template = """
<!doctype html>
<html lang=\"ko\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
  <meta property=\"og:type\" content=\"website\">
  <meta property=\"og:title\" content=\"Ai-Trade\">
  <meta property=\"og:description\" content=\"주식 데이터를 분석하고 시뮬레이션하는 웹 앱\">
  <meta property=\"og:url\" content=\"{{ url_for('stocks.index', _external=True) }}\">
  <meta property=\"og:image\" content=\"{{ OG_IMAGE_URL }}\">
  <title>저장된 종목</title>
</head>
<body class=\"bg-light\">
<nav class=\"navbar navbar-expand-lg navbar-dark bg-primary\">
  <div class=\"container\">
    <a class=\"navbar-brand\" href=\"{{ url_for('stocks.index') }}\">Ai-Trade</a>
    <div class=\"d-flex\">
      <span class=\"navbar-text me-3\">로그인: {{ g.user['username'] }}</span>
      <a class=\"btn btn-outline-light btn-sm\" href=\"{{ url_for('auth.logout') }}\">로그아웃</a>
    </div>
  </div>
</nav>

<div class=\"container py-4\">
  <h1 class=\"mb-4\">저장된 티커</h1>
  <form method=\"post\" class=\"row gy-2 gx-2 align-items-center mb-3\">
    <div class=\"col-auto\">
      <input name=\"ticker\" class=\"form-control\" placeholder=\"티커 추가\">
    </div>
    <div class=\"col-auto\">
        <button class=\"btn btn-success\" type=\"submit\">추가</button>
    </div>
  </form>
  {% if message %}
  <div class=\"alert alert-danger\">{{ message }}</div>
  {% endif %}
  <form method=\"get\" class=\"mb-3\">
    <div class=\"input-group\">
      <input name=\"q\" class=\"form-control\" placeholder=\"검색\" value=\"{{ search }}\">
      <button class=\"btn btn-outline-secondary\" type=\"submit\">검색</button>
    </div>
  </form>
  <ul class=\"list-group\">
    {% for t in tickers %}
      <li class=\"list-group-item\"><a href=\"{{ url_for('stocks.stock', ticker=t) }}\">{{ t }}</a></li>
    {% else %}
      <li class=\"list-group-item\">저장된 티커가 없습니다.</li>
    {% endfor %}
  </ul>
</div>
</body>
</html>
"""

template = """
<!doctype html>
<html lang=\"ko\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
  <meta property=\"og:type\" content=\"article\">
  <meta property=\"og:title\" content=\"{{ ticker }} 데이터 | Ai-Trade\">
  <meta property=\"og:description\" content=\"주식 차트와 시뮬레이션 결과 제공\">
  <meta property=\"og:url\" content=\"{{ url_for('stocks.stock', ticker=ticker, _external=True) }}\">
  <meta property=\"og:image\" content=\"{{ OG_IMAGE_URL }}\">
  <title>{{ ticker }} 데이터</title>
</head>
<body class=\"bg-light\">
<nav class=\"navbar navbar-expand-lg navbar-dark bg-primary\">
  <div class=\"container\">
    <a class=\"navbar-brand\" href=\"{{ url_for('stocks.index') }}\">Ai-Trade</a>
    <div class=\"d-flex\">
      <span class=\"navbar-text me-3\">로그인: {{ g.user['username'] }}</span>
      <a class=\"btn btn-outline-light btn-sm\" href=\"{{ url_for('auth.logout') }}\">로그아웃</a>
    </div>
  </div>
</nav>

<div class=\"container py-4\">
  <h1 class=\"mb-4\">{{ ticker }} 데이터</h1>
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
          <option value=\"line\" {% if chart_type == 'line' %}selected{% endif %}>선 차트</option>
          <option value=\"candlestick\" {% if chart_type == 'candlestick' %}selected{% endif %}>캔들스틱</option>
        </select>
      </div>
    </form>
    {{ graph|safe }}
    <div class=\"table-responsive\">
      <table class=\"table table-striped\">
        <thead>
          <tr><th>날짜</th><th>시가</th><th>고가</th><th>저가</th><th>종가</th><th>거래량</th></tr>
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
    <h2 class=\"mt-4\">시뮬레이션</h2>
    <form method=\"post\" class=\"row gy-2 gx-2 align-items-center mb-3\">
      <div class=\"col-auto\">
        <input name=\"seed\" class=\"form-control\" placeholder=\"시드\" value=\"{{ seed }}\">
      </div>
      <div class=\"col-auto\">
        <input name=\"days\" class=\"form-control\" placeholder=\"일수\" value=\"{{ days }}\">
      </div>
      <div class=\"col-auto\">
        <button class=\"btn btn-warning\" type=\"submit\">시뮬레이션 하기</button>
      </div>
    </form>
    {% if trades %}
    <div class=\"table-responsive\">
      <table class=\"table table-bordered\">
        <thead>
          <tr><th>날짜</th><th>구분</th><th>수량</th><th>가격</th><th>가치</th></tr>
        </thead>
        <tbody>
          {% for t in trades %}
          <tr>
            <td>{{ t.date }}</td>
            <td>{{ t.action }}</td>
            <td>{{ '{:.2f}'.format(t.shares) }}</td>
            <td>{{ '{:.2f}'.format(t.price) }}</td>
            <td>{{ '{:.2f}'.format(t.value) }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    <div class=\"mt-4\">
      {{ profit_graph|safe }}
    </div>
    {% endif %}
    {% if note %}
    <div class=\"alert alert-info mt-3\">{{ note }}</div>
    {% endif %}
    <h2 class=\"mt-4\">평균 뉴스 감정: {{ sentiment_label }}</h2>
    <h2 class=\"mt-4\">최근 뉴스</h2>
    <ul>
      {% for n in news %}
      <li><a href="{{ n['link'] }}" target="_blank">{{ n['title']|truncate(100) }}</a>{% if n.get('publisher') %} ({{ n['publisher'] }}){% endif %}</li>
      {% else %}
      <li>최근 뉴스를 찾을 수 없습니다.</li>
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
        data = fetch_stock_history(ticker, period=period)
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
        news = fetch_news(ticker)
        sentiment = analyze_sentiment(news)
        sentiment_label_val = sentiment_to_label(sentiment)
        preds = predict_prices(data, days=days, sentiment=sentiment)
        simulation, trades, note = (run_simulation(data, preds, seed)
                                    if request.method == 'POST' else ([], [], ''))
        profit_graph_html = ''
        if simulation:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=[r['date'] for r in simulation],
                                      y=[r['value'] for r in simulation],
                                      mode='lines+markers', name='Value'))
            fig2.update_layout(title='Portfolio Value', xaxis_title='Date',
                               yaxis_title='Value', template='plotly_white')
            profit_graph_html = pio.to_html(fig2, full_html=False)

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
            sentiment_label=sentiment_label_val,
            simulation=simulation,
            trades=trades,
            profit_graph=profit_graph_html,
            seed=seed,
            days=days,
            note=note,
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
            sentiment_label=sentiment_to_label(0.0),
            simulation=[],
            trades=[],
            profit_graph='',
            seed=seed,
            days=days,
            note='',
            error=str(e),
        )

