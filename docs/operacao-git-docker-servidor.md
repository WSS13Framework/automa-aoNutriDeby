# Operação: Git + servidor + Docker (registo permanente)

Este documento explica **porque** o servidor às vezes corre código “velho” e como alinhar com o repositório. Serve para toda a vida do projecto e para evitar repetir a mesma confusão.

## 1. Duas fontes de verdade para o código Python

### A) Imagem Docker (`docker compose build`)

- O **Dockerfile** copia ficheiros (`COPY src ./src`) **no momento do build**.
- Se o `docker-compose.yml` do **servidor** **não** montar o projecto em `/app`, o container usa **só** o que está dentro da imagem → cada mudança de código exige **`docker compose build`** (de preferência após `git pull`).

### B) Volume `volumes: - .:/app` (muito comum em dev)

- O directório do host (ex.: `/opt/automa-aoNutriDeby`) **substitui** `/app` dentro do container.
- O Python executa o que está **no disco do servidor**, **não** o que foi “cozinhado” na última imagem (excepto dependências `pip` instaladas na imagem).
- Consequência: **`docker compose build` sozinho não actualiza o `dietbox_sync.py`** se o ficheiro no disco continuar antigo.
- Consequência: **`git pull` no servidor** é o passo crítico para trazer código novo **para o disco**.

## 2. Ficheiros *untracked* e `git pull`

- Ficheiros listados em **`Untracked files`** no `git status` **não** pertencem ao histórico remoto.
- `git pull` **não** substitui nem funde automaticamente esses ficheiros por versões do `origin`.
- Se no remoto **passa a existir** um ficheiro com o **mesmo caminho** que no servidor está *untracked*, o `git pull` pode **recusar** ou exigir que movas/apagues o local primeiro.

**Procedimento seguro no servidor** (antes de `git pull`):

1. `git status`
2. Backup: `mkdir -p ~/backup-nutrideby-DATA && cp -a caminhos/importantes ~/backup-nutrideby-DATA/`
3. Para ficheiros *untracked* que devem passar a vir do Git: **`rm`** ou **`mv`** para fora do repo, depois `git pull`.
4. Para alterações *modified* que queres guardar: `git stash` ou commit numa branch.

## 3. Fluxo recomendado (equipa com GitHub)

| Passo | Onde | Acção |
|-------|------|--------|
| 1 | Máquina de desenvolvimento | `git add`, `git commit`, `git push origin main` (ou branch acordada). |
| 2 | Servidor `/opt/automa-aoNutriDeby` | `git pull` (resolver conflitos se existirem). |
| 3 | Servidor | Verificar código: `grep -n sync-list src/nutrideby/workers/dietbox_sync.py` (exemplo de “flag” de versão). |
| 4 | Servidor | Se **há** volume `.:/app` → **não** é obrigatório rebuild só por `.py`. Se **não** há volume → `docker compose build --no-cache worker`. |
| 5 | Servidor | Correr o worker: `docker compose --profile tools run --rm worker python -m ...` |

**`python` vs `python3` no servidor:** no *host* Ubuntu minimal (sem `python-is-python3`), o comando `python` pode não existir — usa **`python3 -m ...`** com `PYTHONPATH` / venv correctos, ou (recomendado) **sempre** o Docker na linha 5, onde o container expõe `python`.

## 4. Variáveis de ambiente (Dietbox, Postgres)

- Segredos no **`.env`** no servidor; **nunca** commit.
- O serviço `worker` deve ver o `.env`: **`env_file: .env`** no `docker-compose.yml` ou ficheiro **`docker-compose.override.yml`** (ignorado pelo Git — criar no servidor a partir de `docker-compose.override.yml.example`).

## 5. Erro típico: `unrecognized arguments: --sync-list`

**Significado:** o `argparse` do `dietbox_sync.py` em execução **não** define `--sync-list` → ficheiro no disco (ou imagem) **ainda é versão antiga**.

**Checklist de diagnóstico:**

1. `grep -n sync-list src/nutrideby/workers/dietbox_sync.py` — se **não** imprimir nada, o disco **não** tem a versão nova.
2. `git status` — ver *untracked* / *modified* que impedem alinhar com `origin`.
3. Garantir **push** a partir do dev para `origin` com os ficheiros correctos.
4. No servidor: `git pull` após limpar *untracked* em conflito.
5. Confirmar de novo o `grep`.

## 6. SQL na shell

- Comandos `SELECT ...` são para **`psql`**, não para `bash` directo.

Exemplo:

```bash
docker compose exec postgres psql -U nutrideby -d nutrideby -c "SELECT source_system, count(*) FROM patients GROUP BY 1;"
```

(Ajustar utilizador e base conforme o teu `.env`.)

## 7. Resolução de conflitos Git

- `git stash` antes do pull para guardar alterações locais; depois `git stash pop` e resolver marcadores de conflito.
- Ou: commit local numa branch, `git pull --rebase origin main`, resolver, merge para `main` conforme fluxo da equipa.

---

**Última actualização:** 2026-05-02 — inclui lições do deploy em `ubuntu-s--Maria-Helena-v2` e erro `--sync-list` por código não alinhado com o remoto / *untracked*.
