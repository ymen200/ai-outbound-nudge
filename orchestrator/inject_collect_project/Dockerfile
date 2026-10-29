# Stage 1: Builder stage for dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

# Install system dependencies for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies to system site-packages
RUN pip install --no-cache-dir -r requirements.txt


# Stage 2: Final runtime image
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies for Playwright, PDF processing, and system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright dependencies
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libgbm1 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxss1 \
    fonts-liberation \
    xdg-utils \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/app/.cache/playwright \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0

# Copy project files
COPY . .

# Create output directories
RUN mkdir -p scraped_data merged_profiles comparisons personas_discovered

# Create non-root user BEFORE installing playwright
RUN useradd -m -u 1000 appuser

# Install Playwright browsers as root (globally accessible)
RUN playwright install chromium && playwright install-deps chromium

# Make app directory writable by appuser
RUN chown -R appuser:appuser /app

USER appuser

# Default command - can be overridden
CMD ["python", "main_discovery.py"]
