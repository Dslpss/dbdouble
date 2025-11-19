"""
Calibração adaptativa usando Platt scaling
Equivalente ao adaptiveCalibration.js
"""
import json
import os
from typing import Dict, Optional

STORAGE_FILE = "platt_params.json"
PATTERN_STATS_FILE = "pattern_stats.json"

def _read_json(filepath: str) -> Optional[Dict]:
    """Ler JSON do arquivo"""
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"Erro ao ler {filepath}: {e}")
    return None

def _write_json(filepath: str, obj: Dict):
    """Escrever JSON no arquivo"""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
    except Exception as e:
        print(f"Erro ao escrever {filepath}: {e}")

def get_platt_params() -> Optional[Dict]:
    """Obter parâmetros Platt"""
    p = _read_json(STORAGE_FILE)
    if p and isinstance(p.get("A"), (int, float)) and isinstance(p.get("B"), (int, float)):
        return p
    return None

def set_platt_params(A: float, B: float) -> Dict:
    """Definir parâmetros Platt"""
    obj = {
        "A": float(A) if A else 0,
        "B": float(B) if B else 0,
        "updatedAt": int(time.time() * 1000)
    }
    _write_json(STORAGE_FILE, obj)
    return obj

def online_update_platt(raw_score: float, label: int, opts: Dict = None) -> Dict:
    """
    Atualização online dos parâmetros Platt
    raw_score: número (0..100)
    label: 0 ou 1
    """
    opts = opts or {}
    lr = opts.get("lr", 0.05)
    
    def clip(v):
        return min(1e6, max(-1e6, v))
    
    prev = get_platt_params() or {"A": 0, "B": 0}
    A = float(prev.get("A", 0))
    B = float(prev.get("B", 0))
    
    x = float(raw_score) if raw_score else 0
    z = clip(A * x + B)
    p = 1 / (1 + pow(2.71828, -z))
    err = p - (1 if label else 0)
    
    # Gradientes
    gradA = err * x
    gradB = err * 1
    
    A = A - lr * gradA
    B = B - lr * gradB
    
    return set_platt_params(A, B)

def get_pattern_stat(key: str) -> Dict:
    """Obter estatísticas de um padrão"""
    s = _read_json(PATTERN_STATS_FILE) or {}
    return s.get(key, {"wins": 0, "losses": 0, "updatedAt": None})

def update_pattern_stat(key: str, hit: bool) -> Dict:
    """Atualizar estatísticas de um padrão"""
    s = _read_json(PATTERN_STATS_FILE) or {}
    cur = s.get(key, {"wins": 0, "losses": 0, "updatedAt": None})
    if hit:
        cur["wins"] = cur.get("wins", 0) + 1
    else:
        cur["losses"] = cur.get("losses", 0) + 1
    cur["updatedAt"] = int(time.time() * 1000)
    s[key] = cur
    _write_json(PATTERN_STATS_FILE, s)
    return cur

def getAll_pattern_stats() -> Dict:
    """Obter todas as estatísticas de padrões"""
    return _read_json(PATTERN_STATS_FILE) or {}

import time  # Import necessário

