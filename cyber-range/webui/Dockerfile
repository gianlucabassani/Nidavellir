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

# Default command
CMD ["python", "webui/app.py"]
