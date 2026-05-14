"""
NutriDeby — Credential Vault
Criptografia AES-256-GCM para credenciais de plataformas externas.
Chave lida de ONBOARDING_VAULT_KEY (env var, 32 bytes hex).
"""
from __future__ import annotations

import os
import secrets
from base64 import b64decode, b64encode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_key() -> bytes:
    raw = os.environ.get("ONBOARDING_VAULT_KEY", "")
    if not raw:
        raise RuntimeError("ONBOARDING_VAULT_KEY não definida. Gere com: openssl rand -hex 32")
    key = bytes.fromhex(raw)
    if len(key) != 32:
        raise RuntimeError("ONBOARDING_VAULT_KEY deve ter 32 bytes (64 hex chars)")
    return key


def encrypt(plaintext: str) -> tuple[bytes, bytes]:
    """
    Criptografa plaintext com AES-256-GCM.
    Retorna (ciphertext_bytes, nonce_bytes).
    Nonce é 12 bytes aleatórios — único por operação.
    """
    key = _get_key()
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return ciphertext, nonce


def decrypt(ciphertext: bytes, nonce: bytes) -> str:
    """
    Decriptografa ciphertext com AES-256-GCM.
    Retorna plaintext string.
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode()


def encrypt_b64(plaintext: str) -> tuple[str, str]:
    """Versão base64 para armazenamento em JSON."""
    ct, nonce = encrypt(plaintext)
    return b64encode(ct).decode(), b64encode(nonce).decode()


def decrypt_b64(ciphertext_b64: str, nonce_b64: str) -> str:
    """Versão base64 para leitura de JSON."""
    return decrypt(b64decode(ciphertext_b64), b64decode(nonce_b64))
