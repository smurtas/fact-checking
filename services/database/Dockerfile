# Dockerfile for a lightweight DuckDB Python environment
FROM python:3.10-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . . 

# Default command: open DuckDB Python shell
CMD ["python3"]
