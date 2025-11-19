"""Script de teste para verificação do novo martingale: envia resultados via on_message e observa pending_bets e bet_result SSE
"""
import os, sys
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from app import on_message, results_history, pending_bets, event_clients
from services.parser import parse_double_payload
from config import CONFIG
import time

# Criar dummy queue para capturar SSE
class DummyQueue:
    def __init__(self):
        self.items = []
    def put_nowait(self, msg):
        print('SSE Message:', msg)

# garantir event_clients vazio e trocar por dummy
if event_clients:
    event_clients.clear()
q = DummyQueue()
event_clients.append(q)

# Função utilitaria: enviar resultados via on_message
emit_counter = 0
def emit_result(num, ts=None):
    global emit_counter
    # For test, ensure timestamps are at least 2.1s apart to avoid duplicate filtering
    base_ts = int(time.time() * 1000)
    ts_val = base_ts + (emit_counter * 2100)
    emit_counter += 1
    payload = {"number": num, "timestamp": ts_val}
    print('-> Emitting result', num)
    on_message(payload)

# Cenário: Vamos criar 10 resultados com 7 vermelhos nos últimos 10 (hot_zone_last10)
for n in [1,2,3,1,1,1,1,1,4,5]:
    emit_result(n)

# Agora emitir resultado que corresponda à aposta sugerida (por ex, color red)
# Se the suggested bet color is red, numbers should be 1..7. We'll emit 3 attempts: 8 (black), 2 (red) etc.
emit_result(8)
emit_result(2)

# Esperar para flush
print('Pending bets:', pending_bets)
print('Results history:', [r['number'] for r in results_history[-10:]])

print('Done')
