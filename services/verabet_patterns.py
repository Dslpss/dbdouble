"""
Sistema de detecção de padrões para VeraBet Double
Baseado no motor de padrões da PlayNaBet, otimizado para VeraBet

Representação: "V" = Vermelho (1-7), "P" = Preto (8-14), "B" = Branco (0)
"""

from typing import List, Optional, Dict, Tuple
import time


def last_n(historico: List[str], n: int) -> List[str]:
    """Retorna os últimos N elementos do histórico"""
    return historico[-n:] if len(historico) >= n else historico[:]


def all_equal(seq: List[str]) -> bool:
    """Verifica se todos elementos são iguais"""
    return len(seq) > 0 and all(x == seq[0] for x in seq)


def is_alternating(seq: List[str]) -> bool:
    """Verifica se a sequência alterna entre V e P (ignora B)"""
    if len(seq) < 3:
        return False
    for i in range(1, len(seq)):
        if seq[i] == seq[i - 1] or seq[i] == "B" or seq[i - 1] == "B":
            return False
    return True


def count_streak(historico: List[str], color: str) -> int:
    """Conta sequência consecutiva de uma cor no final do histórico"""
    streak = 0
    for i in range(len(historico) - 1, -1, -1):
        if historico[i] == color:
            streak += 1
        else:
            break
    return streak


class VeraBetPatternEngine:
    """
    Motor de detecção de padrões para VeraBet Double
    
    8 Padrões principais:
    1. Sequência de 5+ iguais → apostar na cor oposta (alto)
    2. Sequência de 3 iguais → apostar na cor oposta (médio)
    3. Alternância de 4+ rodadas → continuar alternando (médio)
    4. Padrão 2x2 (AA BB) → apostar na primeira cor (médio)
    5. Branco após sequência 3+ → apostar na cor oposta (baixo-médio)
    6. Branco após sequência 4+ → repetir a cor anterior (médio-alto)
    7. Sequência de 6+ pretos → apostar no vermelho (alto)
    8. Padrão espelho (A BB A) → apostar no B (médio)
    """
    
    def __init__(self):
        self.last_signal_time = 0
        self.cooldown_seconds = 30  # Cooldown entre sinais
        self.signals_emitted = 0
        self.last_pattern_id = None
    
    def can_emit_signal(self) -> bool:
        """Verifica se pode emitir um novo sinal baseado no cooldown"""
        now = time.time()
        return (now - self.last_signal_time) >= self.cooldown_seconds
    
    def mark_signal_emitted(self, pattern_id: int):
        """Marca que um sinal foi emitido"""
        self.last_signal_time = time.time()
        self.last_pattern_id = pattern_id
        self.signals_emitted += 1
    
    # --- Detectores de Padrões ---
    
    def detectar_padrao1(self, historico: List[str]) -> Tuple[bool, Optional[str], str, int]:
        """
        Padrão 1: Sequência de 5+ iguais
        Quando uma cor aparece 5 ou mais vezes consecutivas, sugere a cor oposta
        Confiança: ALTA (85%)
        """
        seq = last_n(historico, 5)
        if len(seq) == 5 and seq[0] in ("V", "P") and all_equal(seq):
            suggested = "P" if seq[0] == "V" else "V"
            return True, suggested, "alta", 85
        return False, None, "", 0
    
    def detectar_padrao2(self, historico: List[str]) -> Tuple[bool, Optional[str], str, int]:
        """
        Padrão 2: Sequência de 3 iguais
        Quando uma cor aparece 3 vezes consecutivas, sugere a cor oposta
        Confiança: MÉDIA (65%)
        """
        seq = last_n(historico, 3)
        if len(seq) == 3 and seq[0] in ("V", "P") and all_equal(seq):
            # Verificar se não é 5+ (que seria padrão 1)
            if len(historico) >= 5:
                seq5 = last_n(historico, 5)
                if all_equal(seq5) and seq5[0] in ("V", "P"):
                    return False, None, "", 0  # Deixar para padrão 1
            suggested = "P" if seq[0] == "V" else "V"
            return True, suggested, "media", 65
        return False, None, "", 0
    
    def detectar_padrao3(self, historico: List[str]) -> Tuple[bool, Optional[str], str, int]:
        """
        Padrão 3: Alternância
        Quando há 4 ou mais rodadas alternando entre V e P, continuar o padrão
        Confiança: MÉDIA (60%)
        """
        if len(historico) >= 4:
            last4 = last_n(historico, 4)
            if is_alternating(last4):
                next_expected = "V" if last4[-1] == "P" else "P"
                conf = 70 if len(historico) >= 5 and is_alternating(last_n(historico, 5)) else 60
                return True, next_expected, "media", conf
        return False, None, "", 0
    
    def detectar_padrao4(self, historico: List[str]) -> Tuple[bool, Optional[str], str, int]:
        """
        Padrão 4: Dupla (AA BB)
        Quando há padrão de 2 iguais seguidos de 2 opostos, sugere a primeira cor
        Confiança: MÉDIA (65%)
        """
        seq = last_n(historico, 4)
        if len(seq) == 4 and seq[0] in ("V", "P"):
            if seq[0] == seq[1] and seq[2] == seq[3] and seq[0] != seq[2]:
                return True, seq[0], "media", 65
        return False, None, "", 0
    
    def detectar_padrao5(self, historico: List[str]) -> Tuple[bool, Optional[str], str, int]:
        """
        Padrão 5: Branco como reset de tendência
        Após sequência de 3+ seguida de Branco, sugere a cor oposta à tendência
        Confiança: BAIXA-MÉDIA (55%)
        """
        if len(historico) < 4:
            return False, None, "", 0
        if historico[-1] == "B":
            if historico[-2] not in ("V", "P"):
                return False, None, "", 0
            run_color = historico[-2]
            run = 1
            for i in range(len(historico) - 2, -1, -1):
                if historico[i] == run_color:
                    run += 1
                else:
                    break
            if run >= 3:
                suggested = "P" if run_color == "V" else "V"
                return True, suggested, "baixa", 55
        return False, None, "", 0
    
    def detectar_padrao6(self, historico: List[str]) -> Tuple[bool, Optional[str], str, int]:
        """
        Padrão 6: Branco após sequência longa (4+)
        Quando Branco aparece após 4+ da mesma cor, sugere repetir a cor
        Confiança: MÉDIA-ALTA (75%)
        """
        if len(historico) < 5:
            return False, None, "", 0
        if historico[-1] == "B":
            block = historico[-5:-1]
            if len(block) == 4 and all(x == block[0] for x in block) and block[0] in ("V", "P"):
                return True, block[0], "alta", 75
        return False, None, "", 0
    
    def detectar_padrao7(self, historico: List[str]) -> Tuple[bool, Optional[str], str, int]:
        """
        Padrão 7: Sequência longa de uma cor (6+)
        Quando há 6 ou mais da mesma cor, sugere a cor oposta
        Confiança: ALTA (85%)
        """
        if len(historico) < 6:
            return False, None, "", 0
        
        # Verificar sequência de Preto
        streak_p = count_streak(historico, "P")
        if streak_p >= 6:
            return True, "V", "alta", 85
        
        # Verificar sequência de Vermelho
        streak_v = count_streak(historico, "V")
        if streak_v >= 6:
            return True, "P", "alta", 85
        
        return False, None, "", 0
    
    def detectar_padrao8(self, historico: List[str]) -> Tuple[bool, Optional[str], str, int]:
        """
        Padrão 8: Espelho (A BB A)
        Quando há padrão A-BB-A, sugere B
        Confiança: MÉDIA (60%)
        """
        seq = last_n(historico, 4)
        if len(seq) == 4 and seq[0] in ("V", "P"):
            if seq[0] != seq[1] and seq[1] == seq[2] and seq[3] == seq[0]:
                if seq[1] in ("V", "P"):
                    return True, seq[1], "media", 60
        return False, None, "", 0
    
    # --- Avaliação principal ---
    
    def avaliar_historico(self, historico: List[str]) -> Dict:
        """
        Avalia o histórico e retorna o melhor sinal detectado
        
        Returns:
            Dict com:
            - signal: bool - se há sinal
            - pattern_id: int - ID do padrão detectado
            - color: str - cor sugerida ('red' ou 'black')
            - confidence: str - nível de confiança
            - chance: int - probabilidade em %
            - description: str - descrição do sinal
            - candidates: List - todos os padrões detectados
        """
        if len(historico) < 3:
            return {"signal": False, "reason": "historico_insuficiente"}
        
        # Lista de detectores com prioridades
        detectores = [
            (7, self.detectar_padrao7, 105),  # Maior prioridade
            (1, self.detectar_padrao1, 100),
            (6, self.detectar_padrao6, 90),
            (2, self.detectar_padrao2, 80),
            (4, self.detectar_padrao4, 70),
            (8, self.detectar_padrao8, 60),
            (3, self.detectar_padrao3, 50),
            (5, self.detectar_padrao5, 40),
        ]
        
        matches = []
        for pid, detector, priority in detectores:
            detected, suggestion, conf, chance = detector(historico)
            if detected and suggestion:
                matches.append({
                    "pattern_id": pid,
                    "priority": priority,
                    "suggestion": suggestion,
                    "confidence": conf,
                    "chance": chance,
                })
        
        if not matches:
            return {"signal": False, "reason": "nenhum_padrao"}
        
        # Verificar cooldown
        if not self.can_emit_signal():
            return {"signal": False, "reason": "cooldown", "candidates": matches}
        
        # Ordenar por prioridade
        matches.sort(key=lambda x: x["priority"], reverse=True)
        chosen = matches[0]
        
        # Mapear sugestão para cor
        color_map = {"V": "red", "P": "black"}
        suggested_color = color_map.get(chosen["suggestion"])
        
        if not suggested_color:
            return {"signal": False, "reason": "cor_invalida"}
        
        # Descrição do sinal
        color_name = "Vermelho" if suggested_color == "red" else "Preto"
        descriptions = {
            1: f"Sequência de 5+ detectada → Aposte no {color_name}!",
            2: f"Trinca detectada → Aposte no {color_name}!",
            3: f"Alternância detectada → Aposte no {color_name}!",
            4: f"Padrão 2x2 detectado → Aposte no {color_name}!",
            5: f"Branco após sequência → Aposte no {color_name}!",
            6: f"Branco após 4+ → Aposte no {color_name}!",
            7: f"Sequência longa de 6+ → Aposte no {color_name}!",
            8: f"Padrão espelho → Aposte no {color_name}!",
        }
        
        return {
            "signal": True,
            "pattern_id": chosen["pattern_id"],
            "color": suggested_color,
            "suggestion": chosen["suggestion"],
            "confidence": chosen["confidence"],
            "chance": chosen["chance"],
            "description": descriptions.get(chosen["pattern_id"], f"Padrão {chosen['pattern_id']} → Aposte no {color_name}!"),
            "candidates": matches,
        }
    
    def gerar_sinal(self, historico: List[str]) -> Optional[Dict]:
        """
        Gera um sinal completo para envio ao frontend
        Retorna None se não houver sinal válido
        """
        result = self.avaliar_historico(historico)
        
        if not result.get("signal"):
            return None
        
        # Números para cada cor
        numbers_map = {
            "red": [1, 2, 3, 4, 5, 6, 7],
            "black": [8, 9, 10, 11, 12, 13, 14],
        }
        
        signal = {
            "id": f"vb_{int(time.time() * 1000)}",
            "color": result["color"],
            "description": result["description"],
            "patternKey": f"P{result['pattern_id']}",
            "confidence": result["confidence"],
            "confLabel": result["confidence"],
            "chance": result["chance"],
            "probability": f"{result['chance']}%",
            "targets": numbers_map.get(result["color"], []),
            "reasons": [f"VeraBet Padrão {result['pattern_id']}"],
            "maxAttempts": 3,
            "protect_white": True,
            "suggestedBet": {
                "color": result["color"],
                "numbers": numbers_map.get(result["color"], []),
                "protect_white": True
            }
        }
        
        # Marcar sinal como emitido
        self.mark_signal_emitted(result["pattern_id"])
        
        return signal


# Teste standalone
if __name__ == "__main__":
    engine = VeraBetPatternEngine()
    
    exemplos = {
        "5_vermelhos": ["V", "V", "V", "V", "V"],
        "3_pretos": ["V", "P", "P", "P"],
        "7_pretos": ["V", "P", "P", "P", "P", "P", "P", "P"],
        "alternancia": ["V", "P", "V", "P"],
        "dupla_2x2": ["V", "V", "P", "P"],
        "branco_reset": ["V", "V", "V", "B"],
        "branco_longo": ["P", "P", "P", "P", "B"],
        "espelho": ["V", "P", "P", "V"],
    }
    
    print("=== Teste VeraBet Pattern Engine ===\n")
    for nome, hist in exemplos.items():
        result = engine.avaliar_historico(hist)
        signal = "SIM" if result.get("signal") else "NÃO"
        print(f"{nome}: {hist}")
        print(f"  Sinal: {signal}")
        if result.get("signal"):
            print(f"  Padrão: P{result.get('pattern_id')}")
            print(f"  Cor: {result.get('color')}")
            print(f"  Chance: {result.get('chance')}%")
        print()
