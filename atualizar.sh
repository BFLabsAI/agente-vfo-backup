#!/bin/bash
# atualizar.sh — Atualiza VFO (ambas instâncias) do GitHub
# Uso: ./atualizar.sh

set -e  # para se qualquer passo falhar

DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$DIR"

echo ">> Pulling latest from GitHub..."
git pull

echo ">> Restartando vanessa-1 (vfo-agent)..."
systemctl restart vfo-agent

echo ">> Restartando vanessa-2 (vfo-agent-2)..."
systemctl restart vfo-agent-2

echo ">> Status:"
systemctl is-active vfo-agent vfo-agent-2

echo "✓ Atualização concluída."
