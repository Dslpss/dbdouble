"""
Parser para resultados do Double
Equivalente ao parser.js
"""
from typing import Optional, Dict, List, Any

def parse_double_payload(payload: Any) -> Optional[Dict]:
    """
    Parse payload do Double (0-14)
    0 -> white, 1-7 -> red, 8-14 -> black
    """
    try:
        if not payload or not isinstance(payload, dict):
            return None
        
        # Tentar diferentes campos para o número
        value = (
            payload.get("value") or
            payload.get("number") or
            payload.get("n") or
            payload.get("roll") or
            payload.get("result")
        )
        
        if value is None:
            return None
        
        num = int(value)
        if not (0 <= num <= 14):
            return None
        
        # Determinar cor
        if num == 0:
            color = "white"
        elif num <= 7:
            color = "red"
        else:
            color = "black"
        
        return {
            "number": num,
            "color": color,
            "round_id": (
                payload.get("round_id") or
                payload.get("roundId") or
                payload.get("gameId") or
                f"round_{int(time.time() * 1000)}"
            ),
            "timestamp": payload.get("timestamp") or int(time.time() * 1000),
            "source": payload.get("source") or "playnabets",
            "raw": payload,
        }
    except Exception:
        return None

def summarize_results(results: List[Dict]) -> Dict[str, int]:
    """Resumir estatísticas dos resultados"""
    stats = {
        "red": 0,
        "black": 0,
        "white": 0,
        "odd": 0,
        "even": 0,
        "total": 0
    }
    
    for r in results:
        if not r:
            continue
        stats["total"] += 1
        color = r.get("color")
        if color in stats:
            stats[color] += 1
        
        num = r.get("number", 0)
        if num != 0:
            if num % 2 == 0:
                stats["even"] += 1
            else:
                stats["odd"] += 1
    
    return stats

def compute_streaks(results: List[Dict]) -> Dict:
    """Calcular sequências de cores"""
    out = {
        "current": {"color": None, "length": 0},
        "max": {"red": 0, "black": 0, "white": 0}
    }
    
    # Sequência atual (do mais recente)
    cur_color = None
    cur_len = 0
    for i in range(len(results) - 1, -1, -1):
        r = results[i]
        if not r:
            continue
        color = r.get("color")
        if cur_color is None:
            cur_color = color
            cur_len = 1
        elif color == cur_color:
            cur_len += 1
        else:
            break
    
    out["current"]["color"] = cur_color
    out["current"]["length"] = cur_len
    
    # Máxima sequência por cor
    tmp = 0
    last = None
    for r in results:
        if not r:
            continue
        color = r.get("color")
        if color == last:
            tmp += 1
        else:
            tmp = 1
            last = color
        
        if color in out["max"]:
            out["max"][color] = max(out["max"][color], tmp)
    
    return out

def detect_simple_patterns(results: List[Dict]) -> List[Dict]:
    """Detectar padrões simples"""
    patterns = []
    if len(results) < 3:
        return patterns
    
    last = results[-5:]
    
    # Triple repeat: três últimas da mesma cor
    c3 = [r.get("color") for r in last[-3:]]
    if len(c3) == 3 and all(c == c3[0] for c in c3):
        patterns.append({
            "key": "triple_repeat",
            "description": f"Trinca de {c3[0]} detectada",
            "risk": "medium"
        })
    
    # Red/Black balance: diferença > 4 nos últimos 20
    last20 = results[-20:]
    rr = sum(1 for r in last20 if r.get("color") == "red")
    bb = sum(1 for r in last20 if r.get("color") == "black")
    if abs(rr - bb) >= 5:
        dominant = "red" if rr > bb else "black"
        patterns.append({
            "key": "red_black_balance",
            "description": f"Desequilíbrio recente favorece {dominant}",
            "risk": "low"
        })
    
    return patterns

import time  # Import necessário para parse_double_payload

