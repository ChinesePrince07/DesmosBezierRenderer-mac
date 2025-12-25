FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    potrace \
    libagg-dev \
    libpotrace-dev \
    pkg-config \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create frames directory
RUN mkdir -p frames

# Expose port
EXPOSE 5000

# Run the application
CMD ["python", "backend.py", "--yes", "--no-browser"]
