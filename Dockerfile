# Imagem com Python + browsers Playwright (Chromium).
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip && pip install .

# Browsers já inclusos na imagem base; garantir deps do Chromium.
RUN playwright install-deps chromium || true

CMD ["python", "-m", "nutrideby.workers.crm_extract", "--dry-run"]
