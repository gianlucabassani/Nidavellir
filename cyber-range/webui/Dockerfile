FROM node:22.16.0-bookworm-slim AS console-build
WORKDIR /console
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

# Metadata
LABEL description="Nidavellir WebUI - Flask Dashboard"

# Set working directory
WORKDIR /app

# Copy requirements first (for layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /app/webui
COPY --from=console-build /static/console/ /app/webui/static/console/

# Expose Flask port
EXPOSE 5000

# Set environment
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=webui.app:app

# Production server (FR-02, B16): gunicorn with ONE worker process and a thread
# pool (gthread). Threads, because the co-pilot route streams a response and holds
# its connection open — a sync worker would be blocked by one stream; gevent is
# avoided because the app uses blocking `requests` calls that would need
# monkey-patching. ONE process, because login throttling state is in-process.
# The worker heartbeat timeout does not bound a gthread request, so streams are
# not killed at 120 s. The dev overlay runs `python webui/app.py` for the reloader.
CMD ["gunicorn", "--chdir", "/app/webui", "--bind", "0.0.0.0:5000", \
     "--worker-class", "gthread", "--workers", "1", "--threads", "32", \
     "--timeout", "120", "--graceful-timeout", "30", "--access-logfile", "-", \
     "app:app"]
