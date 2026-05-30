FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Database lives on a mounted volume at /code/data
RUN mkdir -p /code/data

EXPOSE 8000

# --proxy-headers/--forwarded-allow-ips let the app honour X-Forwarded-Proto/Host
# from a TLS reverse proxy (Caddy), so OIDC redirect URLs are built as https.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
