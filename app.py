from flask import Flask, render_template_string
import yfinance as yf

app = Flask(__name__)

template = """
<!doctype html>
<title>Stock Data</title>
<h1>Stock Data for {{ ticker }}</h1>
{% if error %}
<p style='color: red;'>{{ error }}</p>
{% else %}
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
    try:
        stock = yf.Ticker(ticker)
        data = stock.history(period="5d")
        if data.empty:
            raise ValueError("No data found for ticker")
        return render_template_string(template, ticker=ticker, data=data, error=None)
    except Exception as e:
        return render_template_string(template, ticker=ticker, data=None, error=str(e))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
