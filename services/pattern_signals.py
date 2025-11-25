"""
Módulo de detecção de padrões e geração de sinais para estudo/simulação.

Representação: "V" = Vermelho, "P" = Preto, "B" = Branco

Fornece uma classe `SignalEngine` que mantém estado (cooldown, stop, histórico
de sinais) e funções para detectar os 8 padrões descritos no prompt do usuário.

Este código é apenas para análise e simulação — não recomenda apostas reais.
"""

from typing import List, Optional, Dict, Tuple

# Configurações (ajustáveis)
X_WINDOW = 20
COOLDOWN_ROUNDS = 5
MAX_GALES = 2
STOP_AFTER_LOSSES = 3
STOP_DURATION = 10


def last_n(historico: List[str], n: int) -> List[str]:
    return historico[-n:] if len(historico) >= n else historico[:]


def all_equal(seq: List[str]) -> bool:
    return len(seq) > 0 and all(x == seq[0] for x in seq)


def is_alternating(seq: List[str]) -> bool:
    # Alternância ignorando Branco: exige que nenhuma rodada seja igual à anterior
    if len(seq) < 4:
        return False
    for i in range(1, len(seq)):
        if seq[i] == seq[i - 1] or seq[i] == "B" or seq[i - 1] == "B":
            return False
    return True


def confidence_rank(conf_str: str) -> int:
    if conf_str in ("alto", "medio-alto"):
        return 3
    if conf_str in ("medio", "baixo-medio"):
        return 2
    if conf_str == "baixo":
        return 1
    return 0


class SignalEngine:
    def __init__(self,
                 x_window: int = X_WINDOW,
                 cooldown: int = COOLDOWN_ROUNDS,
                 max_gales: int = MAX_GALES,
                 stop_after_losses: int = STOP_AFTER_LOSSES,
                 stop_duration: int = STOP_DURATION):
        self.x_window = x_window
        self.cooldown = cooldown
        self.max_gales = max_gales
        self.stop_after_losses = stop_after_losses
        self.stop_duration = stop_duration

        # Estado
        self.last_alert_round: int = -9999
        self.recent_signals: List[Dict] = []  # cada entrada: {round, pattern, result}
        self.stop_until_round: int = -1

    # --- Detectores dos 8 padrões ---
    def detectar_padrao1(self, historico: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        seq = last_n(historico, 5)
        if len(seq) == 5 and seq[0] in ("V", "P") and all_equal(seq):
            suggested = "P" if seq[0] == "V" else "V"
            return True, suggested, "alto"
        return False, None, None

    def detectar_padrao2(self, historico: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        seq = last_n(historico, 3)
        if len(seq) == 3 and seq[0] in ("V", "P") and all_equal(seq):
            suggested = "P" if seq[0] == "V" else "V"
            return True, suggested, "medio"
        return False, None, None

    def detectar_padrao3(self, historico: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        # Alternância: verificar 4 ou 5 rodadas alternadas
        if len(historico) >= 4:
            last4 = last_n(historico, 4)
            if is_alternating(last4):
                # próxima lógica: alternar a partir do último
                next_expected = "V" if last4[-1] == "P" else "P"
                # se 5 também alternam, aumentar confiança
                last5 = last_n(historico, 5)
                conf = "medio-alto" if len(last5) == 5 and is_alternating(last5) else "medio"
                return True, next_expected, conf
        return False, None, None

    def detectar_padrao4(self, historico: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        seq = last_n(historico, 4)
        if len(seq) == 4 and seq[0] in ("V", "P") and seq[0] == seq[1] and seq[2] == seq[3] and seq[0] != seq[2]:
            return True, seq[0], "medio"
        return False, None, None

    def detectar_padrao5(self, historico: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        # Branco como reset de tendência: tendência >=3 antes do B
        if len(historico) < 4:
            return False, None, None
        if historico[-1] == "B":
            # conta corrida da cor imediatamente antes do B
            if historico[-2] not in ("V", "P"):
                return False, None, None
            run_color = historico[-2]
            run = 1
            for i in range(len(historico) - 2, -1, -1):
                if historico[i] == run_color:
                    run += 1
                else:
                    break
            if run >= 3:
                suggested = "P" if run_color == "V" else "V"
                return True, suggested, "baixo-medio"
        return False, None, None

    def detectar_padrao6(self, historico: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        # Branco após sequência longa (>=4) -> repetir cor anterior
        if len(historico) < 5:
            return False, None, None
        if historico[-1] == "B":
            block = historico[-5:-1]
            if len(block) == 4 and all(x == block[0] for x in block) and block[0] in ("V", "P"):
                return True, block[0], "medio-alto"
        return False, None, None

    def detectar_padrao7(self, historico: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        return False, None, None

    def detectar_padrao8(self, historico: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        seq = last_n(historico, 4)
        if len(seq) == 4 and seq[0] in ("V", "P"):
            if seq[0] != seq[1] and seq[1] == seq[2] and seq[3] == seq[0]:
                if seq[1] in ("V", "P"):
                    return True, seq[1], "medio"
        return False, None, None

    # --- Avaliação do histórico e decisão ---
    def avaliar_historico(self, historico: List[str], rodada_atual: int) -> Dict:
        # verifica stop
        if rodada_atual <= self.stop_until_round:
            return {"signal": False, "reason": "stop_ativo"}
        # verifica cooldown
        if rodada_atual - self.last_alert_round < self.cooldown:
            return {"signal": False, "reason": "cooldown"}

        # Lista de padrões com prioridades (maior prioridade primeiro)
        padroes = [
            (1, self.detectar_padrao1, 100),
            (6, self.detectar_padrao6, 90),
            (2, self.detectar_padrao2, 80),
            (4, self.detectar_padrao4, 70),
            (8, self.detectar_padrao8, 60),
            (3, self.detectar_padrao3, 50),
            (5, self.detectar_padrao5, 40),
            (7, self.detectar_padrao7, 10),
        ]

        matches = []
        for pid, fn, prio in padroes:
            detected, suggestion, conf = fn(historico)
            if detected:
                matches.append({
                    "pattern_id": pid,
                    "priority": prio,
                    "suggestion": suggestion,
                    "confidence": conf,
                })

        if not matches:
            return {"signal": False, "reason": "nenhum_padrao"}

        # Ordena por prioridade e desempata por nível de confiança
        matches.sort(key=lambda x: (x["priority"], confidence_rank(x["confidence"])), reverse=True)
        chosen = matches[0]

        return {
            "signal": True,
            "pattern_id": chosen["pattern_id"],
            "suggestion": chosen["suggestion"],
            "confidence": chosen["confidence"],
            "candidates": matches,
        }

    def registrar_sinal(self, rodada_atual: int, pattern_id: int, result: str) -> None:
        # result deve ser "win" ou "loss"
        self.last_alert_round = rodada_atual
        self.recent_signals.append({"round": rodada_atual, "pattern": pattern_id, "result": result})
        # checar stop por perdas consecutivas
        recent = self.recent_signals[-self.stop_after_losses:]
        if len(recent) == self.stop_after_losses and all(r["result"] == "loss" for r in recent):
            self.stop_until_round = rodada_atual + self.stop_duration


if __name__ == "__main__":
    # Exemplos de uso e testes mínimos
    engine = SignalEngine()

    exemplos = {
        "sequencia_long_V": ["V", "V", "V", "V", "V"],
        "tres_P": ["P", "P", "P"],
        "alternancia": ["V", "P", "V", "P"],
        "dupla": ["V", "V", "P", "P"],
        "branco_reset": ["V", "V", "V", "B"],
        "branco_pos_seq": ["P", "P", "P", "P", "B"],
        "sem_branco_20": ["V" if i % 2 == 0 else "P" for i in range(20)],
        "espelho": ["V", "P", "P", "V"],
    }

    print("--- Teste de detectores: exemplos ---")
    for nome, hist in exemplos.items():
        out = engine.avaliar_historico(hist, rodada_atual=len(hist))
        print(f"{nome}: historico={hist} -> {out}")
