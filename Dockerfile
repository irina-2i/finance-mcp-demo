# Small, non-root image that runs the MCP server over stdio.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Sample data is baked in; mount your own folder to /data and set FINANCE_RAW_DIR=/data instead.
COPY data/raw /app/data/raw
ENV FINANCE_RAW_DIR=/app/data/raw

RUN useradd --create-home --uid 10001 mcp
USER mcp

CMD ["python", "-m", "finance_mcp.server"]
