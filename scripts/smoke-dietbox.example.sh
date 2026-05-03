#!/usr/bin/env bash
# Copiar para o servidor (ex.: /opt/nutrideby/smoke-dietbox.sh), chmod +x, apontar CRON para aqui.
# Pré-requisito: repo actualizado a partir do GitHub; Docker com serviço worker e .env com DIETBOX_*.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

docker compose --profile tools run --rm worker \
  python -m nutrideby.workers.dietbox_sync --smoke
