# Secure Shift - Cloud Run image
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080 \
    LOCAL_DB_PATH=/tmp/secure-shift/demo.db

WORKDIR /app

# Dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (secrets are excluded by .dockerignore)
COPY . .

# Run as an unprivileged user
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /tmp/secure-shift \
    && chown -R appuser:appuser /app /tmp/secure-shift
USER appuser

EXPOSE 8080

# Cloud Run injects $PORT; Streamlit must bind 0.0.0.0
CMD ["sh", "-c", "exec streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true"]
