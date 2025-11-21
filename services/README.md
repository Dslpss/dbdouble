# Pattern Signals (SignalEngine)

Módulo `services/pattern_signals.py` implementa um motor simples de detecção de sinais baseado em 8 padrões descritos para análise/estudo do jogo Double.

Como funciona
- Classe `SignalEngine` com detectores `detectar_padrao1`..`detectar_padrao8`.
- Método `avaliar_historico(historico, rodada_atual)` retorna um dicionário com `signal` True/False, `pattern_id`, `suggestion` e `confidence`.
- Estado local com cooldown e stop por perdas: métodos `registrar_sinal` para atualizar o estado.

Como testar
1. Instale dependências (se necessário):
```bash
pip install -r requirements.txt
pip install pytest
```
2. Execute os testes:
```bash
pytest -q
```

Uso rápido
```python
from services.pattern_signals import SignalEngine
engine = SignalEngine()
hist = ["V","V","V","B"]
out = engine.avaliar_historico(hist, rodada_atual=len(hist))
print(out)
```

Observação
Este motor é para simulação e análise apenas. Não é recomendação de aposta.
