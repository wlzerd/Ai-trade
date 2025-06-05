from flask import Flask, render_template_string, request
import yfinance as yf
import plotly.graph_objects as go
import plotly.io as pio

app = Flask(__name__)

template = """
<!doctype html>
<title>Stock Data</title>
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

@app.route('/stock/<ticker>')
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
