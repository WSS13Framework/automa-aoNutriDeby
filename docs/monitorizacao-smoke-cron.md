# Smoke Dietbox + cron (JWT / 401)

Objetivo: correr de hora em hora (ou 2×/dia) um pedido **mínimo** à API Dietbox e falhar de forma **discriminada** quando o JWT expirar (**HTTP 401**), para e-mail do cron ou webhook.

## Comando

```bash
python -m nutrideby.workers.dietbox_sync --smoke
```

Requer `DIETBOX_BEARER_TOKEN` (e opcionalmente `DIETBOX_API_BASE`) no `.env` — igual aos outros comandos Dietbox.

## Códigos de saída

| Exit | Significado |
|------|-------------|
| `0` | OK — subscription devolveu **200**. |
| `1` | Erro genérico (outro HTTP, rede, SSL). |
| `2` | Configuração — token em falta. |
| `3` | **401** — JWT inválido ou expirado; **renovar token no servidor** (GitHub → pull só actualiza código; o `.env` no servidor é separado). |

## Webhook opcional (401)

No `.env` do servidor:

```bash
NUTRIDEBY_SMOKE_ALERT_WEBHOOK_URL=https://hooks.slack.com/services/...
```

Se estiver definido e o smoke receber **401**, o processo faz um `POST` JSON com pelo menos `text` (compatível com *Slack incoming webhook*), mais campos `source`, `check`, `http_status`. Falhas no webhook são só logadas; o exit mantém-se **3**.

## Exemplo crontab (root ou utilizador com `.env`)

Ajusta caminho e `docker compose` conforme o servidor.

```cron
MAILTO=ops@example.com
# De hora em hora, smoke Dietbox (e-mail se falhar)
15 * * * * cd /opt/automa-aoNutriDeby && docker compose --profile tools run --rm worker python -m nutrideby.workers.dietbox_sync --smoke
```

Ou script wrapper: ver `scripts/smoke-dietbox.example.sh`.

## Alerta só em 401 (exit 3)

```bash
python -m nutrideby.workers.dietbox_sync --smoke || {
  c=$?
  [ "$c" -eq 3 ] && curl -fsS -X POST -H 'Content-Type: application/json' \
    -d '{"text":"Dietbox JWT 401"}' 'https://hooks.slack.com/services/...' || true
  exit "$c"
}
```

## Regra de deploy

Código vem do **GitHub** (`git pull` no servidor). O **JWT** vive no `.env` / segredos do host — não é substituído pelo `git pull`. Quando o smoke falhar com **3**, actualizar `DIETBOX_BEARER_TOKEN` no servidor e reiniciar jobs se necessário.
