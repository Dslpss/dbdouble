"""
DBcolor - Servidor principal
Aplicação FastAPI para análise de padrões do Double
"""
from fastapi import FastAPI, Request, Depends
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
import db as db_module
from routes.auth import router as auth_router, get_current_user, get_admin_user
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
sinais_perdidos_por_pausa = 0
compensation_remaining = 0

# Cooldown (server-side)
COOLDOWN_BASIC = 4
COOLDOWN_AFTER_LOSS = 8
# Anti-tilt: pausa após perdas fortes consecutivas
ANTI_TILT_LOSS_STREAK = 2
STOP_DURATION_ROUNDS = 12
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
sinais_emitidos_hoje = 0
meta_sinais_dia = 100
last_win_ts = None
last_loss_ts = None
# Rastreamento de sequências de wins entre losses
win_streak_history = []  # Lista de sequências de wins entre losses
current_win_streak = 0
max_win_streak = 0
signal_outcome_history = []  # Lista de outcomes {'outcome': 'win'|'loss', 'ts': timestamp}

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
        stop_counter = STOP_DURATION_ROUNDS
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
        if perdas_consecutivas >= ANTI_TILT_LOSS_STREAK:
            ativar_cooldown("stop")

def registrar_resultado_sinal(confianca: str, acertou: bool):
    global current_win_streak, max_win_streak, win_streak_history, signal_outcome_history
    try:
        lbl = confianca if confianca in ("alta", "media", "baixa") else "media"
        signal_stats[lbl]["total"] = signal_stats[lbl].get("total", 0) + 1
        signal_stats["geral"]["total"] = signal_stats["geral"].get("total", 0) + 1
        if acertou:
            signal_stats[lbl]["acertos"] = signal_stats[lbl].get("acertos", 0) + 1
            signal_stats["geral"]["acertos"] = signal_stats["geral"].get("acertos", 0) + 1
            # Rastrear sequências de wins
            current_win_streak += 1
            if current_win_streak > max_win_streak:
                max_win_streak = current_win_streak
        else:
            # Quando perde, salvar a sequência atual (se houver) e resetar
            if current_win_streak > 0:
                win_streak_history.append(current_win_streak)
                # Manter apenas últimas 100 sequências
                if len(win_streak_history) > 100:
                    win_streak_history = win_streak_history[-100:]
            current_win_streak = 0
        
        # Adicionar ao histórico de outcomes
        signal_outcome_history.append({
            'outcome': 'win' if acertou else 'loss',
            'ts': int(time.time() * 1000)
        })
        # Manter apenas últimos 100 outcomes
        if len(signal_outcome_history) > 100:
            signal_outcome_history = signal_outcome_history[-100:]
        
        calcular_taxas()
        
        # Salvar no banco de dados de forma assíncrona
        try:
            asyncio.create_task(save_stats_to_db())
        except Exception:
            pass
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

async def save_stats_to_db():
    """Salva estatísticas no MongoDB para persistência"""
    try:
        if db_module.db is None:
            return
        
        stats_doc = {
            "_id": "global_stats",
            "signal_stats": signal_stats,
            "last_win_ts": last_win_ts,
            "last_loss_ts": last_loss_ts,
            "current_win_streak": current_win_streak,
            "max_win_streak": max_win_streak,
            "win_streak_history": win_streak_history[-100:],  # últimas 100
            "signal_outcome_history": signal_outcome_history[-100:],  # últimas 100
            "results_history": results_history[-50:],  # Persistir últimos 50 resultados
            "updated_at": int(time.time() * 1000)
        }
        
        await db_module.db.stats.update_one(
            {"_id": "global_stats"},
            {"$set": stats_doc},
            upsert=True
        )
    except Exception as e:
        print(f"Erro ao salvar stats no DB: {e}")

async def save_signal_to_history(signal_data: Dict, result: str, attempts_used: int, platform: str = "playnabet"):
    """
    Salva um sinal no histórico para análise estatística detalhada.
    Usado para gerar gráficos de performance por hora, dia, padrão, etc.
    """
    try:
        if db_module.db is None:
            return
        
        now = int(time.time() * 1000)
        created_at = signal_data.get('createdAt', now)
        
        # Extrair hora e dia da semana usando fuso horário de Brasília
        from datetime import datetime, timezone, timedelta
        try:
            from zoneinfo import ZoneInfo
            brazil_tz = ZoneInfo("America/Sao_Paulo")
        except Exception:
            brazil_tz = timezone(timedelta(hours=-3))
        
        # Converter timestamp para datetime com fuso de Brasília
        dt_utc = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)
        dt_brazil = dt_utc.astimezone(brazil_tz)
        
        history_doc = {
            "id": signal_data.get('id', f"sig_{now}"),
            "platform": platform,
            "patternKey": signal_data.get('patternKey', 'unknown'),
            "color": signal_data.get('color'),
            "chance": signal_data.get('chance', 0),
            "createdAt": created_at,
            "resolvedAt": now,
            "result": result,  # 'win' ou 'loss'
            "attemptsUsed": attempts_used,
            "hour": dt_brazil.hour,  # Hora de Brasília
            "dayOfWeek": dt_brazil.weekday(),  # 0=Monday, 6=Sunday
            "date": dt_brazil.strftime("%Y-%m-%d"),  # Data de Brasília
            "confLabel": signal_data.get('confLabel', 'media')
        }
        
        await db_module.db.signal_history.insert_one(history_doc)
        print(f"[Stats] Sinal salvo no histórico: {platform} {result} ({signal_data.get('patternKey')}) - {dt_brazil.strftime('%H:%M')}")
    except Exception as e:
        print(f"Erro ao salvar sinal no histórico: {e}")



async def load_stats_from_db():
    """Carrega estatísticas do MongoDB na inicialização"""
    global signal_stats, last_win_ts, last_loss_ts, current_win_streak, max_win_streak, win_streak_history, signal_outcome_history, results_history
    try:
        if db_module.db is None:
            return
        
        stats_doc = await db_module.db.stats.find_one({"_id": "global_stats"})
        if stats_doc:
            signal_stats.update(stats_doc.get("signal_stats", {}))
            last_win_ts = stats_doc.get("last_win_ts")
            last_loss_ts = stats_doc.get("last_loss_ts")
            current_win_streak = stats_doc.get("current_win_streak", 0)
            max_win_streak = stats_doc.get("max_win_streak", 0)
            win_streak_history = stats_doc.get("win_streak_history", [])
            signal_outcome_history = stats_doc.get("signal_outcome_history", [])
            # Carregar histórico de resultados se existir
            loaded_results = stats_doc.get("results_history", [])
            if loaded_results:
                results_history = loaded_results
            
            # Verificação de consistência: Total de Wins não pode ser menor que Sequência Atual
            total_wins = signal_stats["geral"].get("acertos", 0)
            if current_win_streak > total_wins:
                print(f"⚠️ Inconsistência detectada: Streak ({current_win_streak}) > Total Wins ({total_wins}). Corrigindo Total Wins.")
                signal_stats["geral"]["acertos"] = current_win_streak
                signal_stats["geral"]["total"] = max(signal_stats["geral"].get("total", 0), current_win_streak)
                
            print(f"✅ Estatísticas carregadas do DB: {len(win_streak_history)} streaks, max: {max_win_streak}, results: {len(results_history)}")
    except Exception as e:
        print(f"Erro ao carregar stats do DB: {e}")

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

@app.get("/favicon.ico")
async def favicon():
    ico_path = os.path.join(base_dir, "favicon.ico")
    if os.path.exists(ico_path):
        return FileResponse(ico_path, media_type="image/x-icon")
    return HTMLResponse(status_code=204)


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

@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    """Página de estatísticas - requer autenticação"""
    try:
        await get_current_user(request)
    except Exception:
        return HTMLResponse(content="", status_code=302, headers={"Location": "/auth"})
    
    html_path = os.path.join(base_dir, "stats.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Stats page not found</h1>", status_code=404)

@app.get("/stats.js")
async def stats_js():
    js_path = os.path.join(base_dir, "stats.js")
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

@app.get("/api/signal_stats")
async def api_signal_stats():
    try:
        geral = signal_stats.get("geral", {})
        total = int(geral.get("total", 0))
        acertos = int(geral.get("acertos", 0))
        perdas = max(0, total - acertos)
        return {
            "ok": True,
            "wins": acertos,
            "losses": perdas,
            "lastWinTime": last_win_ts,
            "lastLossTime": last_loss_ts,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/win_streaks")
async def api_win_streaks():
    """Retorna estatísticas de sequências de wins entre losses"""
    try:
        # Calcular média de wins entre losses
        avg_wins = 0.0
        if len(win_streak_history) > 0:
            avg_wins = sum(win_streak_history) / len(win_streak_history)
        
        return {
            "ok": True,
            "currentStreak": current_win_streak,
            "maxStreak": max_win_streak,
            "averageWinsBetweenLosses": round(avg_wins, 2),
            "streakHistory": win_streak_history[-10:] if len(win_streak_history) > 0 else [],
            "totalStreaks": len(win_streak_history)
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ============================================================
# ENDPOINT PARA SALVAR RESULTADO DE SINAL NO HISTÓRICO
# ============================================================

@app.post("/api/signal/resolve")
async def api_signal_resolve(request: Request):
    """Recebe o resultado de um sinal do frontend e salva no histórico"""
    try:
        data = await request.json()
        
        signal_id = data.get("id")
        result = data.get("result")  # "win" ou "loss"
        attempts_used = data.get("attemptsUsed", 1)
        platform = data.get("platform", "playnabet")
        pattern_key = data.get("patternKey", "unknown")
        color = data.get("color")
        chance = data.get("chance", 0)
        created_at = data.get("createdAt", int(time.time() * 1000))
        
        if not result or result not in ["win", "loss"]:
            return {"ok": False, "error": "result deve ser 'win' ou 'loss'"}
        
        signal_data = {
            "id": signal_id,
            "patternKey": pattern_key,
            "color": color,
            "chance": chance,
            "createdAt": created_at
        }
        
        await save_signal_to_history(signal_data, result, attempts_used, platform)
        
        return {"ok": True, "message": f"Sinal {signal_id} salvo como {result}"}
    except Exception as e:
        print(f"Erro ao resolver sinal: {e}")
        return {"ok": False, "error": str(e)}

# ============================================================
# ENDPOINTS DE ESTATÍSTICAS AVANÇADAS
# ============================================================

@app.get("/api/stats/overview")
async def api_stats_overview(platform: str = "all", days: int = 30):
    """Retorna estatísticas gerais para o dashboard"""
    try:
        if db_module.db is None:
            return {"ok": False, "error": "Database not connected"}
        
        # Filtrar por período
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_ts = int(cutoff.timestamp() * 1000)
        
        query = {"createdAt": {"$gte": cutoff_ts}}
        if platform != "all":
            query["platform"] = platform
        
        signals = await db_module.db.signal_history.find(query).to_list(length=10000)
        
        total = len(signals)
        wins = sum(1 for s in signals if s.get("result") == "win")
        losses = total - wins
        rate = round((wins / total * 100), 2) if total > 0 else 0
        
        # ROI simulado (aposta R$10, retorno 2x no win)
        # ROI = ((wins * 20) - (total * 10)) / (total * 10) * 100
        roi = round(((wins * 20) - (total * 10)) / (total * 10) * 100, 2) if total > 0 else 0
        
        return {
            "ok": True,
            "total": total,
            "wins": wins,
            "losses": losses,
            "rate": rate,
            "roi": roi,
            "platform": platform,
            "days": days
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/stats/by-hour")
async def api_stats_by_hour(platform: str = "all", days: int = 30):
    """Retorna taxa de acerto por hora do dia"""
    try:
        if db_module.db is None:
            return {"ok": False, "error": "Database not connected"}
        
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_ts = int(cutoff.timestamp() * 1000)
        
        query = {"createdAt": {"$gte": cutoff_ts}}
        if platform != "all":
            query["platform"] = platform
        
        signals = await db_module.db.signal_history.find(query).to_list(length=10000)
        
        # Agrupar por hora
        by_hour = {}
        for h in range(24):
            by_hour[h] = {"total": 0, "wins": 0}
        
        for s in signals:
            hour = s.get("hour", 0)
            by_hour[hour]["total"] += 1
            if s.get("result") == "win":
                by_hour[hour]["wins"] += 1
        
        # Calcular taxas
        result = []
        for hour in range(24):
            data = by_hour[hour]
            rate = round((data["wins"] / data["total"] * 100), 2) if data["total"] > 0 else 0
            result.append({
                "hour": hour,
                "total": data["total"],
                "wins": data["wins"],
                "rate": rate
            })
        
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/stats/by-pattern")
async def api_stats_by_pattern(platform: str = "all", days: int = 30):
    """Retorna taxa de acerto por padrão detectado"""
    try:
        if db_module.db is None:
            return {"ok": False, "error": "Database not connected"}
        
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_ts = int(cutoff.timestamp() * 1000)
        
        query = {"createdAt": {"$gte": cutoff_ts}}
        if platform != "all":
            query["platform"] = platform
        
        signals = await db_module.db.signal_history.find(query).to_list(length=10000)
        
        # Agrupar por padrão
        by_pattern = {}
        for s in signals:
            pattern = s.get("patternKey", "unknown")
            if pattern not in by_pattern:
                by_pattern[pattern] = {"total": 0, "wins": 0}
            by_pattern[pattern]["total"] += 1
            if s.get("result") == "win":
                by_pattern[pattern]["wins"] += 1
        
        # Calcular taxas e ordenar por total
        result = []
        for pattern, data in by_pattern.items():
            rate = round((data["wins"] / data["total"] * 100), 2) if data["total"] > 0 else 0
            result.append({
                "pattern": pattern,
                "total": data["total"],
                "wins": data["wins"],
                "rate": rate
            })
        
        result.sort(key=lambda x: x["total"], reverse=True)
        
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/stats/pattern-tips")
async def api_stats_pattern_tips(platform: str = "all", days: int = 7, min_signals: int = 5):
    """Retorna dicas de padrões: o melhor e o pior (com mínimo de sinais)"""
    try:
        if db_module.db is None:
            return {"ok": False, "error": "Database not connected"}
        
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_ts = int(cutoff.timestamp() * 1000)
        
        query = {"createdAt": {"$gte": cutoff_ts}}
        if platform != "all":
            query["platform"] = platform
        
        signals = await db_module.db.signal_history.find(query).to_list(length=10000)
        
        # Agrupar por padrão
        by_pattern = {}
        for s in signals:
            pattern = s.get("patternKey", "unknown")
            if pattern not in by_pattern:
                by_pattern[pattern] = {"total": 0, "wins": 0}
            by_pattern[pattern]["total"] += 1
            if s.get("result") == "win":
                by_pattern[pattern]["wins"] += 1
        
        # Calcular taxas (apenas padrões com mínimo de sinais)
        patterns_with_rate = []
        for pattern, data in by_pattern.items():
            if data["total"] >= min_signals:
                rate = round((data["wins"] / data["total"] * 100), 2)
                patterns_with_rate.append({
                    "pattern": pattern,
                    "total": data["total"],
                    "wins": data["wins"],
                    "rate": rate
                })
        
        if not patterns_with_rate:
            return {
                "ok": True,
                "best": None,
                "worst": None,
                "message": f"Poucos dados (mínimo {min_signals} sinais por padrão)"
            }
        
        # Ordenar por taxa
        patterns_with_rate.sort(key=lambda x: x["rate"], reverse=True)
        
        best = patterns_with_rate[0]
        worst = patterns_with_rate[-1]
        
        return {
            "ok": True,
            "best": {
                "pattern": best["pattern"],
                "rate": best["rate"],
                "total": best["total"],
                "wins": best["wins"]
            },
            "worst": {
                "pattern": worst["pattern"],
                "rate": worst["rate"],
                "total": worst["total"],
                "wins": worst["wins"]
            },
            "days": days,
            "platform": platform
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/stats/by-attempt")
async def api_stats_by_attempt(platform: str = "all", days: int = 30):
    """Retorna estatísticas de win/loss por número de tentativa (1ª, 2ª, 3ª)"""
    try:
        if db_module.db is None:
            return {"ok": False, "error": "Database not connected"}
        
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_ts = int(cutoff.timestamp() * 1000)
        
        query = {"createdAt": {"$gte": cutoff_ts}, "result": "win"}
        if platform != "all":
            query["platform"] = platform
        
        # Buscar apenas wins (losses são sempre na última tentativa)
        wins = await db_module.db.signal_history.find(query).to_list(length=10000)
        
        # Contar por tentativa
        attempts = {1: 0, 2: 0, 3: 0}
        for w in wins:
            att = w.get("attemptsUsed", 1)
            if att in attempts:
                attempts[att] += 1
        
        total_wins = sum(attempts.values())
        
        # Total de sinais (incluindo losses)
        total_query = {"createdAt": {"$gte": cutoff_ts}}
        if platform != "all":
            total_query["platform"] = platform
        total_signals = await db_module.db.signal_history.count_documents(total_query)
        total_losses = total_signals - total_wins
        
        return {
            "ok": True,
            "data": {
                "first_attempt": attempts[1],
                "second_attempt": attempts[2],
                "third_attempt": attempts[3],
                "total_wins": total_wins,
                "total_losses": total_losses,
                "total_signals": total_signals
            },
            "percentages": {
                "first": round((attempts[1] / total_wins * 100), 1) if total_wins > 0 else 0,
                "second": round((attempts[2] / total_wins * 100), 1) if total_wins > 0 else 0,
                "third": round((attempts[3] / total_wins * 100), 1) if total_wins > 0 else 0
            },
            "platform": platform,
            "days": days
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/stats/by-day")
async def api_stats_by_day(platform: str = "all", days: int = 30):
    """Retorna taxa de acerto por dia (para gráfico de linha)"""
    try:
        if db_module.db is None:
            return {"ok": False, "error": "Database not connected"}
        
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_ts = int(cutoff.timestamp() * 1000)
        
        query = {"createdAt": {"$gte": cutoff_ts}}
        if platform != "all":
            query["platform"] = platform
        
        signals = await db_module.db.signal_history.find(query).to_list(length=10000)
        
        # Agrupar por data
        by_date = {}
        for s in signals:
            date = s.get("date", "unknown")
            if date not in by_date:
                by_date[date] = {"total": 0, "wins": 0}
            by_date[date]["total"] += 1
            if s.get("result") == "win":
                by_date[date]["wins"] += 1
        
        # Calcular taxas e ordenar por data
        result = []
        for date, data in by_date.items():
            rate = round((data["wins"] / data["total"] * 100), 2) if data["total"] > 0 else 0
            result.append({
                "date": date,
                "total": data["total"],
                "wins": data["wins"],
                "rate": rate
            })
        
        result.sort(key=lambda x: x["date"])
        
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/stats/signals-history")
async def api_stats_signals_history(platform: str = "all", days: int = 30, page: int = 1, limit: int = 50):
    """Retorna histórico de sinais com paginação"""
    try:
        if db_module.db is None:
            return {"ok": False, "error": "Database not connected"}
        
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_ts = int(cutoff.timestamp() * 1000)
        
        query = {"createdAt": {"$gte": cutoff_ts}}
        if platform != "all":
            query["platform"] = platform
        
        # Contar total
        total = await db_module.db.signal_history.count_documents(query)
        
        # Buscar com paginação
        skip = (page - 1) * limit
        signals = await db_module.db.signal_history.find(query).sort("createdAt", -1).skip(skip).limit(limit).to_list(length=limit)
        
        # Formatar para JSON (remover _id do MongoDB)
        formatted = []
        for s in signals:
            formatted.append({
                "id": s.get("id"),
                "platform": s.get("platform"),
                "patternKey": s.get("patternKey"),
                "color": s.get("color"),
                "result": s.get("result"),
                "attemptsUsed": s.get("attemptsUsed"),
                "createdAt": s.get("createdAt"),
                "hour": s.get("hour"),
                "date": s.get("date")
            })
        
        return {
            "ok": True,
            "data": formatted,
            "total": total,
            "page": page,
            "limit": limit,
            "totalPages": (total + limit - 1) // limit
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/admin/reset")
async def admin_reset_state(admin_user: dict = Depends(get_admin_user)):
    try:
        global results_history, pending_bets, cooldown_contador, perdas_consecutivas, modo_stop, stop_counter, modo_conservador, historico_alertas, round_index, signal_stats, sinais_perdidos_por_pausa, compensation_remaining
        global win_streak_history, current_win_streak, max_win_streak, signal_outcome_history
        global signal_outcomes_history
        global verabet_results_history, verabet_pending_bets, verabet_round_index
        global verabet_signal_stats, verabet_win_streak_history, verabet_current_win_streak, verabet_max_win_streak
        global verabet_last_win_ts, verabet_last_loss_ts
        results_history = []
        pending_bets = []
        cooldown_contador = 0
        perdas_consecutivas = 0
        modo_stop = False
        stop_counter = 0
        modo_conservador = False
        historico_alertas = []
        round_index = 0
        sinais_perdidos_por_pausa = 0
        compensation_remaining = 0
        # Reset win streak tracking
        win_streak_history = []
        current_win_streak = 0
        max_win_streak = 0
        signal_outcome_history = []
        signal_outcomes_history = []
        signal_stats = {
            "alta": {"total": 0, "acertos": 0, "taxa": 0.0},
            "media": {"total": 0, "acertos": 0, "taxa": 0.0},
            "baixa": {"total": 0, "acertos": 0, "taxa": 0.0},
            "geral": {"total": 0, "acertos": 0, "taxa": 0.0},
        }
        verabet_results_history = []
        verabet_pending_bets = []
        verabet_round_index = 0
        verabet_signal_stats = {
            "alta": {"total": 0, "acertos": 0, "taxa": 0.0},
            "media": {"total": 0, "acertos": 0, "taxa": 0.0},
            "baixa": {"total": 0, "acertos": 0, "taxa": 0.0},
            "geral": {"total": 0, "acertos": 0, "taxa": 0.0},
        }
        verabet_win_streak_history = []
        verabet_current_win_streak = 0
        verabet_max_win_streak = 0
        verabet_last_win_ts = None
        verabet_last_loss_ts = None
        
        # Limpar coleção de stats no MongoDB
        try:
            if db_module.db is not None:
                await db_module.db.stats.delete_many({})
                try:
                    await db_module.db.stats.delete_one({"_id": "verabet_stats"})
                except Exception:
                    pass
                print("✅ Coleção de stats limpa no MongoDB")
        except Exception as e:
            print(f"Erro ao limpar stats no DB: {e}")
            
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            for fname in ("platt_params.json", "pattern_stats.json"):
                fpath = os.path.join(base, fname)
                if os.path.exists(fpath):
                    os.remove(fpath)
        except Exception:
            pass
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/auth/admin/stats")
async def _admin_stats(admin_user: dict = Depends(get_admin_user)):
    total_users = await db_module.db.users.count_documents({})
    total_bankroll = await db_module.db.users.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$bankroll"}}}
    ]).to_list(length=1)
    total_bankroll_value = total_bankroll[0]["total"] if total_bankroll else 0
    return {
        "total_users": total_users,
        "total_bankroll": float(total_bankroll_value),
        "database_name": db_module.db.name,
    }

@app.get("/api/auth/admin/users")
async def _admin_users(admin_user: dict = Depends(get_admin_user)):
    projection = {
        "email": 1,
        "username": 1,
        "bankroll": 1,
        "enabled_colors": 1,
        "enabled_patterns": 1,
        "receive_alerts": 1,
        "is_admin": 1,
        "created_at": 1,
        "last_login": 1,
        "_id": 0,
    }
    users = await db_module.db.users.find({}, projection).to_list(length=None)
    def _normalize(u):
        return {
            "email": u.get("email"),
            "username": u.get("username"),
            "bankroll": float(u.get("bankroll", 0)),
            "enabled_colors": u.get("enabled_colors", []),
            "enabled_patterns": u.get("enabled_patterns", []),
            "receive_alerts": bool(u.get("receive_alerts", True)),
            "is_admin": bool(u.get("is_admin", False)),
            "created_at": u.get("created_at"),
            "last_login": u.get("last_login"),
        }
    return {"users": [ _normalize(u) for u in users ]}

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
    
    # Carregar estatísticas do banco de dados
    try:
        await load_stats_from_db()
    except Exception as e:
        print(f"[startup] Falha ao carregar stats do DB: {e}")
    
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
            
        # Salvar no banco de dados de forma assíncrona
        try:
            asyncio.create_task(save_stats_to_db())
        except Exception:
            pass
        
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
                        try:
                            last_win_ts = now_ts
                            asyncio.create_task(save_stats_to_db())
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
                        # Salvar no histórico para estatísticas
                        try:
                            asyncio.create_task(save_signal_to_history(pb, 'win', pb['attemptsUsed'], 'playnabet'))
                        except Exception:
                            pass
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
                            try:
                                last_loss_ts = now_ts
                                asyncio.create_task(save_stats_to_db())
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
                            # Salvar no histórico para estatísticas
                            try:
                                asyncio.create_task(save_signal_to_history(pb, 'loss', pb['attemptsUsed'], 'playnabet'))
                            except Exception:
                                pass
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
                            if suggested_color == 'white':
                                suggested_color = None
                            # chance estimada simplificada baseada no label de confiança
                            chance_map = {'alto': 85, 'medio-alto': 75, 'medio': 65, 'baixo-medio': 55, 'baixo': 30}
                            chance_pct = chance_map.get(conf_label, 50)
                            targets = numbers_for_color(suggested_color) if suggested_color else []
                            if not suggested_color:
                                signal = None
                            else:
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
                    try:
                        global sinais_emitidos_hoje
                        sinais_emitidos_hoje += 1
                    except Exception:
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

# ============================================================
# VERABET DOUBLE INTEGRATION
# ============================================================
from services.verabet_client import VeraBetClient, parse_verabet_result, fetch_initial_history
from services.verabet_patterns import VeraBetPatternEngine

# Estado global VeraBet (separado do PlayNaBet)
verabet_results_history: List[Dict] = []
verabet_ws_connection: VeraBetClient = None
verabet_ws_connected = False
verabet_event_clients: List[asyncio.Queue] = []
verabet_pending_bets: List[Dict] = []
verabet_round_index = 0
verabet_signal_stats = {
    "alta": {"total": 0, "acertos": 0, "taxa": 0.0},
    "media": {"total": 0, "acertos": 0, "taxa": 0.0},
    "baixa": {"total": 0, "acertos": 0, "taxa": 0.0},
    "geral": {"total": 0, "acertos": 0, "taxa": 0.0}
}
verabet_win_streak_history = []
verabet_current_win_streak = 0
verabet_max_win_streak = 0
verabet_last_win_ts = None
verabet_last_loss_ts = None
verabet_signal_outcome_history = []  # Histórico de outcomes: [{'outcome': 'win'|'loss', 'ts': timestamp}]

# VeraBet pattern engine instance (motor dedicado para VeraBet)
try:
    verabet_pattern_engine = VeraBetPatternEngine()
    print("✅ VeraBet Pattern Engine inicializado")
except Exception as e:
    verabet_pattern_engine = None
    print(f"⚠️ Erro ao inicializar VeraBet Pattern Engine: {e}")

async def save_verabet_stats_to_db():
    """Salva estatísticas do VeraBet no MongoDB para persistência"""
    try:
        if db_module.db is None:
            return
        
        stats_doc = {
            "_id": "verabet_stats",
            "signal_stats": verabet_signal_stats,
            "last_win_ts": verabet_last_win_ts,
            "last_loss_ts": verabet_last_loss_ts,
            "current_win_streak": verabet_current_win_streak,
            "max_win_streak": verabet_max_win_streak,
            "win_streak_history": verabet_win_streak_history[-100:],  # últimas 100
            "signal_outcome_history": verabet_signal_outcome_history[-100:],  # últimos 100 outcomes
            "results_history": verabet_results_history[-50:],  # últimos 50 resultados
            "updated_at": int(time.time() * 1000)
        }
        
        await db_module.db.stats.update_one(
            {"_id": "verabet_stats"},
            {"$set": stats_doc},
            upsert=True
        )
    except Exception as e:
        print(f"[VeraBet] Erro ao salvar stats no DB: {e}")

async def load_verabet_stats_from_db():
    """Carrega estatísticas do VeraBet do MongoDB na inicialização"""
    global verabet_signal_stats, verabet_last_win_ts, verabet_last_loss_ts
    global verabet_current_win_streak, verabet_max_win_streak, verabet_win_streak_history
    global verabet_results_history
    try:
        if db_module.db is None:
            return
        
        stats_doc = await db_module.db.stats.find_one({"_id": "verabet_stats"})
        if stats_doc:
            verabet_signal_stats.update(stats_doc.get("signal_stats", {}))
            verabet_last_win_ts = stats_doc.get("last_win_ts")
            verabet_last_loss_ts = stats_doc.get("last_loss_ts")
            verabet_current_win_streak = stats_doc.get("current_win_streak", 0)
            verabet_max_win_streak = stats_doc.get("max_win_streak", 0)
            verabet_win_streak_history = stats_doc.get("win_streak_history", [])
            global verabet_signal_outcome_history
            verabet_signal_outcome_history = stats_doc.get("signal_outcome_history", [])
            
            # Carregar histórico de resultados se existir
            loaded_results = stats_doc.get("results_history", [])
            if loaded_results:
                verabet_results_history = loaded_results
            
            print(f"✅ [VeraBet] Estatísticas carregadas do DB: {len(verabet_win_streak_history)} streaks, max: {verabet_max_win_streak}, results: {len(verabet_results_history)}")
    except Exception as e:
        print(f"[VeraBet] Erro ao carregar stats do DB: {e}")


def verabet_on_message(data: Dict):
    """Callback para mensagens do cliente VeraBet"""
    global verabet_results_history, verabet_ws_connected, verabet_round_index
    
    if data.get("type") == "status":
        verabet_ws_connected = data.get("connected", False)
        message = f"event: status\ndata: {json.dumps(data)}\n\n"
        for queue in verabet_event_clients:
            try:
                queue.put_nowait(message)
            except:
                pass
        return
    
    # Processar resultado do Double
    if data.get("source") == "verabet":
        verabet_round_index += 1
        
        # Evitar duplicatas
        if verabet_results_history:
            last = verabet_results_history[-1]
            if last.get("round_id") == data.get("round_id"):
                return
        
        verabet_results_history.append(data)
        if len(verabet_results_history) > 100:
            verabet_results_history = verabet_results_history[-100:]
        
        # Notificar clientes SSE
        result_payload = {"type": "double_result", "data": data}
        message = f"event: double_result\ndata: {json.dumps(result_payload)}\n\n"
        for queue in verabet_event_clients:
            try:
                queue.put_nowait(message)
            except:
                pass
        
        # Avaliar pendentes
        signal_just_resolved = False  # Flag para bloquear novo sinal após resolução
        try:
            if CONFIG.MARTINGALE_ENABLED and verabet_pending_bets:
                res_color = data.get('color')
                now_ts = int(time.time() * 1000)
                remove_ids = []
                
                print(f"[VeraBet] Avaliando {len(verabet_pending_bets)} pendente(s) | Resultado: {res_color}")
                
                for pb in list(verabet_pending_bets):
                    attempts_left = pb.get('attemptsLeft', CONFIG.MARTINGALE_MAX_ATTEMPTS)
                    target_color = pb.get('color')
                    
                    created_round = pb.get('createdRound')
                    if created_round is not None and created_round == verabet_round_index:
                        print(f"[VeraBet] Pulando pendente {pb.get('id')} - mesma rodada de criação")
                        continue
                    
                    protect_white = pb.get('protect_white', False)
                    is_win = (res_color == target_color) or (protect_white and res_color == 'white')
                    
                    print(f"[VeraBet] Pendente {pb.get('patternKey')} | Alvo: {target_color} | Saiu: {res_color} | Tentativas: {pb.get('attemptsUsed', 0)+1}/{3}")
                    
                    if is_win:
                        pb['attemptsUsed'] = pb.get('attemptsUsed', 0) + 1
                        pb['resolved'] = True
                        pb['result'] = 'win'
                        pb['resolvedAt'] = now_ts
                        verabet_registrar_resultado_sinal(pb.get('confLabel', 'media'), True)
                        bet_payload = {"type": "bet_result", "data": pb}
                        bet_message = f"event: bet_result\ndata: {json.dumps(bet_payload)}\n\n"
                        for queue in verabet_event_clients:
                            try:
                                queue.put_nowait(bet_message)
                            except:
                                pass
                        remove_ids.append(pb.get('id'))
                        signal_just_resolved = True
                        print(f"[VeraBet] ✅ WIN detectado para {pb.get('patternKey')} após {pb['attemptsUsed']} tentativa(s)")
                        # Salvar no histórico para estatísticas
                        try:
                            asyncio.create_task(save_signal_to_history(pb, 'win', pb['attemptsUsed'], 'verabet'))
                        except Exception:
                            pass
                    else:
                        pb['attemptsLeft'] = attempts_left - 1
                        pb['attemptsUsed'] = pb.get('attemptsUsed', 0) + 1
                        print(f"[VeraBet] ❌ Não acertou - tentativas restantes: {pb['attemptsLeft']}")
                        if pb['attemptsLeft'] <= 0:
                            pb['resolved'] = True
                            pb['result'] = 'loss'
                            pb['resolvedAt'] = now_ts
                            verabet_registrar_resultado_sinal(pb.get('confLabel', 'media'), False)
                            bet_payload = {"type": "bet_result", "data": pb}
                            bet_message = f"event: bet_result\ndata: {json.dumps(bet_payload)}\n\n"
                            for queue in verabet_event_clients:
                                try:
                                    queue.put_nowait(bet_message)
                                except:
                                    pass
                            remove_ids.append(pb.get('id'))
                            signal_just_resolved = True
                            print(f"[VeraBet] ❌ LOSS detectado para {pb.get('patternKey')} após 3 tentativas")
                            # Salvar no histórico para estatísticas
                            try:
                                asyncio.create_task(save_signal_to_history(pb, 'loss', pb['attemptsUsed'], 'verabet'))
                            except Exception:
                                pass
                
                if remove_ids:
                    verabet_pending_bets[:] = [p for p in verabet_pending_bets if p.get('id') not in remove_ids]
        except Exception as e:
            print(f"[VeraBet] Erro ao avaliar pendentes: {e}")
        
        
        # Detectar sinal usando VeraBetPatternEngine
        # Deve funcionar mesmo sem clientes SSE conectados — stats precisam persistir 24/7
        # Ainda bloqueamos se houver pendentes ou se acabou de resolver um sinal
        if len(verabet_results_history) >= 3 and verabet_pattern_engine:
            try:
                # VeraBet SEMPRE bloqueia sinais enquanto houver pendente (independente de CONFIG)
                # Também bloqueia se acabamos de resolver um sinal nesta rodada
                if verabet_pending_bets or signal_just_resolved:
                    # Há sinal pendente ou acabamos de resolver, não detectar novo
                    if signal_just_resolved:
                        print(f"[VeraBet] Bloqueando novo sinal - acabou de resolver um")
                    signal = None
                else:
                    # Converter histórico para formato V/P/B
                    short_hist = []
                    for r in verabet_results_history:
                        c = r.get('color')
                        if c == 'red':
                            short_hist.append('V')
                        elif c == 'black':
                            short_hist.append('P')
                        else:
                            short_hist.append('B')
                    
                    # Usar o método gerar_sinal do VeraBetPatternEngine
                    signal = verabet_pattern_engine.gerar_sinal(short_hist)
                    
                    # Adicionar informação do último resultado ao sinal
                    if signal and verabet_results_history:
                        last_result = verabet_results_history[-1]
                        last_num = last_result.get('number', '?')
                        last_color = last_result.get('color', '')
                        last_color_name = 'Vermelho' if last_color == 'red' else 'Preto' if last_color == 'black' else 'Branco'
                        suggested_color_name = 'Vermelho' if signal.get('color') == 'red' else 'Preto'
                        
                        # Atualizar descrição para mostrar o número que disparou
                        signal['description'] = f"Após o {last_num} {last_color_name} → Aposte no {suggested_color_name}!"
                        signal['lastNumber'] = last_num
                        signal['lastColor'] = last_color
                
                if signal:
                    print(f"[VeraBet] Sinal detectado: {signal.get('patternKey')} → {signal.get('color')} ({signal.get('chance')}%)")
                    
                    signal_payload = {"type": "signal", "data": signal}
                    signal_message = f"event: signal\ndata: {json.dumps(signal_payload)}\n\n"
                    clients_notified = 0
                    for queue in verabet_event_clients:
                        try:
                            queue.put_nowait(signal_message)
                            clients_notified += 1
                        except:
                            pass
                    
                    
                    # SEMPRE adicionar aos pendentes se martingale estiver ativo, mesmo sem clientes
                    # Isso garante que o histórico de wins/losses seja gerado 24/7
                    if CONFIG.MARTINGALE_ENABLED:
                        pb = {
                            'id': signal.get('id'),
                            'patternKey': signal.get('patternKey'),
                            'color': signal.get('color'),
                            'numbers': signal.get('targets', []),
                            'chance': signal.get('chance', 0),
                            'createdAt': int(time.time() * 1000),
                            'createdRound': verabet_round_index,
                            'attemptsLeft': signal.get('maxAttempts', 3),
                            'attemptsUsed': 0,
                            'protect_white': signal.get('protect_white', False),
                            'confLabel': signal.get('confLabel', 'media'),
                        }
                        verabet_pending_bets.append(pb)
                        
                        if clients_notified > 0:
                            print(f"[VeraBet] Sinal enviado para {clients_notified} cliente(s)")
                        else:
                            print(f"[VeraBet] Sinal registrado internamente (sem clientes conectados)")
            except Exception as e:
                print(f"[VeraBet] Erro na detecção de sinal: {e}")

def verabet_registrar_resultado_sinal(confianca: str, acertou: bool):
    global verabet_current_win_streak, verabet_max_win_streak, verabet_win_streak_history
    global verabet_last_win_ts, verabet_last_loss_ts, verabet_signal_outcome_history
    try:
        lbl = confianca if confianca in ("alta", "media", "baixa") else "media"
        verabet_signal_stats[lbl]["total"] = verabet_signal_stats[lbl].get("total", 0) + 1
        verabet_signal_stats["geral"]["total"] = verabet_signal_stats["geral"].get("total", 0) + 1
        
        # Registrar outcome no histórico
        outcome = "win" if acertou else "loss"
        verabet_signal_outcome_history.append({"outcome": outcome, "ts": int(time.time() * 1000)})
        if len(verabet_signal_outcome_history) > 100:
            verabet_signal_outcome_history = verabet_signal_outcome_history[-100:]
        
        if acertou:
            verabet_signal_stats[lbl]["acertos"] = verabet_signal_stats[lbl].get("acertos", 0) + 1
            verabet_signal_stats["geral"]["acertos"] = verabet_signal_stats["geral"].get("acertos", 0) + 1
            verabet_current_win_streak += 1
            if verabet_current_win_streak > verabet_max_win_streak:
                verabet_max_win_streak = verabet_current_win_streak
            verabet_last_win_ts = int(time.time() * 1000)
        else:
            if verabet_current_win_streak > 0:
                verabet_win_streak_history.append(verabet_current_win_streak)
                if len(verabet_win_streak_history) > 100:
                    verabet_win_streak_history = verabet_win_streak_history[-100:]
            verabet_current_win_streak = 0
            verabet_last_loss_ts = int(time.time() * 1000)
        
        # Salvar no banco de dados de forma assíncrona
        try:
            asyncio.create_task(save_verabet_stats_to_db())
        except Exception:
            pass
    except Exception:
        pass

def verabet_get_consecutive_losses():
    """
    Conta quantas VEZES aconteceu uma sequência de 2+ losses consecutivos.
    Retorna (contagem, timestamp_ultima_sequencia)
    """
    count = 0
    last_sequence_ts = None
    in_loss_streak = False
    current_streak = 0
    streak_start_ts = None
    
    for entry in verabet_signal_outcome_history:
        if entry.get("outcome") == "loss":
            if not in_loss_streak:
                # Primeiro loss da possível sequência
                in_loss_streak = True
                current_streak = 1
                streak_start_ts = entry.get("ts")
            else:
                current_streak += 1
        else:
            if in_loss_streak and current_streak >= 2:
                count += 1  # Terminou uma sequência válida de 2+ losses
                last_sequence_ts = streak_start_ts
            in_loss_streak = False
            current_streak = 0
            streak_start_ts = None
    
    # Checar se terminou em sequência ainda ativa
    if in_loss_streak and current_streak >= 2:
        count += 1
        last_sequence_ts = streak_start_ts
    
    return count, last_sequence_ts

# VeraBet Routes
@app.get("/verabet", response_class=HTMLResponse)
async def verabet_page(request: Request):
    """Página VeraBet Double - requer autenticação"""
    try:
        await get_current_user(request)
    except Exception:
        return HTMLResponse(content="", status_code=302, headers={"Location": "/auth"})
    
    html_path = os.path.join(base_dir, "verabet.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>VeraBet page not found</h1>", status_code=404)

@app.get("/verabet_app.js")
async def verabet_app_js():
    js_path = os.path.join(base_dir, "verabet_app.js")
    if os.path.exists(js_path):
        return FileResponse(js_path, media_type="application/javascript")
    return {"error": "File not found"}, 404

@app.get("/verabet/api/status")
async def verabet_status():
    return {
        "ok": True,
        "wsConnected": verabet_ws_connected,
        "hasToken": False,
        "timestamp": int(time.time() * 1000)
    }

@app.get("/verabet/api/results")
async def verabet_api_get_results(limit: int = 20):
    return {
        "ok": True,
        "wsConnected": verabet_ws_connected,
        "results_count": len(verabet_results_history),
        "results": verabet_results_history[:limit],
    }

@app.get("/verabet/api/signal_stats")
async def verabet_api_signal_stats():
    try:
        geral = verabet_signal_stats.get("geral", {})
        total = int(geral.get("total", 0))
        acertos = int(geral.get("acertos", 0))
        perdas = max(0, total - acertos)
        return {
            "ok": True,
            "wins": acertos,
            "losses": perdas,
            "lastWinTime": verabet_last_win_ts,
            "lastLossTime": verabet_last_loss_ts,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/verabet/api/win_streaks")
async def verabet_api_win_streaks():
    try:
        avg_wins = 0.0
        if len(verabet_win_streak_history) > 0:
            avg_wins = sum(verabet_win_streak_history) / len(verabet_win_streak_history)
        # Calcular sequências de losses consecutivos (2+ seguidos)
        loss_sequences_count, last_sequence_ts = verabet_get_consecutive_losses()
        
        return {
            "ok": True,
            "currentStreak": verabet_current_win_streak,
            "maxStreak": verabet_max_win_streak,
            "consecutiveLossesCount": loss_sequences_count,
            "lastConsecutiveLossTime": last_sequence_ts,
            "averageWinsBetweenLosses": round(avg_wins, 2),
            "streakHistory": verabet_win_streak_history[-10:] if len(verabet_win_streak_history) > 0 else [],
            "totalStreaks": len(verabet_win_streak_history)
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/verabet/events")
async def verabet_events(request: Request):
    """Server-Sent Events para VeraBet Double"""
    async def event_generator():
        global verabet_ws_connected, verabet_ws_connection
        
        queue = asyncio.Queue()
        verabet_event_clients.append(queue)
        
        try:
            yield f"event: status\ndata: {json.dumps({'type': 'status', 'connected': verabet_ws_connected, 'ts': int(time.time() * 1000)})}\n\n"
            
            if verabet_ws_connection is None:
                verabet_ws_connection = VeraBetClient(verabet_on_message)
                await verabet_ws_connection.start()
            
            last_heartbeat = time.time()
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield message
                except asyncio.TimeoutError:
                    pass
                
                if time.time() - last_heartbeat >= 10:
                    yield f"event: ping\ndata: {json.dumps({'type': 'ping', 'ts': int(time.time() * 1000)})}\n\n"
                    last_heartbeat = time.time()
                
                await asyncio.sleep(0.1)
        finally:
            if queue in verabet_event_clients:
                verabet_event_clients.remove(queue)
    
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
async def startup_verabet_client():
    """Iniciar cliente VeraBet na inicialização"""
    global verabet_ws_connection, verabet_results_history
    try:
        # Carregar estatísticas do MongoDB
        await load_verabet_stats_from_db()
        
        # Carregar histórico inicial (se não foi carregado do DB)
        if len(verabet_results_history) == 0:
            initial_history = await fetch_initial_history(limit=30)
            if initial_history:
                verabet_results_history = initial_history
                print(f"[VeraBet] Histórico inicial carregado: {len(verabet_results_history)} resultados")
        else:
            print(f"[VeraBet] Histórico já carregado do DB: {len(verabet_results_history)} resultados")
        
        if verabet_ws_connection is None:
            verabet_ws_connection = VeraBetClient(verabet_on_message)
            await verabet_ws_connection.start()
            print("[VeraBet] Cliente de polling iniciado")
    except Exception as e:
        print(f"[VeraBet] Falha ao iniciar cliente: {e}")

@app.on_event("shutdown")
async def shutdown_verabet_client():
    global verabet_ws_connection
    try:
        if verabet_ws_connection is not None:
            await verabet_ws_connection.stop()
            print("[VeraBet] Cliente finalizado")
    except Exception as e:
        print(f"[VeraBet] Erro ao finalizar cliente: {e}")

# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)

