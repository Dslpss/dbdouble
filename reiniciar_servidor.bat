@echo off
echo ========================================
echo Reiniciando servidor DBcolor
echo ========================================
echo.
echo Parando processos na porta 3001...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3001') do (
    echo Matando processo %%a
    taskkill /PID %%a /F >nul 2>&1
)
echo.
echo Aguardando 2 segundos...
timeout /t 2 /nobreak >nul
echo.
echo Iniciando servidor...
python main.py
pause



