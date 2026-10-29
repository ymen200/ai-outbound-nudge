# Use an explicit, lightweight Python runtime optimized for debian slim
FROM python:3.11-slim

# Prevent Python from writing .pyc files to disk and ensure logs print immediately
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Establish the working directory inside the isolated container
WORKDIR /app

# Install basic system packages required for Python dependency compilations
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy your dependency configurations first to maximize Docker layer caching
COPY requirements.txt .

# Install your project's pip libraries cleanly without saving local cache wheels
RUN pip install --no-cache-dir -r requirements.txt

# Copy the remaining codebase directories and configuration scripts into /app
COPY . .

# Set the container's execution entry point to run your full graph test suite
CMD ["pytest", "qualifier_agent/tests/test_full_pipeline.py", "-v"]