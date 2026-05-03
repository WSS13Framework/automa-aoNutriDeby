"""Segmentação simples de texto para a tabela ``chunks`` (sem embeddings)."""

from __future__ import annotations


def chunk_text(text: str, *, max_chars: int = 1200) -> list[str]:
    """
    Parte texto em blocos até ``max_chars``, preferindo quebras em newline ou espaço.

    Idempotente no sentido de que o mesmo ``text`` produz a mesma lista de segmentos.
    """
    s = (text or "").strip()
    if not s:
        return []
    max_chars = max(200, int(max_chars))
    out: list[str] = []
    n = len(s)
    i = 0
    while i < n:
        end = min(i + max_chars, n)
        if end < n:
            cut = s.rfind("\n", i + 1, end)
            if cut == -1 or cut < i + max_chars // 2:
                cut = s.rfind(" ", i + 1, end)
            if cut > i:
                end = cut + 1
        piece = s[i:end].strip()
        if piece:
            out.append(piece)
        if end <= i:
            i += 1
        else:
            i = end
    return out
