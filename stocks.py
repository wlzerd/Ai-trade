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
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import openai
import pandas as pd
from dotenv import load_dotenv
from anomalies import detect_anomalies

load_dotenv()
# Placeholder image used for social previews
OG_IMAGE_URL = os.getenv("LOGO")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")

from db import get_db
from auth import login_required

bp = Blueprint("stocks", __name__)


def canvas_chart_block(dates, opens, highs, lows, closes, chart_type):
    """Return HTML for a canvas-based stock chart."""
    template = """
<canvas id=\"chart\" width=\"800\" height=\"400\"></canvas>
<script>
const dates = {{ dates|tojson }};
const opens = {{ opens|tojson }};
const highs = {{ highs|tojson }};
const lows = {{ lows|tojson }};
const closes = {{ closes|tojson }};
const chartType = "{{ chart_type }}";
let offset = 0;
let scale = 1;
const canvas = document.getElementById('chart');
const ctx = canvas.getContext('2d');
const paddingRight = 50;
const paddingBottom = 20;

function draw(){
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const chartWidth = canvas.width - paddingRight;
    const chartHeight = canvas.height - paddingBottom;
    const min = Math.min(...lows);
    const max = Math.max(...highs);
    const range = max - min || 1;
    const step = chartWidth / (dates.length * scale);
    if(chartType === 'line'){
        ctx.strokeStyle = 'blue';
        ctx.beginPath();
        closes.forEach((c,i)=>{
            const x = (i - offset) * step;
            const y = chartHeight - ((c - min) / range) * chartHeight;
            if(i===0){ctx.moveTo(x,y);}else{ctx.lineTo(x,y);}
        });
        ctx.stroke();
    }else{
        closes.forEach((c,i)=>{
            const x = (i - offset) * step;
            const highY = chartHeight - ((highs[i]-min)/range)*chartHeight;
            const lowY = chartHeight - ((lows[i]-min)/range)*chartHeight;
            const openY = chartHeight - ((opens[i]-min)/range)*chartHeight;
            const closeY = chartHeight - ((closes[i]-min)/range)*chartHeight;
            ctx.strokeStyle = 'black';
            ctx.beginPath();
            ctx.moveTo(x, highY);
            ctx.lineTo(x, lowY);
            ctx.stroke();
            ctx.fillStyle = closes[i] >= opens[i] ? 'green' : 'red';
            const rectY = Math.min(openY, closeY);
            const rectH = Math.abs(openY - closeY) || 1;
            ctx.fillRect(x - step*0.3, rectY, step*0.6, rectH);
        });
    }
    // axes
    ctx.strokeStyle = '#000';
    ctx.beginPath();
    ctx.moveTo(chartWidth, 0);
    ctx.lineTo(chartWidth, chartHeight);
    ctx.moveTo(0, chartHeight);
    ctx.lineTo(chartWidth, chartHeight);
    ctx.stroke();
    ctx.fillStyle = '#000';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    const ticks = 4;
    for(let i=0;i<=ticks;i++){
        const price = min + (range*(ticks-i)/ticks);
        const y = (chartHeight*i)/ticks;
        ctx.fillText(price.toFixed(2), chartWidth+4, y);
    }
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    const stepDate = Math.max(1, Math.round(dates.length/5));
    for(let i=0;i<dates.length;i+=stepDate){
        const x = (i - offset) * step;
        if(x >= 0 && x <= chartWidth){
            ctx.fillText(dates[i], x, chartHeight+2);
        }
    }
}

draw();

let drag = false;
let lastX = 0;
let pinch = null;

canvas.addEventListener('mousedown', e => {drag = true; lastX = e.clientX;});
canvas.addEventListener('mousemove', e => {
    if(drag){
        const step = (canvas.width - paddingRight) / (dates.length * scale);
        offset += (lastX - e.clientX) / step;
        lastX = e.clientX;
        draw();
    }
});
window.addEventListener('mouseup', () => {drag = false;});

canvas.addEventListener('wheel', e => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 1.1 : 0.9;
    scale *= delta;
    draw();
});

canvas.addEventListener('touchstart', e => {
    if(e.touches.length === 2){
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        pinch = Math.hypot(dx, dy);
    }else if(e.touches.length === 1){
        drag = true;
        lastX = e.touches[0].clientX;
    }
});
canvas.addEventListener('touchmove', e => {
    e.preventDefault();
    if(e.touches.length === 2){
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        const dist = Math.hypot(dx, dy);
        if(pinch){
            scale *= pinch / dist;
            pinch = dist;
            draw();
        }
    }else if(drag && e.touches.length === 1){
        const step = (canvas.width - paddingRight) / (dates.length * scale);
        offset += (lastX - e.touches[0].clientX) / step;
        lastX = e.touches[0].clientX;
        draw();
    }
});
canvas.addEventListener('touchend', () => {drag=false; pinch=null;});
</script>
"""

    return render_template_string(
        template,
        dates=dates,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        chart_type=chart_type,
    )


def fetch_stock_history(ticker, period="1y", interval="1d"):
    """Fetch historical stock prices from Polygon.io.

    ``interval`` controls the aggregation resolution (e.g. ``1m``,
    ``5m``, ``15m``, ``1h``, ``1d``) which maps to Polygon's
    ``range/{multiplier}/{timespan}`` URL segments.
    """
    if not POLYGON_API_KEY:
        raise ValueError("POLYGON_API_KEY not set")

    end_dt = pd.Timestamp.utcnow()
    start_dt = end_dt - pd.Timedelta(days=365)

    m = re.match(r"(\d+)([a-zA-Z]+)", interval)
    multiplier = int(m.group(1)) if m else 1
    unit = m.group(2).lower() if m else "d"
    unit_map = {"m": "minute", "min": "minute", "h": "hour", "d": "day"}
    timespan = unit_map.get(unit, "day")

    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/"
        f"{multiplier}/{timespan}/"
        f"{start_dt.strftime('%Y-%m-%d')}/{end_dt.strftime('%Y-%m-%d')}"
    )
    params = {"adjusted": "true", "sort": "asc", "apiKey": POLYGON_API_KEY}
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    # Polygon sometimes returns a "DELAYED" status even when data is valid,
    # so treat it the same as "OK" when results are present.
    if data.get("status") not in ("OK", "DELAYED") or not data.get("results"):
        raise ValueError(f"Polygon error: {data}")

    results = data.get("results", [])
    df = pd.DataFrame(
        {
            "Open": [r.get("o") for r in results],
            "High": [r.get("h") for r in results],
            "Low": [r.get("l") for r in results],
            "Close": [r.get("c") for r in results],
            "Volume": [r.get("v") for r in results],
        },
        index=pd.to_datetime([r.get("t") for r in results], unit="ms"),
    )
    df = df.sort_index()
    days_map = {"5d": 5, "1mo": 22, "3mo": 66, "6mo": 132, "1y": 264}
    days = days_map.get(period, 5)
    return df.tail(days)


def gpt_predict_prices(data, days, sentiment):
    key = os.getenv("OPENAI_API_KEY")
    if not key or data is None or data.empty or "Close" not in data:
        return None
    try:
        client = openai.OpenAI(api_key=key)
        closes = [round(float(c), 2) for c in data["Close"].tail(180).tolist()]
        prompt = (
            "Predict the next "
            f"{days} closing prices based on this series: {closes} "
            f"and an average news sentiment of {sentiment:.3f}. "
            "Respond with numbers only."
        )
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        text = resp.choices[0].message.content
        nums = re.findall(r"-?\d+\.\d+|-?\d+", text)
        out = [float(n) for n in nums][:days]
        if len(out) == days:
            return out
    except Exception:
        pass
    return None


def predict_prices(data, days=5, sentiment=0.0):
    """Predict future close prices using GPT or an AR(1) fallback."""
    if data is None or data.empty or "Close" not in data:
        return []

    preds = gpt_predict_prices(data, days, sentiment)
    if preds is not None:
        return preds

    closes = data["Close"]
    if len(closes) < 3:
        return []

    diffs = closes.diff().dropna()
    x = diffs.iloc[:-1]
    y = diffs.iloc[1:]
    if len(x) == 0:
        return []

    x_mean = x.mean()
    y_mean = y.mean()
    denom = ((x - x_mean) ** 2).sum()
    slope = ((x - x_mean) * (y - y_mean)).sum() / denom if denom != 0 else 0.0
    intercept = y_mean - slope * x_mean

    current_price = closes.iloc[-1]
    last_diff = diffs.iloc[-1]
    predictions = []
    for _ in range(days):
        next_diff = intercept + slope * last_diff
        if sentiment > 0.1:
            next_diff *= 1.05
        elif sentiment < -0.1:
            next_diff *= 0.95
        current_price += next_diff
        predictions.append(float(current_price))
        last_diff = next_diff
    return predictions


def fetch_news(ticker):
    """Return a list of recent news articles for the given ticker.

    Uses Polygon.io's reference news endpoint when a ``POLYGON_API_KEY`` is
    configured. If the key is missing or the request fails, headlines are
    retrieved from the Yahoo Finance RSS feed instead.
    """
    news = []
    if POLYGON_API_KEY:
        try:
            params = {
                "ticker": ticker,
                "limit": 5,
                "apiKey": POLYGON_API_KEY,
            }
            resp = requests.get(
                "https://api.polygon.io/v2/reference/news", params=params, timeout=10
            )
            data = resp.json()
            for item in data.get("results", []):
                title = item.get("title", "")
                link = item.get("article_url")
                publisher = item.get("publisher", {}).get("name")
                if title and link:
                    news.append({"title": title, "link": link, "publisher": publisher})
            if news:
                return news
        except Exception:
            pass

    # Fallback to Yahoo RSS feed if Polygon request fails
    try:
        feed_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
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
        client = openai.OpenAI(api_key=key)
        text = "\n".join(n["title"] for n in news)
        prompt = (
            "Give a single sentiment score between -1 and 1 for these headlines:"
            f"\n{text}\nScore:"
        )
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        out = resp.choices[0].message.content.strip()
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
    scores = [analyzer.polarity_scores(n["title"])["compound"] for n in news]
    return sum(scores) / len(scores)


def sentiment_to_label(score):
    """Return human readable sentiment label."""
    if score > 0.1:
        return "긍정적"
    if score < -0.1:
        return "부정적"
    return "보통"


def gpt_explain_predictions(predictions, sentiment, news):
    """Return GPT reasoning for the predicted prices if possible."""
    key = os.getenv("OPENAI_API_KEY")
    if not key or not predictions:
        return ""
    try:
        client = openai.OpenAI(api_key=key)
        titles = "\n".join(n["title"] for n in news) if news else ""
        prompt = (
            "다음 종가 예측 값들을 참고하여 왜 이런 결과가 예상되는지 200토큰으로 간단히 말해 "
            "한국어로 설명해줘."
            f"\n예측: {predictions}\n뉴스 감정: {sentiment:.3f}\n"
            f"제목들:\n{titles}"
        )
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return ""


def run_simulation(data, predictions, balance):
    """Simulate adaptive trading based on predicted prices."""
    if data is None or data.empty or "Close" not in data or not predictions:
        return [], [], ""

    last_date = data.index[-1]
    start_price = float(data["Close"].iloc[-1])
    current_price = start_price
    no_buy_expected = not any(p > start_price for p in predictions)
    cash = balance
    shares = 0.0
    trades = []
    results = []
    bought = False

    for i, price in enumerate(predictions, start=1):
        date = (last_date + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        action = None

        if price > current_price and price > start_price and cash >= current_price:
            # Buy as price expected to rise beyond the starting price
            shares_to_buy = cash / current_price
            cash -= shares_to_buy * current_price
            shares += shares_to_buy
            action = "BUY"
            bought = True
        elif price < current_price and shares > 0:
            # Sell if price expected to drop
            cash += shares * current_price
            shares = 0
            action = "SELL"

        value = cash + shares * price
        results.append({"date": date, "value": value})

        if action:
            trades.append(
                {
                    "date": date,
                    "action": action,
                    "shares": shares,
                    "price": current_price,
                    "value": value,
                }
            )

        current_price = price

    # Final sell if still holding shares
    if shares > 0:
        cash += shares * current_price
        trades.append(
            {
                "date": (last_date + pd.Timedelta(days=len(predictions))).strftime(
                    "%Y-%m-%d"
                ),
                "action": "SELL",
                "shares": shares,
                "price": current_price,
                "value": cash,
            }
        )
        shares = 0

    note = (
        ""
        if bought and not no_buy_expected
        else "지속적인 하락새로 인한 해당기간내에 매수의견이 없습니다."
    )
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
        <select name=\"interval\" class=\"form-select\" onchange=\"this.form.submit()\">
          {% for i in ['1m','5m','15m','1h','1d'] %}
          <option value=\"{{ i }}\" {% if i == interval %}selected{% endif %}>{{ i }}</option>
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
    {{ chart_html|safe }}
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
    <h2 class=\"mt-4\">GPT기반 시뮬레이션</h2>
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
    {% endif %}
    <div class=\"mt-4\">
      {% if profit_graph %}
      {{ profit_graph|safe }}
      {% endif %}
      {% if simulation %}
      <p class=\"mt-2 text-muted\">
        예측된 종가: {% for p in predictions %}{{ '{:.2f}'.format(p) }}{% if not loop.last %}, {% endif %}{% endfor %}.<br>
        {{ prediction_reason }}
      </p>
      {% endif %}
    </div>
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


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    conn = get_db()
    cursor = conn.cursor()
    message = None
    if request.method == "POST":
        ticker = request.form.get("ticker", "").upper().strip()
        if ticker:
            try:
                cursor.execute("INSERT INTO tickers (ticker) VALUES (?)", (ticker,))
                conn.commit()
                conn.close()
                return redirect(url_for("stocks.index"))
            except Exception:
                message = "Ticker already saved."
    search = request.args.get("q", "").upper()
    if search:
        cursor.execute(
            "SELECT ticker FROM tickers WHERE ticker LIKE ?", (f"%{search}%",)
        )
    else:
        cursor.execute("SELECT ticker FROM tickers")
    tickers = [row["ticker"] for row in cursor.fetchall()]
    conn.close()
    return render_template_string(
        index_template, tickers=tickers, search=search, message=message
    )


@bp.route("/stock/<ticker>", methods=["GET", "POST"])
@login_required
def stock(ticker):
    period = request.args.get("period", "1y")
    interval = request.args.get("interval", "1d")
    chart_type = request.args.get("chart_type", "line")
    seed = 10000.0
    days = 5
    if request.method == "POST":
        seed = float(request.form.get("seed", 10000))
        days = int(request.form.get("days", 5))
    try:
        data = fetch_stock_history(ticker, period=period, interval=interval)
        if data.empty:
            raise ValueError("No data found for ticker")

        dates = data.index.strftime("%Y-%m-%d").tolist()
        opens = data["Open"].astype(float).round(2).tolist()
        highs = data["High"].astype(float).round(2).tolist()
        lows = data["Low"].astype(float).round(2).tolist()
        closes = data["Close"].astype(float).round(2).tolist()

        chart_html = canvas_chart_block(dates, opens, highs, lows, closes, chart_type)
        news = fetch_news(ticker)
        sentiment = analyze_sentiment(news)
        sentiment_label_val = sentiment_to_label(sentiment)
        preds = predict_prices(data, days=days, sentiment=sentiment)
        reason = gpt_explain_predictions(preds, sentiment, news)
        if not reason:
            reason = (
                f"최근 {sentiment_label_val} 뉴스 감정({sentiment:.3f})과 "
                "과거 가격 추세를 고려해 예측했습니다."
            )
        simulation, trades, note = (
            run_simulation(data, preds, seed)
            if request.method == "POST"
            else ([], [], "")
        )
        profit_graph_html = ""
        if simulation:
            preds = predict_prices(data, days=days, sentiment=sentiment)
            reason = gpt_explain_predictions(preds, sentiment, news)

        return render_template_string(
            template,
            ticker=ticker,
            data=data,
            period=period,
            interval=interval,
            chart_type=chart_type,
            chart_html=chart_html,
            dates=dates,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            predictions=preds,
            prediction_reason=reason,
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
            interval=interval,
            chart_type=chart_type,
            chart_html="",
            dates=[],
            opens=[],
            highs=[],
            lows=[],
            closes=[],
            predictions=[],
            prediction_reason="",
            news=[],
            sentiment=0.0,
            sentiment_label=sentiment_to_label(0.0),
            simulation=[],
            trades=[],
            profit_graph="",
            seed=seed,
            days=days,
            note="",
            error=str(e),
        )

@bp.route("/anomalies/<ticker>")
@login_required
def show_anomalies(ticker):
    """Display high trade count periods for the given ticker."""
    date = request.args.get("date") or pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    threshold = float(request.args.get("threshold", 3.0))
    try:
        anomalies, mean, std = detect_anomalies(ticker, date, threshold)
        rows = [
            {"time": ts.strftime("%H:%M"), "count": int(cnt)}
            for ts, cnt in anomalies.items()
        ]
    except Exception as e:
        rows = []
        mean = std = 0.0
        error = str(e)
    else:
        error = None
    template_html = """
    <!doctype html>
    <html lang='ko'>
    <head>
    <meta charset='utf-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1'>
    <link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css' rel='stylesheet'>
    <title>{{ ticker }} anomalies</title>
    </head>
    <body class='container py-4'>
    <h1>{{ ticker }} {{ date }} 거래 이상 탐지</h1>
    {% if error %}<div class='alert alert-danger'>{{ error }}</div>{% endif %}
    <p>평균 {{ mean:.2f }}건, 표준편차 {{ std:.2f }} 기준 {{ threshold }}배 이상인 구간</p>
    <table class='table table-sm'>
    <tr><th>시간</th><th>거래 수</th></tr>
    {% for r in rows %}
    <tr><td>{{ r.time }}</td><td>{{ r.count }}</td></tr>
    {% endfor %}
    </table>
    </body>
    </html>
    """
    return render_template_string(
        template_html,
        ticker=ticker,
        date=date,
        rows=rows,
        mean=mean,
        std=std,
        threshold=threshold,
        error=error,
    )
