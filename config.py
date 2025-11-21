"""
Configurações do DBcolor
Equivalente ao double.config.js
"""
import os
from dotenv import load_dotenv

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

class Config:
    # WebSocket URL
    WS_URL = os.getenv("PLAYNABETS_WS_URL", "wss://play.soline.bet:5903/Game")
    
    # Janelas e thresholds
    SEQ_LEN = 4  # sequência mínima para color_streak
    ALTERNATION_WINDOW = 3  # tamanho mínimo para alternância
    IMBALANCE_WINDOW = 20  # janela para red_black_balance
    IMBALANCE_DIFF = 2  # diferença mínima entre red e black
    
    # Qualidade mínima da amostra
    MIN_SAMPLE_TOTAL = 8
    
    # Seleção
    RANDOMIZE_TOP_DELTA = 5
    COMPOSED_MIN_AGREE = 1  # mínimo de padrões concordando
    
    # Cooldown de emissão (ms)
    COOLDOWN_MS = 10000

    # Emitir sinais apenas quando exatamente 1 padrão for detectado
    # Se True: retorna somente quando len(patterns) == 1
    EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN = False
    # Habilita envio apenas quando padrões configurados aparecem
    # Se True e ENABLED_PATTERNS não estiver vazio, o servidor só enviará
    # sinais quando pelo menos um dos padrões listados for detectado.
    EMIT_ON_ENABLED_PATTERNS_ONLY = False
    # Lista de padrões que podem disparar alerta. Lista vazia = todos os padrões permitidos
    ENABLED_PATTERNS = []
    # Se True: Emite sinal baseando-se apenas no pattern detectado (sem cálculo de score/predição)
    EMIT_SIGNAL_BASED_ON_PATTERN_ONLY = False
    # Martingale settings: enable/disable and number of attempts (max results to check)
    MARTINGALE_ENABLED = True
    MARTINGALE_MAX_ATTEMPTS = 3
    # Bloquear emissão de novos sinais enquanto houver aposta pendente
    BLOCK_SIGNALS_WHILE_PENDING = True
    
    # Parâmetros de calibração (Platt-like logistic)
    CALIBRATION = {
        "cal_slope": 0,
        "cal_intercept": -0.0047349634512580336,
    }

    # Habilitar uso do motor simples de padrões implementado em services/pattern_signals.py
    # Se True, o app usará SignalEngine para detectar sinais de acordo com os 8 padrões.
    USE_PATTERN_SIGNALS = True

CONFIG = Config()

