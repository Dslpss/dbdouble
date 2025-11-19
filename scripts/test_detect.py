"""Script de teste para verificar detecção de padrões no services.double

Roda alguns cenários de exemplo e imprime se um sinal é detectado.
"""
import os
import sys
# Garantir que o repositório esteja no caminho
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from services.double import detect_best_double_signal, detect_double_patterns, clear_signal_cooldown
from config import CONFIG
from services.adaptive_calibration import get_platt_params

# Função auxiliar para criar resultado com número e cor
import time

def make_result(number):
    color = 'white' if number == 0 else ('red' if number <= 7 else 'black')
    return {"number": number, "color": color, "round_id": f"r{int(time.time() * 1000)}", "timestamp": int(time.time() * 1000)}

# Cenários
scenarios = {
    'triple_repeat_red': [1,1,1],
    'streak_5_black': [8,8,8,8,8],
    'hot_zone_red_7_10': [1,2,3,4,1,2,3,5,1,1],
    'alternation': [1,8,1,8,1,8],
    'mixed_no_pattern': [1,8,1,0,8,2,3],
}

print('Config EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN =', CONFIG.EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN)
print('Config EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN =', CONFIG.EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN)
print('\nRunning with default behavior...')

for name, nums in scenarios.items():
    results = [make_result(n) for n in nums]
    patterns = detect_double_patterns(results)
    sig = detect_best_double_signal(results)
    print('-' * 60)
    print(f'Scenario: {name}')
    print('numbers:', nums)
    print('patterns detected:', [p['key'] for p in patterns])
    print('signal returned:', bool(sig))
    if sig:
        print(' signal info: ', {k: sig.get(k) for k in ('patternKey','type','confidence','chance')})
        nums = sig.get('suggestedBet', {}).get('numbers', [])
        color = sig.get('suggestedBet', {}).get('color')
        if nums and color:
            if len(nums) == 1:
                print(f" suggestion: Após o número {nums[0]}, apostar {color} ")
            else:
                print(f" suggestion: Se sair qualquer um destes números ({', '.join(map(str, nums))}), apostar {color} ")
            # Simular os próximos resultados para verificar martingale
            # Vamos simular no máximo MARTINGALE_MAX_ATTEMPTS e verificar se cor aparece
            sim_attempts = CONFIG.MARTINGALE_MAX_ATTEMPTS
            hit = False
            for i in range(sim_attempts):
                # se houver um número dentro numbers simula um hit no próximo
                # para testar caso positivo, use o primeiro `numbers` como próximo
                if i < len(nums):
                    next_num = nums[0]
                else:
                    next_num = nums[0] + 7 if nums else 1
                next_res = make_result(next_num)
                if next_res['color'] == color:
                    print(f"  simulated next result {i+1}: {next_res['number']} ({next_res['color']}) -> HIT")
                    hit = True
                    break
                else:
                    print(f"  simulated next result {i+1}: {next_res['number']} ({next_res['color']}) -> MISS")
            if not hit:
                print('  simulated outcome: LOSS after', sim_attempts, 'attempts')
    # Limpar cooldown entre testes para evitar bloqueio de sinais
    clear_signal_cooldown()

print('\n\nAgora testando com EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN = True\n')
CONFIG.EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN = True
print('Config EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN =', CONFIG.EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN)
for name, nums in scenarios.items():
    results = [make_result(n) for n in nums]
    patterns = detect_double_patterns(results)
    sig = detect_best_double_signal(results)
    print('-' * 60)
    print(f'Scenario: {name}')
    print('numbers:', nums)
    print('patterns detected:', [p['key'] for p in patterns])
    print('signal returned:', bool(sig))
    if sig:
        print(' signal info: ', {k: sig.get(k) for k in ('patternKey','type','confidence','chance')})
    clear_signal_cooldown()

print('\nTeste concluído')

print('\nAgora testando com EMIT_ON_ENABLED_PATTERNS_ONLY = True e ENABLED_PATTERNS = ["hot_zone_last10"]')
CONFIG.EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN = False
CONFIG.EMIT_ON_ENABLED_PATTERNS_ONLY = True
CONFIG.ENABLED_PATTERNS = ["hot_zone_last10"]
print('Config EMIT_ON_ENABLED_PATTERNS_ONLY =', CONFIG.EMIT_ON_ENABLED_PATTERNS_ONLY)
print('Config ENABLED_PATTERNS =', CONFIG.ENABLED_PATTERNS)
print('\nAgora testando EMIT_SIGNAL_BASED_ON_PATTERN_ONLY = True')
CONFIG.EMIT_SIGNAL_BASED_ON_PATTERN_ONLY = True
print('Config EMIT_SIGNAL_BASED_ON_PATTERN_ONLY =', CONFIG.EMIT_SIGNAL_BASED_ON_PATTERN_ONLY)
for name, nums in scenarios.items():
    results = [make_result(n) for n in nums]
    patterns = detect_double_patterns(results)
    sig = detect_best_double_signal(results)
    print('-' * 60)
    print(f'Scenario: {name}')
    print('numbers:', nums)
    print('patterns detected:', [p['key'] for p in patterns])
    print('signal returned:', bool(sig))
    if sig:
        print(' signal info: ', {k: sig.get(k) for k in ('patternKey','type','confidence','chance')})
    clear_signal_cooldown()

print('\nTeste concluído')
