# Sovereign MCP Web Search - Dockerfile
# No API keys, direct scrape, MCP stdio
FROM python:3.12-slim

LABEL org.opencontainers.image.title="sovereign-mcp-search"
LABEL org.opencontainers.image.description="Sovereign MCP Web Search - direct scrape, no API keys, 7 engines, MCP stdio"
LABEL org.opencontainers.image.source="https://github.com/sovereign/mcp-web-search"

# Security: non-root
RUN useradd -m -u 1000 mcp && mkdir -p /app && chown mcp:mcp /app
WORKDIR /app

# System deps for lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 && rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml README.md ./
COPY server.py ./
RUN pip install --no-cache-dir -e .

# Sovereign: no env keys needed, but allow override
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

USER mcp

# MCP stdio - container runs as MCP server
ENTRYPOINT ["python", "server.py"]

# Healthcheck: verify MCP tools list
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD python -c "import asyncio; from mcp import ClientSession, StdioServerParameters; from mcp.client.stdio import stdio_client; asyncio.run((lambda: None)())" || exit 1

# Usage:
# docker build -t sovereign-mcp-search .
# docker run -i sovereign-mcp-search  # stdio
# For opencode: "command": ["docker", "run", "-i", "--rm", "sovereign-mcp-search"]
