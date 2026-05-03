#!/usr/bin/env python3
"""
Remove espaços e tabs no **início** e **fim** de cada linha do ficheiro `.env`.

Corrige erros como `` DIETBOX_BEARER_TOKEN=...`` (espaço antes do nome da variável).

Uso:
  python3 scripts/strip_env_whitespace.py
  python3 scripts/strip_env_whitespace.py /opt/automa-aoNutriDeby/.env
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _strip_line(line: str) -> str:
    if line.endswith("\r\n"):
        body, ending = line[:-2], "\r\n"
    elif line.endswith("\n"):
        body, ending = line[:-1], "\n"
    elif line.endswith("\r"):
        body, ending = line[:-1], "\r"
    else:
        body, ending = line, ""
    return body.strip(" \t") + ending


def main() -> int:
    p = argparse.ArgumentParser(description="Strip leading/trailing spaces/tabs on each .env line")
    p.add_argument(
        "env_file",
        type=Path,
        nargs="?",
        default=Path(".env"),
        help="Caminho do .env (default: ./.env)",
    )
    p.add_argument(
        "--no-backup",
        action="store_true",
        help="Não criar cópia .env.bak antes de gravar",
    )
    args = p.parse_args()
    path: Path = args.env_file
    if not path.is_file():
        print(f"Erro: ficheiro não encontrado: {path.resolve()}", file=sys.stderr)
        return 1
    raw = path.read_text(encoding="utf-8")
    new_content = "".join(_strip_line(line) for line in raw.splitlines(keepends=True))
    if new_content == raw:
        print(f"Nada a alterar: {path.resolve()}")
        return 0
    if not args.no_backup:
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
        print(f"Backup: {bak.resolve()}")
    path.write_text(new_content, encoding="utf-8")
    print(f"Actualizado: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
