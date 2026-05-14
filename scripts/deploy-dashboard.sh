#!/usr/bin/env bash
set -euo pipefail
IMAGE="ghcr.io/wss13framework/nutrideby-dashboard:latest"
CONTAINER="nutrideby-dashboard"
ENV_FILE="/opt/automa-aoNutriDeby/dashboard/.env"
NETWORK="automa-aonutrideby_default"
echo "[*] Pulling imagem: $IMAGE"
docker pull "$IMAGE"
echo "[*] Parando container antigo..."
docker rm -f "$CONTAINER" 2>/dev/null || true
echo "[*] Subindo container..."
docker run -d --name "$CONTAINER" --network "$NETWORK" --env-file "$ENV_FILE" \
  -p 3000:3000 --restart unless-stopped \
  --log-opt max-size=10m --log-opt max-file=3 "$IMAGE"
sleep 3
curl -sf http://localhost:3000/login > /dev/null 2>&1 && echo "[OK] Dashboard rodando" || echo "[WARN] Verificar: docker logs $CONTAINER"
docker image prune -f
