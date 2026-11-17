FROM python:3.11-slim

# Metadata
LABEL description="Nidavellir Orchestrator - Backend API & Celery Worker"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    unzip \
    git \
    openssh-client \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install OpenTofu
ARG TOFU_VERSION=1.6.0
RUN wget -q https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/tofu_${TOFU_VERSION}_linux_amd64.zip \
    && unzip tofu_${TOFU_VERSION}_linux_amd64.zip \
    && mv tofu /usr/local/bin/ \
    && rm tofu_${TOFU_VERSION}_linux_amd64.zip \
    && chmod +x /usr/local/bin/tofu

# Set working directory
WORKDIR /app

# Copy requirements first (for layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /app/

# Create directories for runtime data
RUN mkdir -p /app/runs /app/data /app/keys /app/cache/terraform-plugins

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV TF_PLUGIN_CACHE_DIR=/app/cache/terraform-plugins
ENV PYTHONPATH=/app

# Expose API port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
