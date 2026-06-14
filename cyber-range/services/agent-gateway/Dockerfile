FROM python:3.11-slim

LABEL description="CyberGuard MCP Agent Gateway"

WORKDIR /app

# Requirements first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Package code (the `gateway` package lives under /app/gateway).
COPY . /app/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
# Containerized: bind all interfaces; exposure is governed by the compose port
# mapping / network, not the bind address.
ENV CYBERGUARD_GATEWAY_HOST=0.0.0.0
ENV CYBERGUARD_GATEWAY_TRANSPORT=streamable-http

EXPOSE 9000

CMD ["python", "-m", "gateway.server"]
