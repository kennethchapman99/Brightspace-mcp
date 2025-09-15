FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip
COPY pyproject.toml ./
RUN pip wheel --no-cache-dir --no-deps -w /wheels . || true
COPY . .
RUN pip install --no-cache-dir -e .

# Non-root user (optional)
# RUN useradd -m app && chown -R app:app /app && USER app

# Default to stdio MCP server
ENTRYPOINT ["brightspace-mcp", "--stdio"]

