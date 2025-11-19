# DBcolor

Sistema de análise de padrões para Double (0-14) em Python.
Replicação do projeto doubleplay com arquitetura similar.

## Características

- 🎯 Detecção inteligente de padrões
- 📊 Análise estatística em tempo real
- 🔄 Calibração adaptativa (Platt scaling)
- 🌐 API REST com FastAPI
- 📡 Server-Sent Events (SSE) para resultados em tempo real
- 🔌 Conexão WebSocket com Play na Bets

## Pré-requisitos

- Python 3.11 ou superior
- pip (geralmente vem com o Python)

**Se o Python não estiver instalado:**

- Baixe de: https://www.python.org/downloads/
- **Importante:** Marque "Add Python to PATH" durante a instalação

## Instalação

1. Instale as dependências:

```bash
# Use python -m pip se pip não funcionar
python -m pip install -r requirements.txt

# Ou no Windows:
py -m pip install -r requirements.txt
```

2. (Opcional) Crie um ambiente virtual:

```bash
python -m venv venv
```

3. Ative o ambiente virtual:

- Windows (Git Bash): `source venv/Scripts/activate`
- Windows (CMD): `venv\Scripts\activate`
- Linux/Mac: `source venv/bin/activate`

4. Se usar ambiente virtual, instale as dependências novamente:

```bash
pip install -r requirements.txt
```

**Nota:** Se encontrar erros, consulte o arquivo `INSTALL.md` para mais detalhes.

## Execução

```bash
python main.py
```

Ou usando uvicorn diretamente:

```bash
uvicorn app:app --host 0.0.0.0 --port 3001 --reload
```

## Configuração

Configure a URL do WebSocket através de variável de ambiente:

```bash
export PLAYNABETS_WS_URL=wss://play.soline.bet:5903/Game
```

## Nova configuração: emissão somente para 1 padrão

Você pode controlar o comportamento do servidor para só emitir sinais quando exatamente um único padrão for detectado. Por padrão a opção está desativada (comportamento atual).

- Para ativar, defina a seguinte variável no `config.py` ou altere dinamicamente `CONFIG.EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN = True`:

```python
# Em config.py
EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN = True
```

Quando habilitado, o servidor ignorará os casos em que mais de um padrão é detectado simultaneamente e emitirá sinal somente se houver exatamente 1 padrão detectado.

### Filtrar por padrões permitidos

Você também pode configurar uma lista de padrões permitidos para que o servidor só emita alertas quando um desses padrões for detectado.
No `config.py`:

```python
# Habilitar filtro por lista de padrões
EMIT_ON_ENABLED_PATTERNS_ONLY = True
# Lista de padrões que devem disparar alerta (lista vazia = todos os padrões)
ENABLED_PATTERNS = ["triple_repeat", "color_streak", "hot_zone_last10"]
```

Combinação sugerida:

- Para enviar alertas apenas quando um padrão específico ocorrer, defina `EMIT_ON_ENABLED_PATTERNS_ONLY = True` e coloque apenas o padrão desejado em `ENABLED_PATTERNS`.
- Se quiser AND/OR comportamentos, combine com `EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN = True` para garantir que o alerta só venha quando houver exatamente 1 padrão detectado.

Ou crie um arquivo `.env`:

```
PLAYNABETS_WS_URL=wss://play.soline.bet:5903/Game
```

## Estrutura do Projeto

```
DBcolor/
├── app.py                    # Servidor FastAPI principal
├── main.py                   # Ponto de entrada
├── config.py                 # Configurações
├── requirements.txt          # Dependências
├── services/                 # Serviços
│   ├── __init__.py
│   ├── parser.py             # Parser de resultados
│   ├── double.py             # Detecção de padrões
│   ├── ws_client.py          # Cliente WebSocket
│   └── adaptive_calibration.py # Calibração adaptativa
└── README.md                 # Este arquivo
```

## Endpoints da API

- `GET /` - Informações do servidor
- `GET /api/status` - Status da conexão WebSocket
- `POST /api/connect` - Conectar ao WebSocket
- `GET /events` - Server-Sent Events para resultados em tempo real

## Padrões Detectados

O sistema detecta diversos padrões:

- Sequências de cores
- Trincas e contra-sequências
- Desequilíbrios Red/Black
- Zonas quentes
- Alternâncias
- Momentum
- E mais...

## Calibração Adaptativa

## Como abrir a interface no navegador

1. Inicie o servidor (veja seção Execução). Por exemplo:

```bash
python main.py
```

2. Abra o navegador e acesse:

```
http://localhost:3001/
```

3. Se nada aparecer (você ver JSON), tente reiniciar o servidor e limpar cache do navegador (Ctrl+F5). Se a página ainda não carregar, confira se algum serviço ocupa a porta 3001.

4. Para facilitar, use os scripts de inicialização:

- No Windows: execute `start.bat`
- No Git Bash / WSL / Linux / Mac: execute `./start.sh`

Se preferir rodar via uvicorn (desenvolvimento):

```bash
uvicorn app:app --host 0.0.0.0 --port 3001 --reload
```

### Emitir sinais apenas quando o pattern ocorre (sem predição)

Se deseja que o bot envie alertas APENAS quando um padrão específico ocorrer (sem tentar predizer resultados), ative a opção abaixo:

```python
# Em config.py
EMIT_SIGNAL_BASED_ON_PATTERN_ONLY = True
```

Opções avançadas combinadas:

- `EMIT_ON_ENABLED_PATTERNS_ONLY = True` e `ENABLED_PATTERNS = ['triple_repeat']` — só enviará se o padrão `triple_repeat` ocorrer.
- `EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN = True` — só envia quando **exatamente um** pattern for detectado.

Recomendações para o bot Telegram:

- Utilize os eventos SSE `signal` emitidos pelo servidor; configure seu bot para enviar mensagens ao Telegram somente quando receber um `signal` do backend.
- Para evitar ruído, combine `EMIT_SIGNAL_BASED_ON_PATTERN_ONLY = True` com `ENABLED_PATTERNS` contendo apenas os padrões que você considera relevantes.

## Martingale: verificação de resultado (win/loss)

O servidor agora suporta um modo para acompanhar sinais emitidos e verificar se a sugestão foi vencedora (win) ou perdida (loss).

- `MARTINGALE_ENABLED` (default True): habilita a verificação de resultado para sinais emitidos.
- `MARTINGALE_MAX_ATTEMPTS` (default 3): número máximo de resultados subsequentes a serem verificados para determinar win/loss.

- `BLOCK_SIGNALS_WHILE_PENDING` (default True): se True, o servidor não emitirá novos sinais enquanto houver uma pending bet (aposta pendente) sendo verificada. Isso garante que o bot não envie várias previsões simultâneas; primeiro aguarda a resolução do sinal atual.

Como funciona:

- Quando o servidor emite um `signal`, ele registra o sinal como uma _pending bet_ (aposta pendente).
- Em cada resultado subsequente, o servidor verifica se a cor sugerida no sinal ocorreu. Se sim, marca `win` e atualiza as estatísticas e calibração; se não, decrementa `attemptsLeft`.
- Se `attemptsLeft` alcançar 0 sem que a cor aconteça, marca `loss`, atualiza estatísticas e calibração.
- O servidor emite um SSE `bet_result` quando um pendente é resolvido (win ou loss). O `bet_result` inclui `patternKey`, `result` (`win`/`loss`), `attemptsUsed` e `chance`.

Recomendo o bot Telegram apenas enviar notificações/guia de ação quando um `signal` for emitido pelo backend. Para reduzir ruído, combine com `ENABLED_PATTERNS` e `EMIT_SIGNAL_BASED_ON_PATTERN_ONLY` ou com `EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN` dependendo da sua estratégia.

## UI: Ação Sugerida (após número Aposta)

O card de sinal na interface inclui agora uma linha de sugestão com uma frase no formato:

```
Sugestão: Após o número X, apostar COR
```

ou, quando a aposta abranger vários números:

```
Sugestão: Se sair qualquer um destes números (x, y, z), apostar COR
```

Isto é preenchido automaticamente a partir do campo `suggestedBet.numbers` e `suggestedBet.color` enviado pelo backend. Se nenhum número for configurado, esta linha ficará oculta.

O sistema usa Platt scaling para calibrar probabilidades baseado em histórico de acertos/erros.
Os parâmetros são salvos em `platt_params.json` e atualizados online.
