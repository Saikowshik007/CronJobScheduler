FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    gcc \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium only for efficiency)
RUN playwright install --with-deps chromium

# Copy application code
COPY src/ ./src/

# Run the application
CMD ["python", "-u", "src/main.py"]
