from flask import (
    Blueprint,
    render_template_string,
    request,
    redirect,
    url_for,
)
import yfinance as yf
import plotly.graph_objects as go
import plotly.io as pio

from db import get_db
from auth import login_required

bp = Blueprint('stocks', __name__)


def predict_prices(data, days=5):
    """Naively predict future close prices using recent average change."""
    if data is None or data.empty or 'Close' not in data:
        return []

    closes = data['Close']
    if len(closes) < 2:
        return []

    diffs = closes.diff().dropna()
    avg_change = diffs.tail(5).mean()
    last = closes.iloc[-1]
    predictions = []
    for _ in range(days):
        last += avg_change
        predictions.append(float(last))
    return predictions

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
    <h2 class=\"mt-4\">Predicted Close Prices (Next 5 days)</h2>
    <ul>
      {% for price in predictions %}
      <li>Day {{ loop.index }}: {{ '{:.2f}'.format(price) }}</li>
      {% endfor %}
    </ul>
    <h2 class=\"mt-4\">Latest News</h2>
    <ul>
      {% for n in news %}
      <li><a href="{{ n['link'] }}" target="_blank">{{ n['title'] }}</a>{% if n.get('publisher') %} ({{ n['publisher'] }}){% endif %}</li>
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


@bp.route('/stock/<ticker>')
@login_required
def stock(ticker):
    period = request.args.get('period', '5d')
    chart_type = request.args.get('chart_type', 'line')
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
        preds = predict_prices(data)
        news = []
        try:
            fetched = []
            if hasattr(stock, 'get_news'):
                fetched = stock.get_news()
            elif hasattr(stock, 'news'):
                fetched = stock.news

            if hasattr(fetched, 'to_dict'):
                fetched = fetched.to_dict('records')

            news = list(fetched)[:5]
        except Exception:
            news = []

        return render_template_string(
            template,
            ticker=ticker,
            data=data,
            period=period,
            chart_type=chart_type,
            graph=graph_html,
            predictions=preds,
            news=news,
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
            error=str(e),
        )

