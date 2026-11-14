# Container for the built-in MCP server, used by directory indexes (Glama,
# MCP registry crawlers) that build a server and check it answers JSON-RPC.
#
# The package has zero runtime dependencies, so the image is the interpreter
# plus this repository and nothing else.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Run as an unprivileged user: the server reads a workspace, it never needs root.
RUN useradd --create-home --uid 10001 mcp
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY skillporter ./skillporter
RUN pip install --no-cache-dir .

USER mcp
WORKDIR /workspace

# stdio transport, read-only unless --allow-writes is passed explicitly.
ENTRYPOINT ["skillporter", "mcp"]