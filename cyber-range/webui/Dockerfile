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

# Expose Flask port
EXPOSE 5000

# Set environment
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=webui.app:app

# Default command
CMD ["python", "webui/app.py"]
