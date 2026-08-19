FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Seed the data file on first startup so /jobs is non-empty immediately.
# In production the ingester would run on a schedule; here we run it once
# at container boot so a reviewer sees data the moment the server is live.
CMD ["sh", "-c", "python ingester.py && uvicorn main:app --host 0.0.0.0 --port 8000"]
