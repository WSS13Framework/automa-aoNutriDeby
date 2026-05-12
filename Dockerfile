# Imagem com Python + browsers Playwright (Chromium).
# Versão alinhada com o pacote `playwright` em pyproject.toml (browsers em /ms-playwright/).
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

# Dependências do projeto (sincronizar com pyproject.toml — NÃO instalar o pacote nutrideby).
# O código corre só de /app/src (volume), evitando cópia antiga em site-packages.
COPY pyproject.toml README.md ./
RUN pip install --upgrade pip && \
    pip install \
    "redis>=5.0.0" \
    "boto3>=1.35.0" \
    "fastapi>=0.115.0" \
    "opensearch-py>=2.4.0" \
    "playwright==1.58.0" \
    "psycopg[binary]>=3.2.0" \
    "pydantic-settings>=2.6.0" \
    "selenium>=4.15.0" \
    "uvicorn[standard]>=0.32.0"

COPY src ./src

# Browsers já inclusos na imagem base; garantir deps do Chromium.
RUN playwright install-deps chromium || true

CMD ["python", "-m", "nutrideby.workers.crm_extract", "--dry-run"]
