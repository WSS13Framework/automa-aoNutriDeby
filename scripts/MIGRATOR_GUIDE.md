# Guia do NutriDeby Migrator (.exe)

Este guia explica como transformar o script `nutrideby_migrator.py` em um executável Windows que a nutricionista pode rodar com um clique.

## 1. Preparação (No seu PC de Dev)

Você precisará do Python instalado no Windows para gerar o executável.

```bash
# Instalar dependências
pip install fdb requests pyinstaller
```

## 2. Configuração

Edite o arquivo `nutrideby_migrator.py` e altere as variáveis no topo:

- `API_URL`: O endereço do seu servidor (ex: `https://api.nutrideby.com.br/api/importar`)
- `API_KEY`: A sua `NUTRIDEBY_API_KEY`

## 3. Gerar o Executável (.exe)

Roda o comando abaixo na pasta do script:

```bash
pyinstaller --onefile --name "NutriDeby_Migrator" --icon=NONE nutrideby_migrator.py
```

- `--onefile`: Gera um único arquivo .exe (fácil de enviar por WhatsApp/E-mail)
- O arquivo final estará na pasta `dist/NutriDeby_Migrator.exe`.

## 4. Como a Nutricionista usa

1. Ela baixa o `NutriDeby_Migrator.exe`.
2. Clica duas vezes para rodar.
3. O script localiza o banco do DietSmart automaticamente.
4. Ela confirma com "s" e os dados são enviados para o seu painel.

---

## Por que isso é "Steve Jobs"?

- **Zero Configuração:** Ela não precisa saber onde o banco está.
- **Zero Instalação:** É um executável portátil.
- **Seguro:** Usa a mesma API que o dashboard usa.
- **Rápido:** Extrai direto do banco local, sem depender da internet lenta do DietSmart Web.
