#!/usr/bin/env bash
# Cria (se preciso) um ambiente virtual, instala o PySide6 e abre o launcher.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo ">> Criando ambiente virtual em .venv (so na primeira vez)..."
  python -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
python -m linuxdroid
