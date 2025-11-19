#!/bin/bash
echo "========================================"
echo "Reiniciando servidor DBcolor"
echo "========================================"
echo ""
echo "Parando processos na porta 3001..."
# Windows Git Bash
if command -v netstat &> /dev/null; then
    PID=$(netstat -ano | grep :3001 | awk '{print $5}' | head -1)
    if [ ! -z "$PID" ]; then
        echo "Matando processo $PID"
        taskkill //PID $PID //F 2>/dev/null || kill -9 $PID 2>/dev/null
    fi
fi
echo ""
echo "Aguardando 2 segundos..."
sleep 2
echo ""
echo "Iniciando servidor..."
python main.py



