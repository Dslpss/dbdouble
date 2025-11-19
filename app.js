// Configuração
// Em produção (quando servido pelo mesmo host), usar '' para chamadas relativas
const API_BASE_URL =
  window &&
  (window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1")
    ? "http://localhost:3001"
    : "";
let eventSource = null;
let results = [];
let stats = {
  total: 0,
  red: 0,
  black: 0,
  white: 0,
  currentStreak: { color: null, length: 0 },
};
let currentPendingSignalId = null;
// Lista de sinais pendentes para avaliação (cada sinal pode tentar até `maxAttempts` resultados)
let pendingSignals = [];
let signalJustResolved = false;
let currentActiveSignal = null;
let winCount = 0;
let lossCount = 0;
const resolvedSignalIds = new Set();
let lastWinTimestamp = null;
let lastLossTimestamp = null;
// Auto scroll behavior
const AUTO_SCROLL_ON_SIGNAL = true;
let lastScrolledSignalId = null;
// histórico curto de resoluções recentes para evitar dupla contagem (por cor/outcome)
let recentResolutions = []; // { id, color, outcome, ts }
const RESOLUTION_DEDUP_WINDOW_MS = 8000; // 8 segundos

// Inicialização
document.addEventListener("DOMContentLoaded", () => {
  initializeApp();
});

function initializeApp() {
  connectSSE();
  updateStats();
  // Mostrar estado inicial de busca
  setSearchingState();
  // Inicializar contadores de wins/losses no DOM
  const winsEl = document.getElementById("statWins");
  const lossesEl = document.getElementById("statLosses");
  if (winsEl) winsEl.textContent = String(winCount);
  if (lossesEl) lossesEl.textContent = String(lossCount);
}

// Conexão SSE
function connectSSE() {
  if (eventSource) {
    eventSource.close();
  }

  eventSource = new EventSource(`${API_BASE_URL}/events`);

  eventSource.addEventListener("status", (event) => {
    const data = JSON.parse(event.data);
    updateConnectionStatus(data.connected);
  });

  eventSource.addEventListener("double_result", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "double_result" && payload.data) {
      handleNewResult(payload.data);
    }
  });

  eventSource.addEventListener("signal", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "signal" && payload.data) {
      handleBackendSignal(payload.data);
    }
  });
  eventSource.addEventListener("bet_result", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "bet_result" && payload.data) {
      handleBetResult(payload.data);
    }
  });

  eventSource.addEventListener("ping", (event) => {
    // Heartbeat - manter conexão viva
    console.log("Ping recebido");
  });

  eventSource.onerror = (error) => {
    console.error("Erro SSE:", error);
    updateConnectionStatus(false);
    // Tentar reconectar após 3 segundos
    setTimeout(() => {
      if (eventSource.readyState === EventSource.CLOSED) {
        connectSSE();
      }
    }, 3000);
  };
}

// Atualizar status de conexão
function updateConnectionStatus(connected) {
  const statusDot = document.getElementById("statusDot");
  const statusText = document.getElementById("statusText");

  if (connected) {
    statusDot.className = "status-dot connected";
    statusText.textContent = "Conectado";
  } else {
    statusDot.className = "status-dot disconnected";
    statusText.textContent = "Desconectado";
  }
}

// Processar novo resultado
function handleNewResult(data) {
  // Adicionar resultado
  results.unshift(data);

  // Manter apenas últimos 50 resultados
  if (results.length > 50) {
    results = results.slice(0, 50);
  }

  // Atualizar estatísticas
  updateStats();

  // Atualizar interface
  renderResults();

  // Avaliar sinais pendentes com o novo resultado (faz primeiro para não sobrescrever o card)
  evaluatePendingSignals(data);

  // Verificar se há sinal (se o backend enviar)
  // Por enquanto, vamos detectar padrões localmente
  checkForSignals();
}

// Avalia sinais pendentes quando chega um novo resultado
function evaluatePendingSignals(newResult) {
  if (!pendingSignals || pendingSignals.length === 0) return;

  // Para cada sinal pendente, checar se o novo resultado resolve como win/loss
  pendingSignals.forEach((p) => {
    if (p.resolved) return;
    p.evaluatedRounds = (p.evaluatedRounds || 0) + 1;
    p.attemptsUsed = p.evaluatedRounds;

    if (
      (newResult && newResult.color === p.expectedColor) ||
      (p.protect_white && newResult.color === "white")
    ) {
      // Win
      p.resolved = true;
      updateHistoryWithOutcome(
        p.id,
        "win",
        p.attemptsUsed,
        Date.now(),
        p.expectedColor
      );
      showSignalResolutionOnCard("win", p.attemptsUsed);
      // proteger o card de ser sobrescrito imediatamente
      signalJustResolved = true;
      setTimeout(() => {
        signalJustResolved = false;
      }, 5000);
    } else if (p.evaluatedRounds >= p.maxAttempts) {
      // Loss
      p.resolved = true;
      updateHistoryWithOutcome(
        p.id,
        "loss",
        p.attemptsUsed,
        Date.now(),
        p.expectedColor
      );
      showSignalResolutionOnCard("loss", p.attemptsUsed);
      signalJustResolved = true;
      setTimeout(() => {
        signalJustResolved = false;
      }, 5000);
    }
  });

  // Remover sinais resolvidos da lista
  pendingSignals = pendingSignals.filter((p) => !p.resolved);

  // Atualizar indicador global de pendência (texto Tentativa X/3 ou esconder)
  updatePendingStatusUI();
}

// Atualiza o item do histórico e marca visualmente win/loss
function updateHistoryWithOutcome(
  signalUiId,
  outcome,
  attemptsUsed,
  resolvedAt = null,
  color = null
) {
  // Histórico foi removido da interface. Registrar resolução no console e atualizar estado.
  console.log(
    `Signal ${signalUiId} resolved as ${outcome.toUpperCase()} after ${attemptsUsed} attempt(s)`
  );
  // Atualizar contadores de win/loss sem duplicidade
  // Atualizar os contadores (tenta incrementar)
  updateWinLossCounts(outcome, signalUiId, resolvedAt, color);
  // registrar resolução recente para evitar double-counting em chamadas subsequentes
  try {
    registerResolution({
      id: signalUiId,
      color: color || null,
      outcome: outcome,
      ts: resolvedAt || Date.now(),
    });
  } catch (e) {}
  // Garantir que qualquer sinal pendente com esse id seja removido
  for (let p of pendingSignals) {
    if (p.id === signalUiId) {
      p.resolved = true;
      p.attemptsUsed = attemptsUsed;
    }
  }
  pendingSignals = pendingSignals.filter((p) => !p.resolved);
  updatePendingStatusUI();
}

// Atualiza o texto do elemento de pendência para mostrar 'Tentativa X/3'
function updatePendingStatusUI() {
  const pendingStatusEl = document.getElementById("signalPendingStatus");
  if (!pendingStatusEl) return;

  if (!pendingSignals || pendingSignals.length === 0) {
    pendingStatusEl.style.display = "none";
    return;
  }

  // Mostrar estado do sinal mais recente (último adicionado)
  const p = pendingSignals[pendingSignals.length - 1];
  // currentAttempt é o próximo resultado a ser avaliado (avaliadoRounds começa em 0)
  const currentAttempt = (p.evaluatedRounds || 0) + 1;
  const max = p.maxAttempts || 3;
  pendingStatusEl.style.display = "block";
  pendingStatusEl.textContent = `Tentativa ${currentAttempt}/${max}`;
}

// Atualiza elemento DOM com timestamp formatado para último win/loss
function formatTimestamp(ts) {
  if (!ts) return "-";
  try {
    return new Date(ts).toLocaleString();
  } catch (e) {
    return String(ts);
  }
}

function setLastTimeDom(kind, ts) {
  try {
    if (kind === "win") {
      const el = document.getElementById("lastWinTime");
      if (el) el.textContent = formatTimestamp(ts);
    } else {
      const el = document.getElementById("lastLossTime");
      if (el) el.textContent = formatTimestamp(ts);
    }
  } catch (e) {}
}

function registerResolution(entry) {
  try {
    const e = {
      id: entry.id || null,
      color: entry.color || null,
      outcome: (entry.outcome || "").toLowerCase(),
      ts: entry.ts || Date.now(),
    };
    recentResolutions.push(e);
    // prune
    const now = Date.now();
    recentResolutions = recentResolutions.filter(
      (r) => now - r.ts <= RESOLUTION_DEDUP_WINDOW_MS
    );
  } catch (e) {}
}

// Debug helpers: add counts manually from UI
// Debug functions removed to avoid UI debug buttons in production

// Atualiza contadores de wins e losses e o DOM, evitando duplicidade por signal id
function updateWinLossCounts(outcome, signalId, resolvedAt = null) {
  // Debug log para entender chamadas
  try {
    console.log(
      `[updateWinLossCounts] outcome=${outcome} signalId=${signalId}`
    );
  } catch (e) {}

  const outcomeNorm =
    typeof outcome === "string" ? outcome.toLowerCase() : String(outcome);
  const idKey = signalId ? String(signalId) : null;
  // If color was passed as 4th arg (legacy compatibility), capture it
  const color = arguments.length >= 4 ? arguments[3] : null;

  // Remove old entries
  const now = Date.now();
  recentResolutions = recentResolutions.filter(
    (r) => now - r.ts <= RESOLUTION_DEDUP_WINDOW_MS
  );

  // If we already recorded a recent resolution with same outcome+color, skip counting
  if (color) {
    const dup = recentResolutions.find(
      (r) =>
        r.outcome === outcomeNorm &&
        r.color === color &&
        now - r.ts <= RESOLUTION_DEDUP_WINDOW_MS
    );
    if (dup) {
      console.log(
        `[dedupe] Skipping duplicate count for ${outcomeNorm} color=${color}`
      );
      return;
    }
  }

  if (!idKey) {
    // sem id, incrementar mesmo assim
    if (outcomeNorm === "win") winCount++;
    else lossCount++;
  } else {
    if (resolvedSignalIds.has(idKey)) {
      console.log(
        `[updateWinLossCounts] Skipping: already counted id=${idKey}`
      );
      return; // já contado
    }
    resolvedSignalIds.add(idKey);
    if (outcomeNorm === "win") winCount++;
    else lossCount++;
  }

  // debug: log counts after increment
  try {
    console.log(
      `[updateWinLossCounts] counts: win=${winCount} loss=${lossCount}`
    );
  } catch (e) {}

  // Atualizar último timestamp de win/loss (usar resolvedAt se fornecido)
  const ts = resolvedAt || Date.now();
  try {
    if (outcomeNorm === "win") {
      lastWinTimestamp = ts;
      setLastTimeDom("win", ts);
    } else {
      lastLossTimestamp = ts;
      setLastTimeDom("loss", ts);
    }
  } catch (e) {}

  // Atualizar DOM
  const winsEl = document.getElementById("statWins");
  const lossesEl = document.getElementById("statLosses");
  if (winsEl) winsEl.textContent = String(winCount);
  if (lossesEl) lossesEl.textContent = String(lossCount);
}

// Mostra visualmente o resultado do sinal no card (WIN/LOSS)
function showSignalResolutionOnCard(outcome, attemptsUsed) {
  const pendingStatusEl = document.getElementById("signalPendingStatus");
  const badge = document.getElementById("signalBadge");
  const card = document.getElementById("signalCard");
  if (pendingStatusEl) {
    const text =
      outcome === "win"
        ? `✅ WIN (${attemptsUsed} tentativa(s))`
        : `❌ LOSS (${attemptsUsed} tentativa(s))`;
    pendingStatusEl.style.display = "block";
    pendingStatusEl.textContent = text;
  }
  if (badge) {
    badge.textContent = outcome === "win" ? "WIN" : "LOSS";
    // Aplicar classe visual (win/loss) ao badge
    badge.classList.remove("win", "loss");
    badge.classList.add(outcome === "win" ? "win" : "loss");
  }
  // Ajustar estilo do card para indicar win/loss (borda e sombra)
  try {
    if (card) {
      if (outcome === "win") {
        card.style.borderColor = "#00ff88";
        card.style.boxShadow = "0 0 30px #00ff8840";
      } else {
        card.style.borderColor = "#ff4444";
        card.style.boxShadow = "0 0 30px #ff444440";
      }
    }
  } catch (e) {}
  // Marcar sinal atual como resolvido e mantê-lo visível
  if (currentActiveSignal) {
    currentActiveSignal.resolved = true;
    currentActiveSignal.resolution = outcome;
    currentActiveSignal.attemptsUsed = attemptsUsed;
  }
}

// Limpar sinal atual da UI (opcional: chamar manualmente ou após timeout)
function clearCurrentSignal() {
  currentActiveSignal = null;
  // Restaurar estado de busca imediatamente
  setSearchingState();
}

// Atualizar estatísticas
function updateStats() {
  stats = {
    total: results.length,
    red: 0,
    black: 0,
    white: 0,
    currentStreak: { color: null, length: 0 },
  };

  // Contar cores
  results.forEach((result) => {
    const color = result.color;
    if (color === "red") stats.red++;
    else if (color === "black") stats.black++;
    else if (color === "white") stats.white++;
  });

  // Calcular sequência atual
  if (results.length > 0) {
    const lastColor = results[0].color;
    let streakLength = 1;

    for (let i = 1; i < results.length; i++) {
      if (results[i].color === lastColor) {
        streakLength++;
      } else {
        break;
      }
    }

    stats.currentStreak = {
      color: lastColor,
      length: streakLength,
    };
  }

  // Atualizar UI
  document.getElementById("statTotal").textContent = stats.total;
  document.getElementById("statRed").textContent = stats.red;
  document.getElementById("statBlack").textContent = stats.black;
  document.getElementById("statWhite").textContent = stats.white;

  const streakText =
    stats.currentStreak.length > 0
      ? `${stats.currentStreak.length}x ${getColorName(
          stats.currentStreak.color
        )}`
      : "-";
  document.getElementById("statStreak").textContent = streakText;
}

// Renderizar resultados
function renderResults() {
  const grid = document.getElementById("resultsGrid");
  grid.innerHTML = "";

  results.forEach((result, index) => {
    const item = document.createElement("div");
    item.className = `result-item ${result.color} ${index === 0 ? "new" : ""}`;

    item.innerHTML = `
            <div class="result-number">${result.number}</div>
            <div class="result-color">${getColorName(result.color)}</div>
        `;

    grid.appendChild(item);
  });

  // Remover classe 'new' após animação
  setTimeout(() => {
    const newItems = document.querySelectorAll(".result-item.new");
    newItems.forEach((item) => item.classList.remove("new"));
  }, 600);
}

// Exibe estado de busca enquanto o sistema procura por padrões
function setSearchingState() {
  // Se acabamos de resolver um sinal, não sobrescrever o card imediatamente
  if (signalJustResolved) return;
  // Se há sinais pendentes, não voltar ao estado de busca
  if (pendingSignals && pendingSignals.length > 0) return;
  // Se já existe um sinal ativo no card (mesmo que resolvido), não sobrescrever
  if (currentActiveSignal) return;
  const section = document.getElementById("signalSection");
  const badge = document.getElementById("signalBadge");
  const confidence = document.getElementById("signalConfidence");
  const description = document.getElementById("signalDescription");
  const betEl = document.getElementById("signalBet");
  const numbersEl = document.getElementById("signalNumbers");
  const probEl = document.getElementById("signalProbability");
  const reasonsEl = document.getElementById("signalReasons");
  const pendingStatusEl = document.getElementById("signalPendingStatus");
  const card = document.getElementById("signalCard");

  if (section) section.style.display = "block";
  if (badge) badge.textContent = "BUSCANDO";
  if (confidence) confidence.textContent = "";
  if (description) description.textContent = "Analisando padrões, aguarde!";
  if (betEl) betEl.textContent = "";
  if (numbersEl) numbersEl.textContent = "";
  if (probEl) probEl.textContent = "";
  if (reasonsEl) reasonsEl.innerHTML = "";
  // A sugestão numérica foi removida do card — nada a mostrar aqui
  if (pendingStatusEl) pendingStatusEl.style.display = "none";
  // Esconder quadrado de cor quando estiver buscando
  try {
    const colorSquareEl = document.getElementById("signalColorSquare");
    if (colorSquareEl) {
      colorSquareEl.style.display = "none";
      colorSquareEl.className = "color-square";
    }
  } catch (e) {}
  // Reset visual do badge/card (remover classes win/loss e estilos inline)
  try {
    if (badge) {
      badge.classList.remove("win", "loss");
    }
    if (card) {
      // limpar estilos inline para voltar ao CSS padrão
      card.style.borderColor = "";
      card.style.boxShadow = "";
    }
  } catch (e) {}
}

// Verificar sinais
function checkForSignals() {
  // Se houver sinais pendentes, não detectar novos sinais até resolução
  if (pendingSignals && pendingSignals.length > 0) {
    console.log(
      `Sinal suprimido: existem ${pendingSignals.length} pendentes, procurando pausada.`
    );
    // Atualizar UI de pendência caso necessário
    updatePendingStatusUI();
    return;
  }

  // Mostrar que estamos procurando por padrões
  setSearchingState();

  // detectSignal já exige pelo menos 3 resultados internamente
  const signal = detectSignal();
  if (signal) {
    displaySignal(signal);
  }
}

// Processar sinal do backend
function handleBackendSignal(signalData) {
  // Converter formato do backend para formato da interface
  // Suprimir sinais do backend quando houver sinais pendentes
  if (pendingSignals && pendingSignals.length > 0) {
    console.log(
      `[DBG] Sinal suprimido: existem ${pendingSignals.length} pendentes e BLOCK_SIGNALS_WHILE_PENDING=True`
    );
    return;
  }
  const signal = {
    type: signalData.type || "MEDIUM_SIGNAL",
    confidence: signalData.confidence || 7.0,
    description: signalData.description || "Padrão detectado",
    patternKey: signalData.patternKey || "unknown",
    suggestedBet: signalData.suggestedBet || {
      type: "color",
      color: "red",
      numbers: [],
      coverage: "0 números",
    },
    probability: signalData.calibratedProbability
      ? `${Math.round(signalData.calibratedProbability * 100)}%`
      : "~60%",
    reasons: signalData.reasons || [],
  };

  displaySignal(signal);
  // mark current signal as pending (if it has id)
  currentPendingSignalId = signalData.id || null;
  const pendingStatusEl = document.getElementById("signalPendingStatus");
  if (currentPendingSignalId && pendingStatusEl) {
    pendingStatusEl.style.display = "block";
  }
}

// Detectar sinal simples
function detectSignal() {
  if (results.length < 3) return null;

  const last3 = results.slice(0, 3);
  const colors = last3.map((r) => r.color);

  // Trinca detectada
  if (
    colors[0] === colors[1] &&
    colors[1] === colors[2] &&
    colors[0] !== "white"
  ) {
    const oppositeColor = colors[0] === "red" ? "black" : "red";
    const numbers = getNumbersForColor(oppositeColor);

    return {
      type: "MEDIUM_SIGNAL",
      confidence: 7.5,
      description: "🔁 Trinca detectada! Aposte na cor oposta.",
      patternKey: "triple_repeat",
      suggestedBet: {
        type: "color",
        color: oppositeColor,
        numbers: numbers,
        coverage: `${numbers.length} números`,
        protect_white: true,
      },
      probability: "~65%",
      reasons: ["Trinca de mesma cor detectada", "Tendência de reversão"],
    };
  }

  // Sequência de 4+
  if (
    stats.currentStreak.length >= 4 &&
    stats.currentStreak.color !== "white"
  ) {
    const oppositeColor = stats.currentStreak.color === "red" ? "black" : "red";
    const numbers = getNumbersForColor(oppositeColor);

    return {
      type: "STRONG_SIGNAL",
      confidence: 8.0,
      description: `⛔ Sequência de ${
        stats.currentStreak.length
      } ${getColorName(stats.currentStreak.color)}! Quebra provável.`,
      patternKey: "streak_break",
      suggestedBet: {
        type: "color",
        color: oppositeColor,
        numbers: numbers,
        coverage: `${numbers.length} números`,
        protect_white: true,
      },
      probability: "~70%",
      reasons: [
        `Sequência longa de ${stats.currentStreak.length}`,
        "Tendência de reversão após streak",
      ],
    };
  }

  // Desequilíbrio Red/Black
  const last10 = results.slice(0, 10);
  const redCount = last10.filter((r) => r.color === "red").length;
  const blackCount = last10.filter((r) => r.color === "black").length;

  if (Math.abs(redCount - blackCount) >= 4) {
    const dominantColor = redCount > blackCount ? "red" : "black";
    const oppositeColor = dominantColor === "red" ? "black" : "red";
    const numbers = getNumbersForColor(oppositeColor);

    return {
      type: "MEDIUM_SIGNAL",
      confidence: 7.0,
      description: `📊 Desequilíbrio detectado! ${getColorName(
        dominantColor
      )} dominando.`,
      patternKey: "red_black_balance",
      suggestedBet: {
        type: "color",
        color: oppositeColor,
        numbers: numbers,
        coverage: `${numbers.length} números`,
        protect_white: true,
      },
      probability: "~60%",
      reasons: ["Desequilíbrio nos últimos 10", "Tendência de correção"],
    };
  }

  return null;
}

// Exibir sinal
function displaySignal(signal) {
  const section = document.getElementById("signalSection");
  const card = document.getElementById("signalCard");

  // Ajustar cor do card baseado no tipo
  const colors = {
    STRONG_SIGNAL: "#00ff88",
    MEDIUM_SIGNAL: "#ffd700",
    WEAK_SIGNAL: "#ff8800",
  };

  card.style.borderColor = colors[signal.type] || "#00ff88";
  card.style.boxShadow = `0 0 30px ${colors[signal.type] || "#00ff88"}40`;

  document.getElementById("signalBadge").textContent = signal.type.replace(
    "_",
    " "
  );
  document.getElementById(
    "signalConfidence"
  ).textContent = `Confiança: ${signal.confidence}/10`;
  document.getElementById("signalDescription").textContent = signal.description;
  // Alteração: exibir sugestão no formato solicitado: "Após numero X aposte cor X" (ou 'Se sair ...')
  const betEl = document.getElementById("signalBet");
  // Construir sugestão com prioridade:
  // 1) se o backend enviar `afterNumber`, usar ele;
  // 2) senão, usar o último resultado local (`results[0]`);
  // 3) senão, fallback para formatSuggestionText ou apenas a cor.
  let finalSuggestion = "";
  const color =
    signal && signal.suggestedBet ? signal.suggestedBet.color : null;
  if (
    signal &&
    typeof signal.afterNumber !== "undefined" &&
    signal.afterNumber !== null &&
    color
  ) {
    finalSuggestion = `Depois do número ${
      signal.afterNumber
    }, jogar na cor ${getColorName(color).toUpperCase()}.`;
  } else {
    try {
      const latest = results && results.length > 0 ? results[0] : null;
      if (latest && typeof latest.number !== "undefined" && color) {
        finalSuggestion = `Depois do número ${
          latest.number
        }, jogar na cor ${getColorName(color).toUpperCase()}.`;
      }
    } catch (e) {
      // ignore
    }
  }

  if (!finalSuggestion || finalSuggestion.length === 0) {
    const suggestion = formatSuggestionText(signal);
    if (suggestion && suggestion.length > 0) {
      finalSuggestion = suggestion;
    } else if (signal && signal.suggestedBet && signal.suggestedBet.color) {
      finalSuggestion = `${getColorName(
        signal.suggestedBet.color
      ).toUpperCase()} (${signal.suggestedBet.coverage})`;
    }
  }

  if (betEl) betEl.textContent = finalSuggestion;
  // Atualizar quadrado de cor ao lado da sugestão (exibir red/black/white)
  try {
    const colorSquareEl = document.getElementById("signalColorSquare");
    const suggestedColor =
      signal && signal.suggestedBet ? signal.suggestedBet.color : null;
    if (colorSquareEl) {
      if (suggestedColor) {
        colorSquareEl.style.display = "inline-block";
        colorSquareEl.className = `color-square ${suggestedColor}`;
      } else {
        colorSquareEl.style.display = "none";
        colorSquareEl.className = "color-square";
      }
    }
  } catch (e) {
    // noop
  }
  document.getElementById("signalNumbers").textContent =
    signal.suggestedBet.numbers.join(", ");

  // Exibir aviso de "Cobrir o Branco" se o sinal sugerir
  const protectWhite = signal.suggestedBet && signal.suggestedBet.protect_white;
  const betGroup = document.querySelector(".signal-bet-group");

  // Remover badge anterior se existir
  const existingProtect = document.getElementById("protectWhiteBadge");
  if (existingProtect) existingProtect.remove();

  if (protectWhite) {
    const protectBadge = document.createElement("span");
    protectBadge.id = "protectWhiteBadge";
    protectBadge.className = "protect-white-badge";
    protectBadge.style.cssText =
      "display: inline-block; background-color: #fff; color: #333; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; margin-left: 8px; font-weight: bold; border: 1px solid #ccc;";
    protectBadge.innerHTML = "Cobrir Branco ⚪";
    if (betGroup) betGroup.appendChild(protectBadge);
  }

  // Tocar som de alerta
  try {
    const audio = document.getElementById("signalAlertSound");
    if (audio) {
      audio.currentTime = 0;
      audio
        .play()
        .catch((e) =>
          console.log("Audio play failed (user interaction needed first?):", e)
        );
    }
  } catch (e) {
    console.error("Error playing sound:", e);
  }

  document.getElementById("signalProbability").textContent = signal.probability;

  const reasonsEl = document.getElementById("signalReasons");
  reasonsEl.innerHTML =
    "<strong>Motivos:</strong><ul>" +
    signal.reasons.map((r) => `<li>${r}</li>`).join("") +
    "</ul>";

  section.style.display = "block";

  // Auto-scroll to the signal card so users see the alert immediately
  if (AUTO_SCROLL_ON_SIGNAL) {
    try {
      const cardEl = document.getElementById("signalCard");
      const uiId = signal._uiId || signal.id || null;
      if (cardEl && uiId && uiId !== lastScrolledSignalId) {
        lastScrolledSignalId = uiId;
        // scroll into view (center), then focus card for accessibility
        cardEl.scrollIntoView({ behavior: "smooth", block: "center" });
        // wait the scroll to finish before focusing
        setTimeout(() => {
          try {
            cardEl.focus({ preventScroll: true });
          } catch (e) {}
        }, 450);
      }
    } catch (e) {
      // noop
    }
  }

  // Adicionar ao histórico
  // Garantir um id para a UI — usado internamente para rastrear o sinal (não há histórico em DOM)
  const uiId =
    signal.id || `ui-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  signal._uiId = uiId;
  // Marcar sinal como atual na UI (será preservado até remoção manual ou nova atribuição)
  currentActiveSignal = signal;

  // Registrar sinal pendente para avaliação automática nas próximas rodadas
  try {
    const expectedColor = signal.suggestedBet
      ? signal.suggestedBet.color
      : null;
    if (expectedColor) {
      pendingSignals.push({
        id: uiId,
        expectedColor: expectedColor,
        evaluatedRounds: 0,
        maxAttempts: 3,
        resolved: false,
        attemptsUsed: 0,
        protect_white: signal.suggestedBet
          ? signal.suggestedBet.protect_white
          : false,
      });
      // Mostrar indicador de pendência
      updatePendingStatusUI();
    }
  } catch (e) {
    // noop
  }

  // Atualiza o texto do elemento de pendência para mostrar 'Tentativa X/3'
  // O UI updatePendingStatusUI foi movido para escopo global
  // Preencher ação sugerida (após número X apostar cor Y)
  // Sugestões baseadas em números foram removidas por decisão de UI.
}

// Histórico de sinais removido da interface. As funções que antes atualizavam o DOM
// agora apenas logam eventos para depuração e mantêm o estado interno.

// Processar resultado do martingale (win/loss) recebido via SSE
function handleBetResult(pb) {
  // Histórico removido: apenas logar resultado e limpar pendências correlatas
  const id = pb && pb.id ? pb.id : null;
  if (!id) return;
  const outcome = pb.result === "win" ? "WIN" : "LOSS";
  console.log(
    `Bet result for signal ${id}: ${outcome} (${pb.attemptsUsed} tentativa(s))`
  );

  // Se o resultado resolver um sinal pendente, marcar como resolvido internamente
  // Primeiro: marcar qualquer pendingSignal cujo id corresponda diretamente
  for (let p of pendingSignals) {
    if (p.id === id && !p.resolved) {
      p.resolved = true;
      p.attemptsUsed = pb.attemptsUsed || p.attemptsUsed;
    }
  }
  // Segundo: também proteger casos onde o backend usa um id diferente
  // (frontend criou um pending ui-... e backend criou pb_...):
  // se o pb inclui `color`, marcar quaisquer pendingSignals com same expectedColor
  // como resolvidos para evitar dupla contagem futura.
  try {
    const pbColor = pb.color || null;
    if (pbColor) {
      for (let p of pendingSignals) {
        if (!p.resolved && p.expectedColor === pbColor) {
          p.resolved = true;
          p.attemptsUsed = pb.attemptsUsed || p.attemptsUsed;
        }
      }
    }
  } catch (e) {}
  pendingSignals = pendingSignals.filter((p) => !p.resolved);
  updatePendingStatusUI();
  // Atualizar contadores/estado com base no resultado do backend
  updateHistoryWithOutcome(
    id,
    pb.result,
    pb.attemptsUsed || 0,
    pb.resolvedAt || null,
    pb.color || null
  );
}

// Format suggestion text for display
function formatSuggestionText(signal) {
  if (!signal || !signal.suggestedBet) return "";
  const nums = signal.suggestedBet.numbers || [];
  const color = signal.suggestedBet.color || null;
  if (!color) return "";

  // Priorizar valor enviado pelo backend (`afterNumber`) quando disponível
  if (
    typeof signal.afterNumber !== "undefined" &&
    signal.afterNumber !== null
  ) {
    return `Depois do número ${signal.afterNumber}, jogar na cor ${getColorName(
      color
    ).toUpperCase()}.`;
  }

  // Usar o resultado mais recente local como próxima opção
  try {
    const latest = results && results.length > 0 ? results[0] : null;
    if (latest && typeof latest.number !== "undefined") {
      return `Depois do número ${latest.number}, jogar na cor ${getColorName(
        color
      ).toUpperCase()}.`;
    }
  } catch (e) {
    // ignore and fallback
  }

  // Fallbacks antigos: se houver exatamente um número sugerido, use-o
  if (nums.length === 1) {
    return `Depois do número ${nums[0]}, jogar na cor ${getColorName(
      color
    ).toUpperCase()}.`;
  }

  // Caso não haja número recente ou único, apresentar apenas a cor
  return `Apostar na cor ${getColorName(color).toUpperCase()}.`;
}

// Funções auxiliares
function getColorName(color) {
  const names = {
    red: "Vermelho",
    black: "Preto",
    white: "Branco",
  };
  return names[color] || color;
}

function getNumbersForColor(color) {
  if (color === "red") {
    return [1, 2, 3, 4, 5, 6, 7];
  } else if (color === "black") {
    return [8, 9, 10, 11, 12, 13, 14];
  } else if (color === "white") {
    return [0];
  }
  return [];
}

// Verificar status do servidor periodicamente
setInterval(async () => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/status`);
    const data = await response.json();
    if (data.ok) {
      updateConnectionStatus(data.wsConnected);
    }
  } catch (error) {
    console.error("Erro ao verificar status:", error);
    updateConnectionStatus(false);
  }
}, 5000);
