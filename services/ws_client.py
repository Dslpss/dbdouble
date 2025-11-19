"""
Cliente WebSocket para conexão com Play na Bets
Equivalente ao wsClient.js
"""
import asyncio
import websockets
import json
from typing import Callable, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class WSClient:
    def __init__(self, url: str, on_message: Callable):
        self.url = url
        self.on_message = on_message
        self.ws = None
        self.running = True
        self.task = None
    
    async def connect(self):
        """Conectar ao WebSocket"""
        while self.running:
            try:
                logger.info(f"[WS] Conectando a {self.url}")
                async with websockets.connect(self.url) as ws:
                    self.ws = ws
                    
                    # Notificar conexão
                    self.on_message({"type": "status", "connected": True})
                    
                    # Escutar mensagens
                    async for message in ws:
                        if not self.running:
                            break
                        try:
                            if isinstance(message, str):
                                data = json.loads(message)
                            else:
                                data = json.loads(message.decode('utf-8'))
                            self.on_message(data)
                        except json.JSONDecodeError:
                            # Tentar extrair JSON de string
                            try:
                                msg_str = message if isinstance(message, str) else message.decode('utf-8')
                                start = msg_str.find("{")
                                end = msg_str.rfind("}") + 1
                                if start != -1 and end > start:
                                    data = json.loads(msg_str[start:end])
                                    self.on_message(data)
                            except:
                                pass
                        except Exception as e:
                            logger.warning(f"[WS] Erro ao processar mensagem: {e}")
                
            except Exception as e:
                logger.error(f"[WS] Erro na conexão: {e}")
                self.on_message({"type": "status", "connected": False, "error": str(e)})
                if self.running:
                    await asyncio.sleep(2)  # Tentar reconectar após 2 segundos
    
    async def start(self):
        """Iniciar cliente"""
        self.task = asyncio.create_task(self.connect())
    
    async def stop(self):
        """Parar cliente"""
        self.running = False
        if self.ws:
            try:
                await self.ws.close()
            except:
                pass
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

