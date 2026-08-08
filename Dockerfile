# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.8.4 AS uv

FROM python:3.12-slim-bookworm AS server-build
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends gcc libcups2-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY cli ./cli
RUN uv sync --frozen --extra cups --no-dev --no-editable

FROM python:3.12-slim-bookworm AS server
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      libcups2 libffi8 libharfbuzz-subset0 libjpeg62-turbo libopenjp2-7 \
      libpango-1.0-0 libpangoft2-1.0-0 shared-mime-info \
      fonts-noto-core fonts-noto-mono curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=server-build --chown=app:app /app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl --fail --silent http://127.0.0.1:8000/healthz >/dev/null || exit 1
ENTRYPOINT ["print-mcp"]

FROM debian:bookworm-slim AS cups
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      cups cups-client cups-filters cups-ipp-utils printer-driver-all \
    && rm -rf /var/lib/apt/lists/*
COPY docker/cups/entrypoint.sh /usr/local/bin/cups-entrypoint
RUN chmod 0755 /usr/local/bin/cups-entrypoint
EXPOSE 631
VOLUME ["/etc/cups", "/var/spool/cups", "/var/cache/cups"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD lpstat -h 127.0.0.1:631 -r >/dev/null || exit 1
ENTRYPOINT ["/usr/local/bin/cups-entrypoint"]
