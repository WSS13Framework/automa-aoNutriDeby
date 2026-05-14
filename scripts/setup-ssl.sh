#!/usr/bin/env bash
set -euo pipefail
SSL_DIR="/opt/automa-aoNutriDeby/infra/nginx/ssl"
CERTBOT_DIR="/opt/automa-aoNutriDeby/infra/nginx/certbot"
DOMAIN="${1:-}"
mkdir -p "$SSL_DIR" "$CERTBOT_DIR"
if [ -n "$DOMAIN" ]; then
    echo "[*] Gerando certificado Let's Encrypt para $DOMAIN..."
    command -v certbot &>/dev/null || { apt-get update -qq && apt-get install -y -qq certbot; }
    docker stop nutrideby-nginx 2>/dev/null || true
    certbot certonly --standalone -d "$DOMAIN" --non-interactive --agree-tos \
        --email "admin@nutrideby.com.br" || {
        echo "[WARN] Certbot falhou. Gerando self-signed..."
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout "$SSL_DIR/privkey.pem" -out "$SSL_DIR/fullchain.pem" \
            -subj "/CN=$DOMAIN/O=NutriDeby/C=BR"
    }
    cp /etc/letsencrypt/live/"$DOMAIN"/fullchain.pem "$SSL_DIR/" 2>/dev/null || true
    cp /etc/letsencrypt/live/"$DOMAIN"/privkey.pem "$SSL_DIR/" 2>/dev/null || true
    CRON_CMD="0 3 * * * certbot renew --quiet --deploy-hook 'docker restart nutrideby-nginx'"
    (crontab -l 2>/dev/null | grep -v certbot; echo "$CRON_CMD") | crontab -
else
    echo "[*] Sem domínio. Gerando self-signed..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$SSL_DIR/privkey.pem" -out "$SSL_DIR/fullchain.pem" \
        -subj "/CN=localhost/O=NutriDeby/C=BR"
fi
echo "[OK] Certificados em $SSL_DIR:"; ls -la "$SSL_DIR"
