# NutriDeby — Sistema de Extração e Centralização de Dados

## Visão Geral

Pipeline modular para extrair dados de plataformas de nutrição brasileiras e centralizar no PostgreSQL + pgvector do NutriDeby.

```
[Plataforma] → [Extrator] → [Normalizador] → [JSON unificado] → POST /api/importar → [PostgreSQL + pgvector]
```

## Estrutura

```
scripts/
├── extractors/
│   ├── normalizer.py              # Normalizador unificado (usado por todos os extratores)
│   ├── dietbox_extractor.py       # Dietbox — API REST autenticada
│   ├── dietsmart_extractor.py     # DietSmart — banco Firebird local
│   ├── nutrium_extractor.py       # Nutrium — PDF + pdfplumber
│   ├── nutricloud_extractor.py    # NutriCloud — CSV nativo
│   └── generic_csv_extractor.py  # Genérico — qualquer CSV/XLSX
├── matriz_plataformas.json        # Matriz estratégica de todas as plataformas
└── README.md                      # Este arquivo
```

## Plataformas Suportadas

| Plataforma | Rota | Complexidade | Status |
|------------|------|-------------|--------|
| **Dietbox** | API REST (Bearer token) | Baixa | ATIVO |
| **DietSmart** | Banco Firebird local | Média | VIÁVEL |
| **Nutrium** | PDF + pdfplumber | Média | VIÁVEL |
| **NutriCloud** | CSV nativo | Baixa | VIÁVEL |
| **Qualquer CSV/XLSX** | Genérico (auto-detect) | Baixa | VIÁVEL |

## Uso

### 1. Dietbox (API REST)

```bash
export DIETBOX_EMAIL="nutri@clinica.com"
export DIETBOX_PASSWORD="senha_segura"

python3 extractors/dietbox_extractor.py \
  --output pacientes_dietbox.json \
  --limit 0   # 0 = todos os pacientes
```

### 2. DietSmart (banco Firebird local)

```bash
# Instalar driver Firebird
pip install firebird-driver

# Extrair do banco local
python3 extractors/dietsmart_extractor.py \
  --db "C:/DietSmart/dados/DIETSMART.FDB" \
  --output pacientes_dietsmart.json

# Fallback: CSV exportado pelo DietSmart
python3 extractors/dietsmart_extractor.py \
  --csv clientes_exportados.csv \
  --output pacientes_dietsmart.json
```

### 3. Nutrium (PDFs)

```bash
pip install pdfplumber

python3 extractors/nutrium_extractor.py \
  --pdf-dir /caminho/para/pdfs/ \
  --output pacientes_nutrium.json
```

### 4. NutriCloud (CSV)

```bash
python3 extractors/nutricloud_extractor.py \
  --csv pacientes_nutricloud.csv \
  --output pacientes_nutricloud.json
```

### 5. Genérico (qualquer CSV/XLSX)

```bash
pip install openpyxl

python3 extractors/generic_csv_extractor.py \
  --file dados.xlsx \
  --platform dietsystem \
  --output pacientes_dietsystem.json
```

## Importar para NutriDeby

Após gerar o JSON, envie para a API:

```bash
curl -X POST http://localhost:8081/api/importar \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $NUTRIDEBY_API_KEY" \
  -d @pacientes_dietbox.json
```

Ou use o painel web: **Dashboard → Importar Pacientes** (drag-and-drop).

## Schema Unificado de Saída

```json
{
  "data_exportacao": "2026-05-14T00:00:00Z",
  "source_platform": "dietbox",
  "total": 430,
  "pacientes": [
    {
      "external_id": "3722078",
      "nome": "Nome do Paciente",
      "dados_cadastrais": {
        "email": "...", "telefone": "...", "data_nascimento": "1990-01-15",
        "sexo": "F", "objetivo": "Emagrecimento"
      },
      "prontuario": {
        "texto": "...", "medicamentos": [], "condicoes": [], "alergias": []
      },
      "metas_nutricionais": {
        "calorias": 1800, "proteinas_g": 120, "carboidratos_g": 200,
        "gorduras_g": 60, "fibras_g": 25, "agua_ml": 2000
      },
      "medidas_antropometricas": {
        "peso_kg": 75.5, "altura_m": 1.65, "imc": 27.7,
        "percentual_gordura": 28.5, "data_medicao": "2026-05-01"
      },
      "plano_alimentar": {},
      "exames": [],
      "historico_evolucao": []
    }
  ]
}
```

## Segurança

- Nunca commitar credenciais. Usar variáveis de ambiente ou `.env` (não versionado).
- O banco Firebird do DietSmart é acessado localmente — sem transmissão de dados.
- A API Dietbox usa HTTPS com Bearer token de sessão.
- Todos os dados são do próprio nutricionista — sem violação de LGPD.

## Dependências

```bash
pip install requests pdfplumber firebird-driver openpyxl
```
