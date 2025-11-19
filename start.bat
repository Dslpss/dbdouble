@echo off
REM Script para inicializar no Windows (CMD/PowerShell)
IF NOT EXIST ".venv" (
    echo Criando virtualenv...
    python -m venv .venv
)

REM Ativar venv
call .\.venv\Scripts\activate

REM Instalar dependências
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

REM Iniciar servidor
python main.py
