# Imagem com Python + browsers Playwright (Chromium).
# Versão alinhada com o pacote `playwright` em pyproject.toml (browsers em /ms-playwright/).
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

COPY pyproject.toml README.md ./
COPY src ./src

# Instalação em modo editável: o volume ./src:/app/src substitui o código sem rebuild.
RUN pip install --upgrade pip && pip install -e .

# Browsers já inclusos na imagem base; garantir deps do Chromium.
RUN playwright install-deps chromium || true

CMD ["python", "-m", "nutrideby.workers.crm_extract", "--dry-run"]
