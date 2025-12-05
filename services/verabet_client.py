"""
Cliente de polling para VeraBet Double API
Equivalente ao WSClient mas usando HTTP polling
"""
import asyncio
import aiohttp
import json
import time
from typing import Callable, Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)

VERABET_API_URL = "https://prod-double-o-br1.banana.games/rounds-info"
POLL_INTERVAL = 2  # segundos (reduzido para resultados mais rápidos)


def parse_verabet_result(item: Dict) -> Optional[Dict]:
    """
    Parse resultado da VeraBet
    {id, number, created_at} -> {number, color, round_id, timestamp, source}
    """
    try:
        num = int(item.get("number", -1))
        if not (0 <= num <= 14):
            return None
        
        # Determinar cor
        if num == 0:
            color = "white"
        elif num <= 7:
            color = "red"
        else:
            color = "black"
        
        # Parse timestamp
        created_at = item.get("created_at", "")
        try:
            from datetime import datetime
            dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
            ts = int(dt.timestamp() * 1000)
        except:
            ts = int(time.time() * 1000)
        
        return {
            "number": num,
            "color": color,
            "round_id": str(item.get("id", f"verabet_{ts}")),
            "timestamp": ts,
            "source": "verabet",
            "created_at": created_at,
            "raw": item,
        }
    except Exception as e:
        logger.warning(f"[VeraBet] Erro ao parsear resultado: {e}")
        return None


class VeraBetClient:
    def __init__(self, on_message: Callable, poll_interval: int = POLL_INTERVAL):
        self.on_message = on_message
        self.poll_interval = poll_interval
        self.running = True
        self.task = None
        self.last_round_id: Optional[str] = None
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def fetch_results(self) -> List[Dict]:
        """Buscar resultados da API VeraBet"""
        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://vera.bet.br",
                "Referer": "https://vera.bet.br/",
            }
            
            async with self.session.post(VERABET_API_URL, headers=headers, json={}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", [])
                else:
                    logger.warning(f"[VeraBet] Status HTTP: {resp.status}")
                    return []
        except Exception as e:
            logger.error(f"[VeraBet] Erro ao buscar resultados: {e}")
            return []
    
    async def poll_loop(self):
        """Loop de polling"""
        self.session = aiohttp.ClientSession()
        
        try:
            # Notificar conexão inicial
            self.on_message({"type": "status", "connected": True})
            logger.info("[VeraBet] Cliente iniciado")
            
            while self.running:
                try:
                    results = await self.fetch_results()
                    
                    if results:
                        # Processar apenas o resultado mais recente
                        latest = results[0]
                        current_id = str(latest.get("id"))
                        
                        # Verificar se é um novo resultado
                        if current_id != self.last_round_id:
                            self.last_round_id = current_id
                            parsed = parse_verabet_result(latest)
                            
                            if parsed:
                                logger.info(f"[VeraBet] Novo resultado: #{parsed['number']} ({parsed['color']})")
                                self.on_message(parsed)
                    
                except Exception as e:
                    logger.error(f"[VeraBet] Erro no loop: {e}")
                    self.on_message({"type": "status", "connected": False, "error": str(e)})
                
                # Aguardar próximo poll
                await asyncio.sleep(self.poll_interval)
                
        except asyncio.CancelledError:
            pass
        finally:
            if self.session:
                await self.session.close()
            self.on_message({"type": "status", "connected": False})
            logger.info("[VeraBet] Cliente finalizado")
    
    async def start(self):
        """Iniciar cliente"""
        self.running = True
        self.task = asyncio.create_task(self.poll_loop())
    
    async def stop(self):
        """Parar cliente"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass


async def fetch_initial_history(limit: int = 20) -> List[Dict]:
    """
    Buscar histórico inicial para popular a interface
    Retorna os últimos `limit` resultados já parseados
    """
    try:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://vera.bet.br",
            "Referer": "https://vera.bet.br/",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(VERABET_API_URL, headers=headers, json={}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    raw_results = data.get("data", [])[:limit]
                    
                    parsed = []
                    for item in raw_results:
                        p = parse_verabet_result(item)
                        if p:
                            parsed.append(p)
                    
                    # Reverter para ordem cronológica (mais antigo primeiro)
                    return list(reversed(parsed))
                else:
                    return []
    except Exception as e:
        logger.error(f"[VeraBet] Erro ao buscar histórico: {e}")
        return []
