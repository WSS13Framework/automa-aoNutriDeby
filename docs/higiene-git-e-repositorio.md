# Higiene Git e repositório

Complementa [operacao-git-docker-servidor.md](./operacao-git-docker-servidor.md).

## Regra de ouro

**Nunca** `git add -A` sem olhar para `git status` antes. Preferir `git add` **ficheiro a ficheiro** ou pastas explícitas (`src/`, `docs/`, …).

## O que **não** deve ir para o GitHub

| Tipo | Exemplos |
|------|-----------|
| Segredos | `.env`, tokens, passwords, chaves API |
| Dados pessoais / clínicos | `*.csv` com pacientes reais, `*.db`, exports |
| Estado local | `.openclaw/`, caches, `docker-compose.override.yml` |
| Binários grandes | bases SQLite, dumps, ficheiros `*.save` |

O **`.gitignore`** na raiz do repo já cobre vários destes padrões.

## Depois de um commit “gordo” no servidor (correcção)

Se já entraram ficheiros que não deviam estar no histórico:

1. **Pull** em todas as máquinas.
2. **Parar de rastrear** (mantém ficheiro no disco, tira do Git):

   ```bash
   git rm -r --cached .openclaw 2>/dev/null || true
   git rm --cached docker-compose.override.yml 2>/dev/null || true
   git rm --cached data/pacientes.db data/*.save 2>/dev/null || true
   # ajustar caminhos conforme o que 'git ls-files' mostrar
   ```

3. Garantir que o **`.gitignore`** já ignora esses caminhos.
4. `git commit -m "chore: remove artefactos locais do controlo de versão"`
5. `git push`

**Segredos expostos:** rodar credenciais (novo token, nova password) mesmo após remover do último commit — o GitHub pode manter histórico público.

## Checklist rápido antes de `push`

- [ ] `git status` — só o que faz sentido versionar
- [ ] `git diff` — rever alterações
- [ ] Nenhum `.env` / `.db` / override local
- [ ] Mensagem de commit descritiva (`feat:`, `fix:`, `docs:`, `chore:`)

---

**Última actualização:** 2026-05-02
