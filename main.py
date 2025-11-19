"""
DBcolor - Projeto Python
Ponto de entrada principal da aplicação
"""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "3001"))
    reload_flag = os.getenv("DEV", "false").lower() in ("1", "true", "yes")
    print("🚀 Iniciando DBcolor Server...")
    print(f"📡 Servidor rodando em http://0.0.0.0:{port}")
    print(f"📊 Endpoint SSE: http://0.0.0.0:{port}/events")
    print(f"🔌 API info: http://0.0.0.0:{port}/")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=reload_flag)

