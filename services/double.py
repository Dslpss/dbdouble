"""
Serviço de detecção de padrões para Double
Equivalente ao double.js
"""
from typing import List, Dict, Optional, Any
import random
import time
from config import CONFIG
from services.parser import summarize_results
from services.adaptive_calibration import get_platt_params, update_pattern_stat, online_update_platt
import uuid

# Cooldown de sinais
last_signal_timestamp = 0
signal_cooldown_active = False

def set_signal_cooldown(ts: Optional[float] = None):
    """Ativar cooldown de sinais"""
    global last_signal_timestamp, signal_cooldown_active
    last_signal_timestamp = ts or time.time() * 1000
    signal_cooldown_active = True

def clear_signal_cooldown():
    """Limpar cooldown"""
    global signal_cooldown_active, last_signal_timestamp
    signal_cooldown_active = False
    last_signal_timestamp = 0

def is_signal_cooldown_active() -> bool:
    """Verificar se cooldown está ativo"""
    global signal_cooldown_active, last_signal_timestamp
    if not signal_cooldown_active:
        return False
    elapsed = (time.time() * 1000) - last_signal_timestamp
    if elapsed >= CONFIG.COOLDOWN_MS:
        signal_cooldown_active = False
        return False
    return CONFIG.COOLDOWN_MS > 0

def build_double_stats(results: List[Dict]) -> Dict:
    """Construir estatísticas do Double"""
    stats = {
        "total": 0,
        "color": {"white": 0, "red": 0, "black": 0},
        "numbers": {}
    }
    
    for r in results:
        if not r:
            continue
        stats["total"] += 1
        color = r.get("color", "white")
        if color in stats["color"]:
            stats["color"][color] = stats["color"].get(color, 0) + 1
        
        num = r.get("number")
        if num is not None and isinstance(num, (int, float)):
            num = int(num)
            stats["numbers"][num] = stats["numbers"].get(num, 0) + 1
    
    return stats

def compute_double_signal_chance(advice: Dict, results: List[Dict]) -> int:
    """Calcular chance de acerto do sinal"""
    sample = results[-50:] if len(results) >= 50 else results
    s = build_double_stats(sample)
    total = s.get("total", 0)
    
    def pct(n, base):
        return round((n / total) * 100) if total >= 10 else base
    
    base = 0
    bonus = 0
    penalty = 0
    
    if advice.get("type") == "color":
        color = advice.get("color", "white")
        base_fallback = 7 if color == "white" else 47
        
        if color == "white":
            base = pct(s["color"].get("white", 0), base_fallback)
        else:
            non_white_total = s["color"].get("red", 0) + s["color"].get("black", 0)
            base = round((s["color"].get(color, 0) / non_white_total) * 100) if non_white_total >= 8 else base_fallback
        
        # Bônus por padrões
        key = advice.get("key")
        last5 = results[-5:] if len(results) >= 5 else results
        last5_colors = [r.get("color") for r in last5 if r.get("color")]
        whites_recent = sum(1 for c in last5_colors if c == "white")
        
        if key == "color_streak":
            # Comprimento da sequência
            len_seq = 0
            for i in range(len(results) - 1, -1, -1):
                c = results[i].get("color")
                if not c or c == "white":
                    break
                if c == color:
                    len_seq += 1
                else:
                    break
            bonus += min(12, 3 + round(len_seq * 1.5))
        
        elif key == "streak_break_opposite":
            opp = "black" if color == "red" else "red"
            opp_len = 0
            for i in range(len(results) - 1, -1, -1):
                c = results[i].get("color")
                if not c or c == "white":
                    break
                if c == opp:
                    opp_len += 1
                else:
                    break
            bonus += min(11, 3 + round(opp_len * 1.3))
        
        elif key == "triple_repeat":
            bonus += 6
        elif key == "red_black_balance":
            last20 = results[-CONFIG.IMBALANCE_WINDOW:] if len(results) >= CONFIG.IMBALANCE_WINDOW else results
            s20 = build_double_stats(last20)
            diff = abs(s20["color"].get("red", 0) - s20["color"].get("black", 0))
            bonus += min(10, 3 + diff * 1.2)
        elif key == "two_in_a_row_trend":
            last5_non_white = [r.get("color") for r in last5 if r.get("color") != "white"]
            support = sum(1 for c in last5_non_white if c == color)
            bonus += min(9, 3 + support * 1.2)
        elif key == "alternation_break":
            alt_window = results[-max(CONFIG.ALTERNATION_WINDOW, 4):]
            alt_colors = [r.get("color") for r in alt_window if r.get("color") != "white"]
            alt_len = len(alt_colors)
            bonus += min(8, 3 + int(alt_len / 1.5))
        elif key == "momentum_bias":
            last5_non_white = [r.get("color") for r in last5 if r.get("color") != "white"]
            support = sum(1 for c in last5_non_white if c == color)
            bonus += min(10, 4 + support * 1.2)
        elif key == "after_white_previous_color":
            last3 = [r.get("color") for r in results[-3:]]
            if len(last3) >= 2 and last3[-1] == "white":
                prev = last3[-2]
                if prev == color:
                    bonus += 7
        elif key == "hot_zone_last10":
            last10 = results[-10:]
            last10_non_white = [r.get("color") for r in last10 if r.get("color") != "white"]
            tally = {}
            for c in last10_non_white:
                tally[c] = tally.get(c, 0) + 1
            cnt = tally.get(color, 0)
            bonus += min(10, max(0, (cnt - 4) * 1.3))
        elif key == "last_single_continuity":
            bonus += 4
        elif key == "short_streak_3":
            bonus += 5
        elif key == "light_imbalance_10":
            last10_stats = build_double_stats(results[-10:])
            diff10 = abs(last10_stats["color"].get("red", 0) - last10_stats["color"].get("black", 0))
            bonus += min(7, 2 + diff10)
        elif key == "two_of_three":
            bonus += 4
        elif key == "streak_4":
            bonus += 6
        elif key == "streak_break_4plus":
            opp4 = "black" if color == "red" else "red"
            opp_len4 = 0
            for i in range(len(results) - 1, -1, -1):
                c = results[i].get("color")
                if not c or c == "white":
                    break
                if c == opp4:
                    opp_len4 += 1
                else:
                    break
            bonus += min(9, 3 + round(opp_len4 * 1.2))
        else:
            bonus += 2
        
        # Penalização por brancos recentes
        if whites_recent >= 1:
            penalty += 1
        if "white" in last5_colors[-2:]:
            penalty += 0.5
        
        # Bônus por proporção na janela 12
        last12 = results[-12:]
        last12_non_white = [r.get("color") for r in last12 if r.get("color") != "white"]
        if len(last12_non_white) >= 6:
            tally12 = {}
            for c in last12_non_white:
                tally12[c] = tally12.get(c, 0) + 1
            cnt12 = tally12.get(color, 0)
            pct12 = round((cnt12 / len(last12_non_white)) * 100)
            if pct12 >= 50:
                bonus += min(6, int((pct12 - 45) / 3))
    else:
        base = 10
    
    chance = round(base + bonus - penalty)
    return max(4, min(89, chance))

def detect_double_patterns(results: List[Dict]) -> List[Dict]:
    """Detectar padrões no Double"""
    patterns = []
    if not isinstance(results, list) or len(results) < 3:
        return patterns
    
    last10 = results[-10:]
    colors = [r.get("color") for r in last10 if r.get("color")]
    
    # 1) Sequência de mesma cor (5+)
    seq_len = 5
    if len(colors) >= seq_len:
        tail = colors[-seq_len:]
        if all(c == tail[0] for c in tail) and tail[0] != "white":
            patterns.append({
                "key": "color_streak",
                "description": f"Sequência de {tail[0]} detectada: {', '.join(tail)}",
                "risk": "medium",
                "targets": {"type": "color", "color": tail[0]}
            })
    
    # 1b) Contra-sequência após streak longo (6+)
    last_non_white = [r.get("color") for r in reversed(results) if r.get("color") and r.get("color") != "white"]
    if len(last_non_white) >= 6:
        len_seq = 1
        for i in range(1, len(last_non_white)):
            if last_non_white[i] == last_non_white[0]:
                len_seq += 1
            else:
                break
        if len_seq >= 6:
            streak_color = last_non_white[0]
            opp = "black" if streak_color == "red" else "red"
            patterns.append({
                "key": "streak_break_opposite",
                "description": f"Sequência longa de {streak_color} ({len_seq}). Quebra provável: {opp}.",
                "risk": "medium",
                "targets": {"type": "color", "color": opp}
            })
    
    # 2) Trinca exata (3 últimas iguais)
    last3 = [r.get("color") for r in results[-3:] if r.get("color")]
    if len(last3) == 3 and all(c == last3[0] for c in last3) and last3[0] != "white":
        opp = "black" if last3[0] == "red" else "red"
        patterns.append({
            "key": "triple_repeat",
            "description": f"Trinca de {last3[0]} detectada, sugerindo {opp}",
            "risk": "low",
            "targets": {"type": "color", "color": opp}
        })
    
    # 3) Desequilíbrio Red/Black nos últimos 20
    last20 = results[-CONFIG.IMBALANCE_WINDOW:]
    s20 = build_double_stats(last20)
    diff = abs(s20["color"].get("red", 0) - s20["color"].get("black", 0))
    if diff >= CONFIG.IMBALANCE_DIFF:
        dom = "red" if s20["color"].get("red", 0) > s20["color"].get("black", 0) else "black"
        patterns.append({
            "key": "red_black_balance",
            "description": f"Desequilíbrio recente favorece {dom} (Δ={diff})",
            "risk": "low",
            "targets": {"type": "color", "color": dom}
        })
    
    # 3b) Hot zone: 7+ de 10 últimos
    last10_non_white = [r.get("color") for r in results[-10:] if r.get("color") != "white"]
    if len(last10_non_white) >= 7:
        tally10 = {}
        for c in last10_non_white:
            tally10[c] = tally10.get(c, 0) + 1
        entries10 = sorted(tally10.items(), key=lambda x: x[1], reverse=True)
        if entries10 and entries10[0][1] >= 7:
            hot = entries10[0][0]
            patterns.append({
                "key": "hot_zone_last10",
                "description": f"Zona quente: {entries10[0][1]}/10 favorecem {hot}",
                "risk": "low",
                "targets": {"type": "color", "color": hot}
            })
    
    # 4) Alternância prolongada
    alt_window = results[-max(CONFIG.ALTERNATION_WINDOW, 4):]
    alt_colors = [r.get("color") for r in alt_window if r.get("color") != "white"]
    if len(alt_colors) >= CONFIG.ALTERNATION_WINDOW:
        last_alt = alt_colors[-CONFIG.ALTERNATION_WINDOW:]
        alternates = all(last_alt[i] != last_alt[i-1] for i in range(1, len(last_alt)))
        if alternates:
            suggest = last_alt[-1]
            patterns.append({
                "key": "alternation_break",
                "description": f"Alternância detectada: {', '.join(last_alt)}. Tendência de quebra em {suggest}.",
                "risk": "low",
                "targets": {"type": "color", "color": suggest}
            })
    
    # 5) Dupla sequência
    last2 = [r.get("color") for r in results[-2:] if r.get("color")]
    last3_colors = [r.get("color") for r in results[-3:] if r.get("color")]
    if (len(last2) == 2 and last2[0] == last2[1] and last2[0] != "white" and
        not (len(last3_colors) == 3 and all(c == last3_colors[0] for c in last3_colors))):
        patterns.append({
            "key": "two_in_a_row_trend",
            "description": f"Dupla de {last2[0]} detectada. Continuidade provável.",
            "risk": "medium",
            "targets": {"type": "color", "color": last2[0]}
        })
    
    # 6) Momentum: 4 de 5 últimos
    last5_colors = [r.get("color") for r in results[-5:] if r.get("color") != "white"]
    if len(last5_colors) >= 4:
        tally = {}
        for c in last5_colors:
            tally[c] = tally.get(c, 0) + 1
        entries = sorted(tally.items(), key=lambda x: x[1], reverse=True)
        if entries and entries[0][1] >= 4:
            dom = entries[0][0]
            patterns.append({
                "key": "momentum_bias",
                "description": f"Momentum favorece {dom} (4/5 recentes)",
                "risk": "low",
                "targets": {"type": "color", "color": dom}
            })
    
    # 7) Após Branco: retomar cor anterior
    last4 = [r.get("color") for r in results[-4:]]
    if len(last4) >= 2 and last4[-1] == "white":
        prev_color = last4[-2]
        if prev_color and prev_color != "white":
            patterns.append({
                "key": "after_white_previous_color",
                "description": f"Após branco, retomar {prev_color}",
                "risk": "low",
                "targets": {"type": "color", "color": prev_color}
            })
    
    # 8) Último resultado único: continuidade
    last1 = [r.get("color") for r in results[-1:] if r.get("color")]
    if len(last1) == 1 and last1[0] != "white":
        patterns.append({
            "key": "last_single_continuity",
            "description": f"Último foi {last1[0]}, continuidade provável",
            "risk": "low",
            "targets": {"type": "color", "color": last1[0]}
        })
    
    # 9) Sequência curta de 3
    if len(colors) >= 3:
        tail3 = colors[-3:]
        if all(c == tail3[0] for c in tail3) and tail3[0] != "white":
            patterns.append({
                "key": "short_streak_3",
                "description": f"Sequência curta de {tail3[0]}: {', '.join(tail3)}",
                "risk": "medium",
                "targets": {"type": "color", "color": tail3[0]}
            })
    
    # 10) Desequilíbrio leve nos últimos 10
    last10_stats = build_double_stats(results[-10:])
    diff10 = abs(last10_stats["color"].get("red", 0) - last10_stats["color"].get("black", 0))
    if diff10 >= 2 and last10_stats["total"] >= 8:
        dom10 = "red" if last10_stats["color"].get("red", 0) > last10_stats["color"].get("black", 0) else "black"
        patterns.append({
            "key": "light_imbalance_10",
            "description": f"Desequilíbrio leve nos últimos 10 favorece {dom10} (Δ={diff10})",
            "risk": "low",
            "targets": {"type": "color", "color": dom10}
        })
    
    # 11) Padrão de 2 em 3 últimos
    last3_non_white = [r.get("color") for r in results[-3:] if r.get("color") != "white"]
    if len(last3_non_white) >= 2:
        tally3 = {}
        for c in last3_non_white:
            tally3[c] = tally3.get(c, 0) + 1
        entries3 = sorted(tally3.items(), key=lambda x: x[1], reverse=True)
        if entries3 and entries3[0][1] >= 2:
            dom3 = entries3[0][0]
            patterns.append({
                "key": "two_of_three",
                "description": f"2 de 3 últimos são {dom3}",
                "risk": "low",
                "targets": {"type": "color", "color": dom3}
            })
    
    # 12) Sequência de 4
    if len(colors) >= 4:
        tail4 = colors[-4:]
        if all(c == tail4[0] for c in tail4) and tail4[0] != "white":
            patterns.append({
                "key": "streak_4",
                "description": f"Sequência de 4 {tail4[0]}: {', '.join(tail4)}",
                "risk": "medium",
                "targets": {"type": "color", "color": tail4[0]}
            })
    
    # 13) Contra-sequência após streak de 4+
    if len(last_non_white) >= 4:
        len4 = 1
        for i in range(1, len(last_non_white)):
            if last_non_white[i] == last_non_white[0]:
                len4 += 1
            else:
                break
        if 4 <= len4 < 6:
            streak_color4 = last_non_white[0]
            opp4 = "black" if streak_color4 == "red" else "red"
            patterns.append({
                "key": "streak_break_4plus",
                "description": f"Sequência de {len4} {streak_color4}. Quebra provável: {opp4}.",
                "risk": "medium",
                "targets": {"type": "color", "color": opp4}
            })
    
    return patterns

def choose_double_bet_signal(patterns: List[Dict], results: List[Dict], options: Dict = None) -> Optional[Dict]:
    """Escolher melhor sinal de aposta"""
    if not patterns or len(patterns) == 0:
        return None
    if is_signal_cooldown_active():
        return None
    
    options = options or {}
    last_key = options.get("lastKey")
    randomize_top_delta = options.get("randomizeTopDelta", CONFIG.RANDOMIZE_TOP_DELTA)
    preferred_color = options.get("preferredColor")
    
    candidates = []
    for p in patterns:
        if p.get("targets", {}).get("type") == "color" and p.get("targets", {}).get("color") != "white":
            candidates.append({
                "key": p.get("key"),
                "type": "color",
                "color": p.get("targets", {}).get("color"),
                "risk": p.get("risk")
            })
    
    if len(candidates) == 0:
        return None
    
    # Filtrar por cor preferida se especificada
    filtered = [c for c in candidates if c["color"] == preferred_color] if preferred_color else candidates
    base_list = filtered if len(filtered) > 0 else candidates
    
    # Consenso: quantos padrões favorecem cada cor
    color_tally = {}
    for c in candidates:
        color_tally[c["color"]] = color_tally.get(c["color"], 0) + 1
    
    # Calcular score para cada candidato
    scored = []
    for advice in base_list:
        chance = compute_double_signal_chance(advice, results)
        penalty_key = 4 if last_key and advice["key"] == last_key else 0
        risk_weight = 2 if advice["risk"] == "low" else (4 if advice["risk"] == "medium" else 7)
        
        this_count = color_tally.get(advice["color"], 0)
        opp_count = color_tally.get("black" if advice["color"] == "red" else "red", 0)
        consensus_boost = min(6, max(0, (this_count - 1) * 2))
        conflict_penalty = min(4, max(0, opp_count - this_count))
        
        score = chance + risk_weight - penalty_key + consensus_boost - conflict_penalty
        scored.append({"advice": advice, "chance": chance, "score": score})
    
    scored.sort(key=lambda x: x["score"], reverse=True)
    
    top_score = scored[0]["score"]
    near_top = [s for s in scored if top_score - s["score"] <= randomize_top_delta]
    pick = random.choice(near_top) if near_top else scored[0]
    
    selected_signal = pick["advice"].copy()
    confidence = max(5.5, min(9.8, (pick["chance"] / 100) * 10.5))
    selected_signal["confidence"] = round(confidence * 10) / 10
    selected_signal["_score"] = pick["score"]
    selected_signal["chance"] = pick["chance"]
    
    return selected_signal

def numbers_for_color(color: str) -> List[int]:
    """Retornar números para uma cor"""
    if color == "white":
        return [0]
    elif color == "red":
        return [1, 2, 3, 4, 5, 6, 7]
    elif color == "black":
        return [8, 9, 10, 11, 12, 13, 14]
    return []

def detect_best_double_signal(results: List[Dict], options: Dict = None) -> Optional[Dict]:
    """Detectar melhor sinal do Double"""
    options = options or {}
    
    # Qualidade mínima de amostra
    sample_stats = build_double_stats(results[-50:])
    if sample_stats.get("total", 0) < CONFIG.MIN_SAMPLE_TOTAL:
        return None
    
    patterns = detect_double_patterns(results)
    # Se a configuração exigir apenas um padrão para emitir sinal, respeitar
    if CONFIG.EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN:
        # Não emitir se não houver exatamente 1 padrão detectado
        if not patterns or len(patterns) != 1:
            print(f"[DBG] Ignorando sinal: EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN ativado e {len(patterns)} padrões detectados")
            return None

    # Filtrar por padrões habilitados (se flag estiver ativada)
    if CONFIG.EMIT_ON_ENABLED_PATTERNS_ONLY and CONFIG.ENABLED_PATTERNS:
        filtered_patterns = [p for p in patterns if p.get('key') in CONFIG.ENABLED_PATTERNS]
        if not filtered_patterns:
            # Nenhum padrão habilitado detectado
            print(f"[DBG] Ignorando sinal: Nenhum dos padrões detectados ({[p.get('key') for p in patterns]}) está na lista ENABLED_PATTERNS")
            return None
        patterns = filtered_patterns
    # Se a configuração exigir apenas um padrão para emitir sinal, respeitar
    if CONFIG.EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN:
        # Não emitir se não houver exatamente 1 padrão detectado
        if not patterns or len(patterns) != 1:
            return None
    if not patterns or len(patterns) == 0:
        return None
    
    last_key = options.get("lastKey")
    
    # Sinal composto: consenso de cor
    agree_colors = [p.get("targets", {}).get("color") for p in patterns
                    if p.get("targets", {}).get("type") == "color" and p.get("targets", {}).get("color") != "white"]
    
    preferred_color = None
    if len(agree_colors) >= CONFIG.COMPOSED_MIN_AGREE:
        tally = {}
        for c in agree_colors:
            tally[c] = tally.get(c, 0) + 1
        entries = sorted(tally.items(), key=lambda x: x[1], reverse=True)
        if entries and entries[0][1] >= CONFIG.COMPOSED_MIN_AGREE:
            preferred_color = entries[0][0]
    
    # Se a configuração exigir sinal apenas baseado no pattern (sem cálculo de score), então criamos o
    # sinal diretamente a partir do primeiro pattern detectado
    if CONFIG.EMIT_SIGNAL_BASED_ON_PATTERN_ONLY:
        # Selecionar o primeiro pattern (após filtros) como o gatilho
        p = patterns[0]
        advice = {
            "key": p.get("key"),
            "type": p.get("targets", {}).get("type", "color"),
            "color": p.get("targets", {}).get("color")
        }
        confidence_map = {"low": 6.5, "medium": 7.5, "high": 8.5}
        risk = p.get("risk", "medium")
        confidence = confidence_map.get(risk, 7.0)
        targets = numbers_for_color(advice["color"]) if advice.get("color") else []
        # Criar payload simples a partir do pattern
        description = p.get("description")
        reasons = [description]
        chance_pct = compute_double_signal_chance(advice, results)
    else:
        signal_advice = choose_double_bet_signal(patterns, results, {
            "lastKey": last_key,
            "preferredColor": preferred_color
        })

        if not signal_advice:
            return None

        confidence = signal_advice["confidence"]
        targets = numbers_for_color(signal_advice["color"])
    
    if not targets or len(targets) == 0:
        return None
    
    description_map = {
        "color_streak": "🔴⚫ Sequência de cor ativa!",
        "streak_break_opposite": "⛔ Contra-sequência após streak longo",
        "triple_repeat": "🔁 Trinca detectada! Aposte na cor oposta.",
        "red_black_balance": "📊 Tendência de cor! Uma cor dominando.",
        "hot_zone_last10": "🔥 Zona quente: 7/10 favorecem a cor",
        "two_in_a_row_trend": "➡️ Continuidade provável após dupla.",
        "alternation_break": "🔄 Alternância tende a quebrar; aposte na continuidade.",
        "momentum_bias": "📈 Momentum recente favorece a cor",
        "after_white_previous_color": "⚪ Após branco, retoma cor anterior",
        "last_single_continuity": "➡️ Continuidade simples do último resultado",
        "short_streak_3": "🔴⚫ Sequência curta de 3 detectada",
        "light_imbalance_10": "📊 Desequilíbrio leve nos últimos 10",
        "two_of_three": "📈 2 de 3 últimos favorecem a cor",
        "streak_4": "🔴⚫ Sequência de 4 cores detectada",
        "streak_break_4plus": "⛔ Quebra provável após sequência de 4+",
    }
    
    # Se foi usado pattern-only, usamos a descrição do pattern; caso contrário, use a description_map
    if CONFIG.EMIT_SIGNAL_BASED_ON_PATTERN_ONLY:
        description = p.get("description", "Padrão detectado")
        reasons = [description]
        signal_key = p.get("key")
        signal_color = advice.get("color") if advice else None
        signal_chance = chance_pct
    else:
        description = description_map.get(signal_advice["key"], "Padrão detectado")
        # Motivos (padrões que concordam)
        reasons_keys = [pp.get("key") for pp in patterns
                        if pp.get("targets", {}).get("type") == "color" and
                        pp.get("targets", {}).get("color") == signal_advice["color"]]
        reasons = [description_map.get(k, k) for k in reasons_keys]
        signal_key = signal_advice["key"]
        signal_color = signal_advice["color"]
        signal_chance = signal_advice.get("chance", 0)
    coverage = f"{len(targets)} números"
    expected_roi = "Alta recompensa" if len(targets) == 1 else "Recompensa moderada"
    
    # (motivos já preenchidos acima dependendo do modo)

    # Classificação de confiança (alta/média/baixa) e confluência
    def classify_confidence(conf_value: float) -> str:
        if conf_value >= 8.5:
            return "alta"
        if conf_value >= 7.0:
            return "media"
        return "baixa"

    conf_label = classify_confidence(confidence)
    confluencia_ativa = False
    if not CONFIG.EMIT_SIGNAL_BASED_ON_PATTERN_ONLY:
        try:
            confluencia_ativa = len(reasons_keys) >= 2
        except Exception:
            confluencia_ativa = False
    else:
        confluencia_ativa = False

    if confluencia_ativa and conf_label != "alta":
        conf_label = "alta"
        confidence = max(confidence, 8.5)

    def peso_por_confianca(label: str) -> int:
        return 3 if label == "alta" else (2 if label == "media" else 1)

    def gales_permitidos(label: str) -> int:
        return 2 if label == "alta" else (1 if label == "media" else 0)

    peso = peso_por_confianca(conf_label)
    gales = gales_permitidos(conf_label)

    # Ativar cooldown
    if CONFIG.COOLDOWN_MS > 0:
        set_signal_cooldown(time.time() * 1000)
    
    # Calibração de probabilidade
    stored = get_platt_params()
    calib = CONFIG.CALIBRATION
    slope = stored.get("A") if stored and isinstance(stored.get("A"), (int, float)) else calib.get("cal_slope", 0.09)
    intercept = stored.get("B") if stored and isinstance(stored.get("B"), (int, float)) else calib.get("cal_intercept", -4.5)
    
    chance_pct = signal_chance
    calibrated_probability = 1 / (1 + pow(2.71828, -(slope * chance_pct + intercept)))
    
    def get_signal_type(conf):
        if conf >= 8.5:
            return "STRONG_SIGNAL"
        elif conf >= 7.0:
            return "MEDIUM_SIGNAL"
        return "WEAK_SIGNAL"
    
    def get_signal_color(conf):
        if conf >= 8.5:
            return "#00ff00"
        elif conf >= 7.5:
            return "#90ee90"
        elif conf >= 7.0:
            return "#ffff00"
        return "#ffa500"
    
    # Informação sobre o resultado recente que disparou/precede o sinal
    last_result = results[-1] if results and len(results) > 0 else None
    after_number = int(last_result.get("number")) if last_result and last_result.get("number") is not None else None
    after_color = last_result.get("color") if last_result and last_result.get("color") else None

    # Texto sugerido em primeiro lugar no formato solicitado: "Após número X, aposte COR"
    if after_number is not None and signal_color:
        suggested_text = f"Após número {after_number}, aposte {signal_color.upper()}"
    else:
        # Fallback: listar números sugeridos
        suggested_text = f"Se sair qualquer um destes números ({', '.join(str(n) for n in targets)}), apostar {signal_color.upper()}"

    return {
        "id": str(uuid.uuid4()),
        "type": get_signal_type(confidence),
        "color": get_signal_color(confidence),
        "description": description,
        "patternKey": signal_key,
        "confidence": confidence,
        "confLabel": conf_label,
        "suggestedBet": {
            "type": "color",
            "color": signal_color,
            "numbers": targets,
            "coverage": coverage,
            "expectedRoi": expected_roi,
            "protect_white": True
        },
        "targets": targets,
        "reasons": reasons,
        "padroes_detectados": reasons_keys,
        "confluencia": confluencia_ativa,
        "isPremium": True if confluencia_ativa else False,
        "peso": peso,
        "gales_permitidos": gales,
        "validFor": 3,
        "historicalAccuracy": None,
        "isLearning": False,
        "timestamp": int(time.time() * 1000),
        "chance": chance_pct,
        "calibratedProbability": calibrated_probability,
        "calibratedScore": round(calibrated_probability * 1000) / 1000
        ,
        "afterNumber": after_number,
        "afterColor": after_color,
        "suggestedText": suggested_text
    }


