import services.pattern_signals as ps


def test_padrao1_sequencia_long():
    engine = ps.SignalEngine()
    hist = ["V", "V", "V", "V", "V"]
    out = engine.avaliar_historico(hist, rodada_atual=len(hist))
    assert out.get("signal") is True
    assert out.get("pattern_id") == 1
    assert out.get("suggestion") == "P"


def test_padrao2_tres_seguidos():
    engine = ps.SignalEngine()
    hist = ["P", "P", "P"]
    out = engine.avaliar_historico(hist, rodada_atual=len(hist))
    assert out.get("signal") is True
    assert out.get("pattern_id") == 2
    assert out.get("suggestion") == "V"


def test_padrao3_alternancia():
    engine = ps.SignalEngine()
    hist = ["V", "P", "V", "P"]
    out = engine.avaliar_historico(hist, rodada_atual=len(hist))
    assert out.get("signal") is True
    assert out.get("pattern_id") == 3


def test_padrao4_dupla():
    engine = ps.SignalEngine()
    hist = ["V", "V", "P", "P"]
    out = engine.avaliar_historico(hist, rodada_atual=len(hist))
    assert out.get("signal") is True
    assert out.get("pattern_id") == 4


def test_padrao8_espelho():
    engine = ps.SignalEngine()
    hist = ["V", "P", "P", "V"]
    out = engine.avaliar_historico(hist, rodada_atual=len(hist))
    assert out.get("signal") is True
    assert out.get("pattern_id") == 8
