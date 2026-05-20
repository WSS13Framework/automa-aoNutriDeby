# Estado Atual do Projeto — NutriDeby
**Atualizado:** 2026-05-20

## Infraestrutura
- VPS: DigitalOcean (Maria-Helena-v2) — 143.198.95.64
- API: FastAPI porta 84
- Dashboard: Next.js porta 3000
- Banco: PostgreSQL + pgvector
- Workers: Kiwify, Hermes

## Credenciais (usar .env — nunca hardcode)
- DEEPSEEK_API_KEY → .env
- TWILIO_ACCOUNT_SID → .env
- TWILIO_AUTH_TOKEN → .env (ATENÇÃO: pode ser regenerado no console Twilio)
- DIETBOX_BEARER_TOKEN → .env (expira — renovar via DevTools DietBox)

## Estado do Banco
- 430 pacientes DietBox sincronizados
- 395 inativos (alvo da campanha)
- 80 com prontuários
- 10 itens fitoterapia/ortomolecular

## Agentes
- hermes_agent.py → disparo WhatsApp via Twilio + DeepSeek
- process_kiwify_inbox.py → ativação automática de pacientes
- worker_trial_whatsapp.py → campanha em lote

## Regras Imutáveis
- NUNCA hardcode de credenciais no código
- NUNCA injetar dados falsos no banco
- SEMPRE usar env vars para secrets
- GitHub push protection ativo

## Twilio Sandbox
- Número: +14155238886
- Join: join silk-track

## Próximos passos
1. Renovar TWILIO_AUTH_TOKEN no console Twilio
2. Disparar Hermes para 395 pacientes inativos
3. Dashboard mostrar pacientes corretamente
4. Deploy automático via GitHub Actions
