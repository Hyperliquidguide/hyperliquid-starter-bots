# Runs the read-only MCP server (hl-guide-mcp) over stdio. No keys needed.
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
ENTRYPOINT ["hl-guide-mcp"]
