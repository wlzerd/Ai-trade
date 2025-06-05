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

index_template = """
<!doctype html>
<title>Saved Stocks</title>
{% if g.user %}
<p>Logged in as {{ g.user['username'] }} | <a href="{{ url_for('auth.logout') }}">Logout</a></p>
{% else %}
<p><a href="{{ url_for('auth.login') }}">Login</a> | <a href="{{ url_for('auth.register') }}">Register</a></p>
{% endif %}
<h1>Saved Tickers</h1>
<form method="post">
    <input name="ticker" placeholder="Add ticker" />
    <button type="submit">Add</button>
</form>
{% if message %}
<p style="color:red;">{{ message }}</p>
{% endif %}
<form method="get">
    <input name="q" placeholder="Search" value="{{ search }}" />
    <button type="submit">Search</button>
</form>
<ul>
{% for t in tickers %}
    <li><a href="{{ url_for('stocks.stock', ticker=t) }}">{{ t }}</a></li>
{% else %}
    <li>No tickers found.</li>
{% endfor %}
</ul>
"""

template = """
<!doctype html>
<title>Stock Data</title>
{% if g.user %}
<p>Logged in as {{ g.user['username'] }} | <a href="{{ url_for('auth.logout') }}">Logout</a></p>
{% else %}
<p><a href="{{ url_for('auth.login') }}">Login</a> | <a href="{{ url_for('auth.register') }}">Register</a></p>
{% endif %}
<h1>Stock Data for {{ ticker }}</h1>
{% if error %}
<p style='color: red;'>{{ error }}</p>
{% else %}
<form method="get">
    Period:
    <select name="period" onchange="this.form.submit()">
        {% for p in ['5d', '1mo', '3mo', '6mo', '1y'] %}
        <option value="{{ p }}" {% if p == period %}selected{% endif %}>{{ p }}</option>
        {% endfor %}
    </select>
    Chart Type:
    <select name="chart_type" onchange="this.form.submit()">
        <option value="line" {% if chart_type == 'line' %}selected{% endif %}>Line</option>
        <option value="candlestick" {% if chart_type == 'candlestick' %}selected{% endif %}>Candlestick</option>
    </select>
</form>
{{ graph|safe }}
<table border="1">
<tr><th>Date</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th></tr>
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
</table>
{% endif %}
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

        fig.update_layout(title=f"{ticker} Price", xaxis_title="Date", yaxis_title="Price")
        graph_html = pio.to_html(fig, full_html=False)

        return render_template_string(template, ticker=ticker, data=data,
                                      period=period, chart_type=chart_type,
                                      graph=graph_html, error=None)
    except Exception as e:
        return render_template_string(template, ticker=ticker, data=None,
                                      period=period, chart_type=chart_type,
                                      graph='', error=str(e))

