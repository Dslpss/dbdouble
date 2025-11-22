"""
DBcolor - Servidor principal
Aplicação FastAPI para análise de padrões do Double
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
import asyncio
import json
import time
import os
from dotenv import load_dotenv
load_dotenv()
import traceback
from datetime import datetime
from typing import List, Dict, Any
from services.ws_client import WSClient
from services.parser import parse_double_payload
from services.double import detect_best_double_signal
from services.double import numbers_for_color
from services.adaptive_calibration import update_pattern_stat, online_update_platt
from config import CONFIG
from db import init_db
from routes.auth import router as auth_router, get_current_user
# Import do motor de padrões simples (opcional)
try:
    from services.pattern_signals import SignalEngine
    USE_PATTERN_ENGINE = True
    pattern_engine = SignalEngine()
except Exception:
    USE_PATTERN_ENGINE = False
    pattern_engine = None

app = FastAPI(title="DBcolor API", version="1.0.0")

# Print de confirmação ao carregar o módulo
print("=" * 60)
print("✅ DBcolor API carregada - Versão com interface HTML")
print("=" * 60)
print(f"Configured PLAYNABETS_WS_URL: {os.getenv('PLAYNABETS_WS_URL', CONFIG.WS_URL)}")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include auth routes
try:
    app.include_router(auth_router)
    print("✅ Auth routes registered")
except Exception:
    pass

# Initialize DB
try:
    init_db(app)
    print("✅ MongoDB initialized")
except Exception as e:
    print("⚠️ Could not initialize MongoDB:", e)

# Estado global
results_history: List[Dict] = []
ws_connection: WSClient = None
ws_connected = False
event_clients: List[asyncio.Queue] = []
# Martingale: bets pending (signals still being verified for win/loss)
pending_bets: List[Dict] = []

# Cooldown (server-side)
COOLDOWN_BASIC = 4
COOLDOWN_AFTER_LOSS = 8
STOP_AFTER_3_LOSSES = 12
MIN_COOLDOWN_AFTER_WIN = 3
GLOBAL_WINDOW_ROUNDS = 30
GLOBAL_MAX_ALERTS = 4

cooldown_contador = 0
perdas_consecutivas = 0
modo_stop = False
stop_counter = 0
modo_conservador = False
historico_alertas: List[Dict] = []
round_index = 0
signal_stats = {
    "alta": {"total": 0, "acertos": 0, "taxa": 0.0},
    "media": {"total": 0, "acertos": 0, "taxa": 0.0},
    "baixa": {"total": 0, "acertos": 0, "taxa": 0.0},
    "geral": {"total": 0, "acertos": 0, "taxa": 0.0}
}
sinais_perdidos_por_pausa = 0
compensation_remaining = 0

def decrementar_cooldown():
    global modo_stop, stop_counter, cooldown_contador, perdas_consecutivas
    if modo_stop:
        stop_counter = max(0, stop_counter - 1)
        if stop_counter == 0:
            modo_stop = False
            perdas_consecutivas = 0
            try:
                global compensation_remaining, sinais_perdidos_por_pausa
                compensation_remaining = sinais_perdidos_por_pausa
                sinais_perdidos_por_pausa = 0
            except Exception:
                pass
        return
    if cooldown_contador > 0:
        cooldown_contador = max(0, cooldown_contador - 1)

def ativar_cooldown(tipo: str):
    global cooldown_contador, modo_conservador, modo_stop, stop_counter
    if tipo == "basico":
        cooldown_contador = COOLDOWN_BASIC
    elif tipo == "perda":
        cooldown_contador = COOLDOWN_AFTER_LOSS
        modo_conservador = True
    elif tipo == "stop":
        modo_stop = True
        stop_counter = STOP_AFTER_3_LOSSES
        cooldown_contador = 0

def verificar_cooldown() -> bool:
    return (not modo_stop) and cooldown_contador == 0

def registrar_alerta():
    global historico_alertas
    historico_alertas.append({"ts": int(time.time() * 1000), "round": round_index})
    if len(historico_alertas) > 200:
        historico_alertas = historico_alertas[-200:]

def contar_alertas_na_janela() -> int:
    min_round = max(0, round_index - GLOBAL_WINDOW_ROUNDS + 1)
    return len([a for a in historico_alertas if a.get("round", 0) >= min_round])

def pode_emitir_alerta() -> bool:
    if modo_stop:
        return False
    if cooldown_contador > 0:
        return False
    if contar_alertas_na_janela() >= GLOBAL_MAX_ALERTS:
        return False
    return True

def registrar_resultado(acertou: bool):
    global cooldown_contador, perdas_consecutivas, modo_conservador
    if acertou:
        cooldown_contador = max(MIN_COOLDOWN_AFTER_WIN, cooldown_contador // 2)
        perdas_consecutivas = 0
        modo_conservador = False
    else:
        perdas_consecutivas += 1
        ativar_cooldown("perda")
        if perdas_consecutivas >= 3:
            ativar_cooldown("stop")

def registrar_resultado_sinal(confianca: str, acertou: bool):
    try:
        lbl = confianca if confianca in ("alta", "media", "baixa") else "media"
        signal_stats[lbl]["total"] = signal_stats[lbl].get("total", 0) + 1
        signal_stats["geral"]["total"] = signal_stats["geral"].get("total", 0) + 1
        if acertou:
            signal_stats[lbl]["acertos"] = signal_stats[lbl].get("acertos", 0) + 1
            signal_stats["geral"]["acertos"] = signal_stats["geral"].get("acertos", 0) + 1
        calcular_taxas()
    except Exception:
        pass

def calcular_taxas():
    try:
        for k in ("alta", "media", "baixa", "geral"):
            tot = signal_stats[k].get("total", 0)
            ac = signal_stats[k].get("acertos", 0)
            signal_stats[k]["taxa"] = round((ac / tot) * 100, 2) if tot > 0 else 0.0
    except Exception:
        pass

def obter_estatisticas() -> Dict:
    return signal_stats

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Página principal da interface - requer autenticação"""
    # Verificar se usuário está autenticado
    try:
        await get_current_user(request)
    except Exception:
        # Não autenticado, redirecionar para auth
        return HTMLResponse(content="", status_code=302, headers={"Location": "/auth"})

    # Usuário autenticado, servir HTML
    base_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(base_dir, "index.html")
    
    print(f"🌐 Requisição para / - Tentando servir HTML de: {html_path}")
    
    if os.path.exists(html_path):
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            print("✅ HTML servido com sucesso!")
            return HTMLResponse(content=html_content)
        except Exception as e:
            print(f"❌ Erro ao ler HTML: {e}")
    
    # Fallback: retornar HTML de erro se arquivo não existir
    error_html = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Erro - DBcolor</title></head>
    <body>
        <h1>Erro: Interface HTML não encontrada</h1>
        <p>Caminho verificado: {html_path}</p>
        <p>Acesse <a href="/api">/api</a> para informações da API.</p>
    </body>
    </html>
    """
    return HTMLResponse(content=error_html, status_code=404)

@app.get("/api")
async def api_info():
    """Informações da API em JSON"""
    return {
        "ok": True,
        "service": "DBcolor - Double Analysis",
        "version": "1.0.0",
        "endpoints": {
            "events": {"method": "GET", "path": "/events", "description": "SSE para resultados do Double"},
            "status": {"method": "GET", "path": "/api/status", "description": "Status da conexão"},
        },
        "status": {
            "ws_connected": ws_connected,
            "results_count": len(results_history),
            "timestamp": int(time.time() * 1000),
        }
    }

# Servir arquivos estáticos
base_dir = os.path.dirname(__file__)

@app.get("/styles.css")
async def styles():
    css_path = os.path.join(base_dir, "styles.css")
    if os.path.exists(css_path):
        return FileResponse(css_path, media_type="text/css")
    return {"error": "File not found"}, 404


@app.get("/auth", response_class=HTMLResponse)
async def auth_page():
    html_path = os.path.join(base_dir, "auth.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Auth page not found</h1>", status_code=404)

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    html_path = os.path.join(base_dir, "admin.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Admin page not found</h1>", status_code=404)

@app.get("/app.js")
async def app_js():
    js_path = os.path.join(base_dir, "app.js")
    if os.path.exists(js_path):
        return FileResponse(js_path, media_type="application/javascript")
    return {"error": "File not found"}, 404

@app.get("/api/status")
async def status():
    """Status da conexão WebSocket"""
    return {
        "ok": True,
        "wsConnected": ws_connected,
        "hasToken": False,
        "timestamp": int(time.time() * 1000)
    }


@app.get("/api/results")
async def api_get_results(limit: int = 20):
    """Retorna os últimos resultados processados (úteis para troubleshooting)."""
    return {
        "ok": True,
        "wsConnected": ws_connected,
        "results_count": len(results_history),
        "results": results_history[:limit],
    }

@app.post("/api/connect")
async def connect():
    """Conectar ao WebSocket"""
    global ws_connection, ws_connected
    try:
        if ws_connection is None:
            ws_connection = WSClient(CONFIG.WS_URL, on_message)
            await ws_connection.start()
        return {"ok": True, "message": "Conectado"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/events")
async def events(request: Request):
    """Server-Sent Events para resultados em tempo real"""
    async def event_generator():
        global ws_connected, ws_connection
        
        # Criar fila para este cliente
        queue = asyncio.Queue()
        event_clients.append(queue)
        
        try:
            # Enviar status inicial
            yield f"event: status\ndata: {json.dumps({'type': 'status', 'connected': ws_connected, 'ts': int(time.time() * 1000)})}\n\n"
            
            # Conectar WebSocket se não estiver conectado
            if ws_connection is None:
                ws_connection = WSClient(CONFIG.WS_URL, on_message)
                await ws_connection.start()
            
            # Heartbeat
            last_heartbeat = time.time()
            while True:
                if await request.is_disconnected():
                    break
                
                # Verificar se há mensagens na fila
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield message
                except asyncio.TimeoutError:
                    pass
                
                # Enviar heartbeat a cada 10 segundos
                if time.time() - last_heartbeat >= 10:
                    yield f"event: ping\ndata: {json.dumps({'type': 'ping', 'ts': int(time.time() * 1000)})}\n\n"
                    last_heartbeat = time.time()
                
                await asyncio.sleep(0.1)
        finally:
            # Remover cliente da lista
            if queue in event_clients:
                event_clients.remove(queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )


@app.on_event("startup")
async def startup_ws_client():
    """Tentativa de iniciar a conexão WebSocket automaticamente na inicialização do app.
    Isso faz o backend começar a receber resultados mesmo sem cliente SSE conectado.
    """
    global ws_connection
    try:
        if ws_connection is None:
            ws_connection = WSClient(CONFIG.WS_URL, on_message)
            await ws_connection.start()
            print(f"[startup] WSClient iniciado para {CONFIG.WS_URL}")
    except Exception as e:
        print(f"[startup] Falha ao iniciar WSClient: {e}")

@app.on_event("shutdown")
async def shutdown_ws_client():
    global ws_connection
    try:
        if ws_connection is not None:
            await ws_connection.stop()
            print("[shutdown] WSClient finalizado")
    except Exception as e:
        print(f"[shutdown] Erro ao finalizar WSClient: {e}")

def on_message(data: Dict):
    """Callback para mensagens do WebSocket"""
    global results_history, ws_connected
    
    if data.get("type") == "status":
        ws_connected = data.get("connected", False)
        # Notificar clientes SSE
        message = f"event: status\ndata: {json.dumps(data)}\n\n"
        for queue in event_clients:
            try:
                queue.put_nowait(message)
            except:
                pass
        return
    
    # Processar resultado do Double
    parsed = parse_double_payload(data)
    if parsed:
        global round_index
        round_index = round_index + 1
        decrementar_cooldown()
        # Evitar duplicatas
        if results_history:
            last = results_history[-1]
            if (last.get("round_id") == parsed.get("round_id") or
                (last.get("number") == parsed.get("number") and
                 abs((parsed.get("timestamp", 0) - last.get("timestamp", 0))) < 2000)):
                return
        
        results_history.append(parsed)
        # Manter apenas últimos 100 resultados
        if len(results_history) > 100:
            results_history = results_history[-100:]
        
        # Notificar clientes SSE com resultado
        result_payload = {"type": "double_result", "data": parsed}
        message = f"event: double_result\ndata: {json.dumps(result_payload)}\n\n"
        for queue in event_clients:
            try:
                queue.put_nowait(message)
            except:
                pass
        # Se o martingale estiver ativado, avaliar pendentes contra o resultado atual
        try:
            if CONFIG.MARTINGALE_ENABLED and pending_bets:
                # Curr result color
                res_color = parsed.get('color')
                now_ts = int(time.time() * 1000)
                remove_ids = []
                for pb in list(pending_bets):
                    # Verificar se perdeu ou ganhou
                    attempts_left = pb.get('attemptsLeft', CONFIG.MARTINGALE_MAX_ATTEMPTS)
                    target_color = pb.get('color')
                    pk = pb.get('patternKey')
                    raw_score = pb.get('chance', 0)
                    
                    # Evitar avaliar um pending bet usando a MESMA rodada que o criou
                    # Usa round_index para evitar problemas de relógio/timestamp
                    created_round = pb.get('createdRound')
                    if created_round is not None and created_round == round_index:
                        print(f"[MARTINGALE] Pulando bet {pb.get('id')} — criada na mesma rodada {created_round}")
                        continue

                    print(f"[MARTINGALE] Verificando bet {pb.get('id')} | Alvo: {target_color} | Saiu: {res_color} | Tentativas rest: {attempts_left}")
                    
                    # Verificar WIN: cor alvo OU white (se protect_white estiver ativo)
                    protect_white = pb.get('protect_white', False)
                    is_win = (res_color == target_color) or (protect_white and res_color == 'white')
                    
                    if is_win:
                        # Ganhou
                        print(f"[MARTINGALE] WIN detectado para {pb.get('id')} | Cor alvo: {target_color} | Saiu: {res_color} | Protect white: {protect_white}")
                        pb['attemptsUsed'] = pb.get('attemptsUsed', 0) + 1
                        pb['resolved'] = True
                        pb['result'] = 'win'
                        pb['resolvedAt'] = now_ts
                        update_pattern_stat(pk, True)
                        try:
                            online_update_platt(raw_score, 1)
                        except Exception:
                            pass
                        registrar_resultado(True)
                        try:
                            registrar_resultado_sinal(pb.get('confLabel', 'media'), True)
                        except Exception:
                            pass
                        # Enviar SSE informando o resultado
                        bet_payload = {"type": "bet_result", "data": pb}
                        bet_message = f"event: bet_result\ndata: {json.dumps(bet_payload)}\n\n"
                        for queue in event_clients:
                            try:
                                queue.put_nowait(bet_message)
                            except:
                                pass
                        remove_ids.append(pb.get('id'))
                    else:
                        # decrement attempts
                        pb['attemptsLeft'] = attempts_left - 1
                        pb['attemptsUsed'] = pb.get('attemptsUsed', 0) + 1
                        if pb['attemptsLeft'] <= 0:
                            # Loss
                            print(f"[MARTINGALE] LOSS detectado para {pb.get('id')}")
                            pb['resolved'] = True
                            pb['result'] = 'loss'
                            pb['resolvedAt'] = now_ts
                            update_pattern_stat(pk, False)
                            try:
                                online_update_platt(raw_score, 0)
                            except Exception:
                                pass
                            registrar_resultado(False)
                            try:
                                registrar_resultado_sinal(pb.get('confLabel', 'media'), False)
                            except Exception:
                                pass
                            bet_payload = {"type": "bet_result", "data": pb}
                            bet_message = f"event: bet_result\ndata: {json.dumps(bet_payload)}\n\n"
                            for queue in event_clients:
                                try:
                                    queue.put_nowait(bet_message)
                                except:
                                    pass
                            remove_ids.append(pb.get('id'))
                # Limpar pendentes resolvidos
                if remove_ids:
                    pending_bets[:] = [p for p in pending_bets if p.get('id') not in remove_ids]
        except Exception:
            print("❌ Erro ao processar martingale:")
            traceback.print_exc()
        
        # Detectar sinal após adicionar resultado
        if len(results_history) >= 5:
            try:
                # Se bloqueio estiver ativado e existirem apostas pendentes, não detectar novos sinais
                if CONFIG.BLOCK_SIGNALS_WHILE_PENDING and pending_bets:
                    # Debug: informar que sinal foi suprimido por pendente
                    print(f"[DBG] Sinal suprimido: existem {len(pending_bets)} pendentes e BLOCK_SIGNALS_WHILE_PENDING=True")
                    signal = None
                else:
                    signal = None
                    # Opção: usar SignalEngine simples (implementa os 8 padrões)
                    if getattr(CONFIG, 'USE_PATTERN_SIGNALS', False) and USE_PATTERN_ENGINE:
                        # Mapear histórico para formato curto ['V','P','B']
                        short_hist = []
                        for r in results_history:
                            c = r.get('color')
                            if c == 'red':
                                short_hist.append('V')
                            elif c == 'black':
                                short_hist.append('P')
                            else:
                                short_hist.append('B')
                        pe = pattern_engine.avaliar_historico(short_hist, rodada_atual=len(short_hist))
                        if pe.get('signal'):
                            # Mapear para formato de sinal compatível
                            pid = pe.get('pattern_id')
                            sugg = pe.get('suggestion')
                            conf_label = pe.get('confidence')
                            # converter sugestão para cores do sistema
                            color_map = {'V': 'red', 'P': 'black', 'B': 'white'}
                            suggested_color = color_map.get(sugg, None)
                            # chance estimada simplificada baseada no label de confiança
                            chance_map = {'alto': 85, 'medio-alto': 75, 'medio': 65, 'baixo-medio': 55, 'baixo': 30}
                            chance_pct = chance_map.get(conf_label, 50)
                            targets = numbers_for_color(suggested_color) if suggested_color else []
                            signal = {
                                'id': f'ps_{int(time.time()*1000)}',
                                'type': 'MEDIUM_SIGNAL' if conf_label in ('medio','medio-alto') else ('STRONG_SIGNAL' if conf_label in ('alto','medio-alto') else 'WEAK_SIGNAL'),
                                'color': '#90ee90',
                                'description': f'PatternEngine P{pid} detected',
                                'patternKey': f'P{pid}',
                                'confidence': 8.5 if conf_label == 'alto' else (7.5 if conf_label in ('medio','medio-alto') else 6.0),
                                'suggestedBet': {
                                    'type': 'color',
                                    'color': suggested_color,
                                    'numbers': targets,
                                    'coverage': f"{len(targets)} números",
                                    'expectedRoi': 'Simulado',
                                    'protect_white': True
                                },
                                'targets': targets,
                                'reasons': [f'PatternEngine: P{pid}'],
                                'validFor': 3,
                                'timestamp': int(time.time() * 1000),
                                'chance': chance_pct,
                                'afterNumber': None,
                                'afterColor': None,
                                'suggestedText': f"Sinal P{pid}: apostar {suggested_color}" if suggested_color else 'Sinal'
                            }
                    # Se não foi gerado sinal pelo pattern engine, manter o detector original
                    if not signal:
                        signal = detect_best_double_signal(results_history)
                if signal:
                    if not pode_emitir_alerta():
                        if modo_stop:
                            try:
                                global sinais_perdidos_por_pausa
                                sinais_perdidos_por_pausa += 1
                            except Exception:
                                pass
                            allow_compensation = False
                            try:
                                allow_compensation = compensation_remaining > 0 and signal.get('chance', 0) >= 65
                            except Exception:
                                allow_compensation = False
                            if not allow_compensation:
                                print(f"[COOLDOWN] Stop temporário ativo ({stop_counter} rodadas restantes)")
                                return
                            else:
                                try:
                                    compensation_remaining = max(0, compensation_remaining - 1)
                                except Exception:
                                    pass
                        elif cooldown_contador > 0:
                            print(f"[COOLDOWN] Padrão detectado mas cooldown ativo ({cooldown_contador} rodadas restantes)")
                            return
                        else:
                            print(f"[COOLDOWN] Limite global atingido ({GLOBAL_MAX_ALERTS}/{GLOBAL_WINDOW_ROUNDS}) — alerta suprimido")
                            return
                    # Antes de enviar a notificação, criar pendente para martingale (se ativado)
                    pb_id = None
                    try:
                        if CONFIG.MARTINGALE_ENABLED:
                            pb_id = f"pb_{int(time.time() * 1000)}"
                            signal['id'] = pb_id
                    except Exception:
                        pb_id = None
                    # Notificar clientes SSE com sinal
                    try:
                        signal['rodada_numero'] = round_index
                    except Exception:
                        pass
                    signal_payload = {"type": "signal", "data": signal}
                    signal_message = f"event: signal\ndata: {json.dumps(signal_payload)}\n\n"
                    for queue in event_clients:
                        try:
                            queue.put_nowait(signal_message)
                        except:
                            pass
                    registrar_alerta()
                    ativar_cooldown("basico")
                    # Se martingale ativado, anexar pendente
                    try:
                        if CONFIG.MARTINGALE_ENABLED:
                            pb = {
                                'id': pb_id,
                                'patternKey': signal.get('patternKey'),
                                'color': signal.get('suggestedBet', {}).get('color'),
                                'numbers': signal.get('suggestedBet', {}).get('numbers', []),
                                'chance': signal.get('chance', 0),
                                'createdAt': int(time.time() * 1000),
                                'createdRound': round_index,
                                'attemptsLeft': (signal.get('gales_permitidos', 0) + 1) if signal.get('gales_permitidos') is not None else CONFIG.MARTINGALE_MAX_ATTEMPTS,
                                'attemptsUsed': 0,
                                'protect_white': signal.get('suggestedBet', {}).get('protect_white', False),
                                'confLabel': signal.get('confLabel', 'media'),
                            }
                            pending_bets.append(pb)
                    except Exception:
                        pass
                    # Adicionar martingale/pending bet ao monitorar futuro
                    # (Bloco duplicado removido)
            except Exception as e:
                # Ignorar erros na detecção de sinais
                pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)

