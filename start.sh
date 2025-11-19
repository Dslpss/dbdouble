#!/usr/bin/env bash
# Script para facilitar a inicialização no Linux/WSL/Git Bash
set -e

if [ ! -d ".venv" ]; then
    echo "Criando virtualenv..."
    python -m venv .venv
fi

# Ativar venv (tenta bin, depois Scripts)
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f ".venv/Scripts/activate" ]; then
    source .venv/Scripts/activate
fi

# Instalar dependências
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Iniciar o servidor (uvicorn com reload)
python main.py
