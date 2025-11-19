"""Script de teste: confirmar que, quando há uma pending bet, o servidor não emite outro signal
"""
import os, sys, time
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from app import on_message, results_history, pending_bets, event_clients
from config import CONFIG

# Dummy queue para capturar SSE events
class DummyQueue:
    def __init__(self):
        self.events = []
    def put_nowait(self, msg):
        print('SSE:', msg)
        self.events.append(msg)

# Reiniciar
results_history.clear(); pending_bets.clear(); event_clients.clear()
q = DummyQueue(); event_clients.append(q)

# Simular uma pending bet como se um signal tivesse sido emitido
pb = {'id': 'test_block_pb1', 'patternKey': 'triple_repeat', 'color': 'red', 'numbers': [1,2,3], 'chance': 70, 'createdAt': int(time.time()*1000), 'attemptsLeft': CONFIG.MARTINGALE_MAX_ATTEMPTS, 'attemptsUsed': 0}
pending_bets.append(pb)
print('Pending bet inserted:', pb)

# Agora emitir resultados que normalmente gerariam outro signal (por exemplo, sequência de 3 pretos)
def emit(num):
    payload = {"number": num, "timestamp": int(time.time()*1000)}
    print('emit', num)
    on_message(payload)
    time.sleep(2.2)

# Emitir 5 resultados que fariam uma sequência de 3 pretos no final
emit(8)
emit(8)
emit(8)

# No final, verificar se algum 'signal' foi enviado por causa desse padrão novo (deveria NÃO enviar)
print('\nEvents captured:')
for e in q.events:
    print(e)

print('\nPending bets after:', pending_bets)
print('Done')
