FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Database lives on a mounted volume at /code/data
RUN mkdir -p /code/data

# Drop root: run the app as an unprivileged user. The host bind-mount at
# ./data must be writable by uid 10001 (the install.sh installer handles
# this; for hand-rolled deploys, `chown 10001:10001 ./data` once).
RUN useradd --system --uid 10001 --gid 0 --home-dir /code --shell /usr/sbin/nologin app \
    && chown -R 10001:0 /code
USER 10001

EXPOSE 8000

# --proxy-headers/--forwarded-allow-ips let the app honour X-Forwarded-Proto/Host
# from a TLS reverse proxy (Caddy), so OIDC redirect URLs are built as https.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
