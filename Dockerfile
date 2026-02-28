FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency installation
RUN pip install --no-cache-dir uv

# Copy dependency files first for better layer caching
COPY pyproject.toml ./

# Install dependencies
RUN uv pip install --system --no-cache -e .

# Copy application code
COPY . .

EXPOSE 8080

CMD ["python", "main.py"]
