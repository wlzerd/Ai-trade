FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create a volume for the SQLite database file
VOLUME ["/app/stocks.db"]

# Set environment variables
ENV FLASK_APP=app.py

EXPOSE 5000

CMD ["python", "app.py"]
