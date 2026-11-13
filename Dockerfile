# syntax=docker/dockerfile:1
#
# Targets:
#   dev  — used by .devcontainer; source is bind-mounted, deps installed by postCreateCommand
#   prod — default; the image deployed to AWS
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --create-home --uid 1000 app
WORKDIR /app


FROM base AS dev
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/* \
 && python -m venv /opt/venv && chown -R app:app /opt/venv
ENV PATH=/opt/venv/bin:$PATH
USER app


FROM base AS prod
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install . \
 && mkdir -p /data && chown app:app /data
USER app
ENV APP_ENV=prod \
    SCRAPE_MODE=live \
    DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"
# Open /events streams would otherwise hold up shutdown during deploys.
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8080", \
     "--timeout-graceful-shutdown", "5"]
