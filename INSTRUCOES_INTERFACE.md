# Instruções para Verificar a Interface

## Problema: Interface HTML não está aparecendo

## Solução Passo a Passo:

### 1. **PARE o servidor atual completamente**

- No terminal onde está rodando, pressione `Ctrl+C`
- Aguarde até ver a mensagem de que parou
- Se não parar, feche o terminal

### 2. **Verifique se os arquivos existem**

```bash
ls index.html styles.css app.js
```

Todos os 3 arquivos devem aparecer

### 3. **Reinicie o servidor**

```bash
# Usando Python diretamente (recomendado) - reinicia com reload
python main.py

# Ou com uvicorn (manual)
uvicorn app:app --host 0.0.0.0 --port 3001 --reload

# Alternativamente, use os scripts de conveniência criados:
# No Windows (PowerShell/CMD): start.bat
start.bat
# No Git Bash/WSL: start.sh
./start.sh
```

### 4. **Acesse no navegador**

- Abra: `http://localhost:3001/`
- **IMPORTANTE**: Limpe o cache do navegador (Ctrl+F5 ou Ctrl+Shift+R)
- Ou abra em uma janela anônima/privada

### 5. **Verifique o que aparece**

- ✅ **Se aparecer a interface HTML** (com cores, estatísticas, etc) = FUNCIONOU!
- ❌ **Se aparecer JSON** = O servidor ainda não foi reiniciado com o código novo

### 6. **Se ainda aparecer JSON:**

a) Verifique qual processo está usando a porta 3001:

```bash
# Windows PowerShell:
netstat -ano | findstr :3001
```

b) Mate o processo se necessário:

```bash
# Use o PID que apareceu no comando acima
taskkill /PID <numero_do_pid> /F
```

c) Reinicie o servidor novamente

### 7. **Teste direto no navegador:**

- Abra o DevTools (F12)
- Vá na aba Network
- Recarregue a página (F5)
- Clique na requisição para "/"
- Verifique o "Content-Type" na resposta
- Deve ser "text/html", não "application/json"

## Código Atualizado

O código foi atualizado para:

- ✅ Sempre retornar HTML quando o arquivo `index.html` existe
- ✅ Usar `HTMLResponse` para garantir tipo correto
- ✅ Ler o arquivo HTML diretamente

## Emissão de alertas somente para 1 padrão

Se desejar que o servidor só alerte quando exatamente **1 padrão** for detectado (ignorando casos em que múltiplos padrões são detectados), habilite a opção no `config.py`:

```python
EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN = True
```

Coloque `False` para manter o comportamento atual (emitir sinais também quando houver múltiplos padrões ou consenso entre padrões).

### Filtrar por padrões configurados

Se você quer que o bot envie alertas APENAS quando um padrão **específico** ocorrer, ative a filtragem de padrões no `config.py`:

```python
# Habilitar filtro por lista de padrões
EMIT_ON_ENABLED_PATTERNS_ONLY = True
# Lista de padrões que devem disparar alerta (lista vazia = todos os padrões)
ENABLED_PATTERNS = ["triple_repeat", "color_streak"]
```

Com isso, apenas os padrões listados em `ENABLED_PATTERNS` poderão disparar um alerta. Combine com `EMIT_SIGNAL_ONLY_IF_SINGLE_PATTERN = True` se desejar que o alerta só venha quando houver **exatamente um** padrão detectado.

### Emitir sinais apenas quando o pattern ocorre (sem predição)

Se você quer que o bot envie alertas APENAS quando um padrão aparece (sem nenhum cálculo preditivo), ative:

```python
EMIT_SIGNAL_BASED_ON_PATTERN_ONLY = True
```

Isso fará com que o servidor gere alertas baseados diretamente no pattern detectado, com mapeamentos simples de confiança/descrição a partir do pattern.

Para integrar com o bot do Telegram:

- Ouça os eventos SSE `signal` do backend e envie mensagens somente quando houver um `signal`.
- Ajuste `ENABLED_PATTERNS` para limitar os padrões que disparam mensagens.

## Verificação de sinal (Martingale)

O servidor verifica agora os sinais emitidos para decidir se houver win ou loss:

```python
MARTINGALE_ENABLED = True
MARTINGALE_MAX_ATTEMPTS = 3
```

A cada novo resultado recebido, o servidor verifica se a cor sugerida no `signal` ocorreu nos próximos `MARTINGALE_MAX_ATTEMPTS` resultados. Se ocorreu, marca `win` e emite `bet_result` via SSE; se não, marca `loss` após esgotar as tentativas e emite `bet_result`.

O `bet_result` é útil para o bot do Telegram para, por exemplo, reportar que a sugestão ganhou ou perdeu e registrar métricas de performance.

## Bloqueio de novos sinais enquanto há pendente

Por padrão, o servidor está configurado para não emitir novos sinais enquanto uma aposta anterior ainda estiver pendente (á espera do `bet_result`). Isso reduz ruído e evita sobreposição de sinais no bot Telegram.

Configuração:

```python
BLOCK_SIGNALS_WHILE_PENDING = True
```

## Se NADA funcionar:

Execute este comando para ver o que o servidor está retornando:

```bash
curl http://localhost:3001/ -H "Accept: text/html"
```

Ou abra o DevTools do navegador (F12) e veja a resposta da requisição.
