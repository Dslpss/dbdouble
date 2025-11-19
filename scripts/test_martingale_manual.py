"""Script de teste do martingale (manual): adiciona um pending bet e emite resultados
para confirmar o win/loss após up to MARTINGALE_MAX_ATTEMPTS.
"""
import os, sys
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from app import on_message, results_history, pending_bets, event_clients
from config import CONFIG
import json
import time

# Dummy queue
class DummyQueue:
    def put_nowait(self, msg):
        print('SSE:', msg)

# Reset environment
event_clients.clear()
event_clients.append(DummyQueue())
results_history.clear()
pending_bets.clear()

# Add a pending bet as if a signal was created
pb = {
    'id': 'test_pb_1',
    'patternKey': 'triple_repeat',
    'color': 'red',
    'numbers': [1,2,3],
    'chance': 65,
    'createdAt': int(time.time() * 1000),
    'attemptsLeft': CONFIG.MARTINGALE_MAX_ATTEMPTS,
    'attemptsUsed': 0,
}

pending_bets.append(pb)
print('Added pending bet: ', pb)

# Emit a few results to simulate failure then success

def emit(n):
    payload = {"number": n, "timestamp": int(time.time() * 1000)}
    print('Emit result', n)
    on_message(payload)
    time.sleep(2.2)  # ensure timestamps differ

emit(8)  # black -> should be miss
emit(8)  # black -> miss
emit(1)  # red -> should be win if attempts left > 0

print('Pending bets after flow:', pending_bets)
print('Results history:', [r['number'] for r in results_history[-10:]])

print('done')
