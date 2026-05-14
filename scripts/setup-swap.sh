#!/usr/bin/env bash
set -euo pipefail
SWAP_FILE="/swapfile"; SWAP_SIZE="2G"
echo "[*] Verificando swap existente..."
if swapon --show | grep -q "$SWAP_FILE"; then
    echo "[OK] Swap já ativo."; swapon --show; exit 0
fi
echo "[*] Criando swapfile de $SWAP_SIZE..."
fallocate -l "$SWAP_SIZE" "$SWAP_FILE"
chmod 600 "$SWAP_FILE"; mkswap "$SWAP_FILE"; swapon "$SWAP_FILE"
grep -q "$SWAP_FILE" /etc/fstab || echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
sysctl vm.swappiness=10
grep -q "vm.swappiness" /etc/sysctl.conf || echo "vm.swappiness=10" >> /etc/sysctl.conf
echo "[OK] Swap configurado:"; swapon --show; free -h
