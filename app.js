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
// Histórico de resoluções de sinais para cálculo de sequências win/loss
let signalOutcomeHistory = []; // { outcome: 'win'|'loss', ts }
const RESOLUTION_DEDUP_WINDOW_MS = 8000; // 8 segundos

// Inicialização
// Ensure user is authenticated before loading the app. If user is not authenticated,
// redirect to /auth, otherwise continue with initialization.
async function ensureAuthenticated() {
  try {
    const path = window.location.pathname || "/";
    const token = localStorage.getItem("token");
    // If on auth page, and token exists and is valid, redirect to root
    if (path === "/auth") {
      if (!token) return; // stay on auth
      // validate token
      const resp = await fetch(`${API_BASE_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok) {
        // token valid, go to root
        window.location = "/";
      } else {
        // invalid token - clear
        localStorage.removeItem("token");
      }
      return;
    }
    // If not on auth page, we require token
    if (!token) {
      window.location = "/auth";
      return;
    }
    // validate token server-side
    const resp = await fetch(`${API_BASE_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp.ok) {
      localStorage.removeItem("token");
      window.location = "/auth";
      return;
    }
    // token ok - nothing to do
  } catch (e) {
    try {
      localStorage.removeItem("token");
    } catch (e) {}
    window.location = "/auth";
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  await ensureAuthenticated();
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

  // Mostrar informações do usuário se logado
  showUserInfo();
}

// Mostrar informações do usuário logado
async function showUserInfo() {
  const token = localStorage.getItem("token");
  if (!token) return;

  try {
    // Buscar informações do usuário
    const resp = await fetch(`${API_BASE_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (resp.ok) {
      const userData = await resp.json();

      // Buscar bankroll
      const bankResp = await fetch(`${API_BASE_URL}/api/auth/user/bankroll`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      let bankroll = 0;
      if (bankResp.ok) {
        const bankData = await bankResp.json();
        bankroll = bankData.bankroll || 0;
      }

      // Mostrar informações
      const userInfo = document.getElementById("userInfo");
      const userEmail = document.getElementById("userEmail");
      const userBankroll = document.getElementById("userBankroll");

      if (userInfo && userEmail && userBankroll) {
        userEmail.textContent = userData.email;
        userBankroll.textContent = `R$ ${bankroll.toFixed(2)}`;
        userInfo.style.display = "flex";

        // Mostrar botão admin se usuário for admin
        if (userData.is_admin) {
          const adminBtn = document.createElement("button");
          adminBtn.id = "btnAdmin";
          adminBtn.className = "admin-btn";
          adminBtn.textContent = "Admin";
          adminBtn.onclick = () => (window.location.href = "/admin");
          userInfo.appendChild(adminBtn);
        }
      }
    }
  } catch (error) {
    console.error("Erro ao buscar informações do usuário:", error);
  }
}

// Função de logout
async function logout() {
  try {
    // Chamar endpoint de logout para limpar cookie
    await fetch(`${API_BASE_URL}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
  } catch (error) {
    console.error("Erro no logout:", error);
  }

  // Limpar localStorage
  localStorage.removeItem("token");

  // Esconder informações do usuário
  const userInfo = document.getElementById("userInfo");
  if (userInfo) {
    userInfo.style.display = "none";
  }

  // Redirecionar para página de auth
  window.location.href = "/auth";
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
  // registrar também no histórico de resultados de sinal (para sequências win/loss)
  try {
    addSignalOutcome(outcome);
  } catch (e) {}
  // Atualizar o simulador martingale (agora com os dados do wins/losses)
  try {
    if (typeof updateMartingaleUI === "function") updateMartingaleUI();
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

function addSignalOutcome(outcome) {
  try {
    const o = (outcome || "").toLowerCase();
    if (o !== "win" && o !== "loss") return;
    signalOutcomeHistory.unshift({ outcome: o, ts: Date.now() });
    // manter histórico de 100 últimas resoluções
    if (signalOutcomeHistory.length > 100) {
      signalOutcomeHistory = signalOutcomeHistory.slice(0, 100);
    }
  } catch (e) {}
}

function getConsecutiveSignalLosses() {
  let count = 0;
  for (let i = 0; i < signalOutcomeHistory.length; i++) {
    if (signalOutcomeHistory[i].outcome === "loss") count++;
    else break; // parada ao encontrar um win
  }
  return count;
}

// Profit simulator UI updates
function formatCurrency(value) {
  try {
    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  } catch (e) {
    return String(value);
  }
}

function updateProfitCard() {
  const betEl = document.getElementById("profitBetAmount");
  const totalEl = document.getElementById("profitTotalBets");
  const winsEl = document.getElementById("profitWins");
  const lossesEl = document.getElementById("profitLosses");
  const netEl = document.getElementById("profitNet");
  const perBetEl = document.getElementById("profitPerBet");
  const roiEl = document.getElementById("profitROI");
  if (!betEl) return;
  const bet = parseFloat(betEl.value) || 0;
  const wins = winCount || 0;
  const losses = lossCount || 0;
  const total = wins + losses;
  const netProfit = (wins - losses) * bet; // payout 1:1
  const perBet = total > 0 ? netProfit / total : 0;
  const roi = total > 0 ? (netProfit / (total * bet)) * 100 : 0;
  if (totalEl) totalEl.textContent = String(total);
  if (winsEl) winsEl.textContent = String(wins);
  if (lossesEl) lossesEl.textContent = String(losses);
  if (netEl)
    netEl.textContent = bet === 0 ? "-" : `R$ ${formatCurrency(netProfit)}`;
  if (perBetEl)
    perBetEl.textContent = bet === 0 ? "-" : `R$ ${formatCurrency(perBet)}`;
  if (roiEl)
    roiEl.textContent =
      total === 0 || bet === 0 ? "-" : `${formatCurrency(roi)}%`;
  // Also refresh martingale UI if present
  try {
    if (typeof updateMartingaleUI === "function") updateMartingaleUI();
  } catch (e) {}
}

// MARTINGALE: calculate sequence, cumulative losses, next bet and capital needed
function calculateMartingaleSequence(initial, losses) {
  const n = Math.max(1, Math.floor(Number(losses) || 1));
  const inc = Number(initial) || 0;
  const seq = [];
  let cur = inc;
  for (let i = 0; i < n; i++) {
    seq.push(cur);
    cur = cur * 2;
  }
  return seq;
}

function calculateCumulativeLoss(initial, losses) {
  const seq = calculateMartingaleSequence(initial, losses);
  return seq.reduce((a, b) => a + b, 0);
}

function calculateNextBet(initial, losses) {
  const n = Math.max(1, Math.floor(Number(losses) || 1));
  const inc = Number(initial) || 0;
  return inc * Math.pow(2, n);
}

function calculateCapitalNeeded(initial, losses) {
  // capital needed includes the future next bet too
  const cumulative = calculateCumulativeLoss(initial, losses);
  const nextBet = calculateNextBet(initial, losses);
  return cumulative + nextBet;
}

// Ajusta a banca com base no outcome e attemptsUsed (Martingale)
async function adjustBankrollOnOutcome(outcome, attemptsUsed) {
  try {
    const betEl = document.getElementById("profitBetAmount");
    const bankEl = document.getElementById("profitBankroll");
    if (!betEl || !bankEl) return;
    const initial = Number(betEl.value) || 0;
    let bank = Number(bankEl.value) || 0;
    const oldBank = bank;
    // Normalizar outcome
    const out = (outcome || "").toLowerCase();
    if (out === "win") {
      // ganho padrão: recuperar perdas + lucro de 1x aposta inicial => adicionar initial
      bank = bank + initial;
    } else if (out === "loss") {
      const n = Math.max(1, Math.floor(Number(attemptsUsed) || 1));
      const losses = calculateCumulativeLoss(initial, n);
      bank = bank - losses;
    } else {
      return; // ignorar outcomes desconhecidos
    }
    // Atualizar DOM e persistir
    bankEl.value = Number(bank).toFixed(2);
    try {
      localStorage.setItem("profitBankroll", bankEl.value);
    } catch (e) {}
    const delta = Number(bank) - Number(oldBank);
    // if user is authenticated, sync with backend
    try {
      const token = localStorage.getItem("token");
      if (token) {
        const resp = await fetch(
          `${API_BASE_URL}/api/auth/user/bankroll/adjust`,
          {
            method: "POST",
            headers: {
              Authorization: `Bearer ${token}`,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ delta: delta }),
          }
        );
        if (resp.ok) {
          const data = await resp.json();
          if (data && data.bankroll !== undefined) {
            bankEl.value = Number(data.bankroll).toFixed(2);
            try {
              localStorage.setItem("profitBankroll", bankEl.value);
            } catch (e) {}
          }
        }
      }
    } catch (e) {}
    // Atualizar UI de martingale/coverage
    try {
      updateMartingaleUI();
    } catch (e) {}
    // highlight visual
    try {
      bankEl.classList.add("bank-changed");
      setTimeout(() => bankEl.classList.remove("bank-changed"), 800);
    } catch (e) {}
  } catch (e) {}
}

function updateMartingaleUI() {
  const betEl = document.getElementById("profitBetAmount");
  const streakEl = document.getElementById("martingaleStreak");
  const sequenceEl = document.getElementById("martingaleSequence");
  const cumulativeEl = document.getElementById("martingaleCumulativeLoss");
  const nextEl = document.getElementById("martingaleNextBet");
  const capitalEl = document.getElementById("martingaleCapitalNeeded");
  if (!betEl || !streakEl) return;
  const bet = Number(betEl.value) || 0;
  const useWL = document.getElementById("useWinsLosses");
  let losses = Math.max(1, Math.floor(Number(streakEl.value) || 1));
  if (useWL && useWL.checked) {
    // use consecutive signal losses (if any), else fallback to manual input
    const consecutive = getConsecutiveSignalLosses();
    if (consecutive > 0) {
      losses = consecutive;
    }
  }
  const seq = calculateMartingaleSequence(bet, losses);
  const seqText = seq.map((v) => `R$ ${formatCurrency(v)}`).join(" + ");
  const cumulative = calculateCumulativeLoss(bet, losses);
  const nextBet = calculateNextBet(bet, losses);
  const capitalNeeded = calculateCapitalNeeded(bet, losses);
  if (sequenceEl) sequenceEl.textContent = seqText === "" ? "-" : seqText;
  if (cumulativeEl)
    cumulativeEl.textContent = `R$ ${formatCurrency(cumulative)}`;
  if (nextEl) nextEl.textContent = `R$ ${formatCurrency(nextBet)}`;
  if (capitalEl) capitalEl.textContent = `R$ ${formatCurrency(capitalNeeded)}`;
  // Bankroll coverage
  const bankrollEl = document.getElementById("profitBankroll");
  const coverageEl = document.getElementById("martingaleCoverage");
  if (bankrollEl && coverageEl) {
    const bankroll = Number(bankrollEl.value) || 0;
    if (bankroll <= 0) {
      coverageEl.textContent = "Banca não informada";
      coverageEl.className = "bankroll-status";
    } else {
      const ratio = bankroll / capitalNeeded;
      const percent = Math.round(ratio * 100);
      coverageEl.textContent = `${percent}% cobertura`;
      coverageEl.className = `bankroll-status ${
        ratio >= 1 ? "bankroll-ok" : "bankroll-warning"
      }`;
    }
  }
  // exibir a contagem atual de perdas consecutivas de sinal
  try {
    const streakElDom = document.getElementById("currentSignalLossStreak");
    if (streakElDom)
      streakElDom.textContent = String(getConsecutiveSignalLosses());
  } catch (e) {}
}

// Bind event to bet input
document.addEventListener("DOMContentLoaded", () => {
  // Logout button
  const logoutBtn = document.getElementById("btnLogout");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", logout);
  }

  const betInput = document.getElementById("profitBetAmount");
  if (betInput) {
    betInput.addEventListener("input", () => updateProfitCard());
  }
  // initial update
  updateProfitCard();
  // bind martingale input if present
  const mgStreak = document.getElementById("martingaleStreak");
  if (mgStreak) {
    mgStreak.addEventListener("input", () => updateMartingaleUI());
    mgStreak.addEventListener("input", () => {
      try {
        localStorage.setItem("martingaleStreak", mgStreak.value);
      } catch (e) {}
    });
  }
  if (betInput) {
    betInput.addEventListener("input", () => updateMartingaleUI());
  }
  const bankrollInput = document.getElementById("profitBankroll");
  if (bankrollInput) {
    bankrollInput.addEventListener("input", () => updateMartingaleUI());
    bankrollInput.addEventListener("input", () => {
      try {
        localStorage.setItem("profitBankroll", bankrollInput.value);
      } catch (e) {}
    });
    bankrollInput.addEventListener("change", async () => {
      try {
        const token = localStorage.getItem("token");
        const val = Number(bankrollInput.value) || 0;
        if (token) {
          const resp = await fetch(`${API_BASE_URL}/api/auth/user/bankroll`, {
            method: "PUT",
            headers: {
              Authorization: `Bearer ${token}`,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ bankroll: val }),
          });
          if (resp.ok) {
            const data = await resp.json();
            if (data && data.bankroll !== undefined) {
              bankrollInput.value = Number(data.bankroll).toFixed(2);
              try {
                localStorage.setItem("profitBankroll", bankrollInput.value);
              } catch (e) {}
              try {
                updateMartingaleUI();
              } catch (e) {}
            }
          }
        }
      } catch (e) {}
    });
  }
  const useWL = document.getElementById("useWinsLosses");
  if (useWL) {
    useWL.addEventListener("input", () => updateMartingaleUI());
    useWL.addEventListener("input", () => {
      try {
        localStorage.setItem("useWinsLosses", useWL.checked ? "1" : "0");
      } catch (e) {}
    });
  }
  // initial martingale update
  updateMartingaleUI();
  // restore persisted inputs
  try {
    const savedBankroll = localStorage.getItem("profitBankroll");
    if (savedBankroll && bankrollInput) bankrollInput.value = savedBankroll;
    const savedStreak = localStorage.getItem("martingaleStreak");
    if (savedStreak && mgStreak) mgStreak.value = savedStreak;
    const savedUse = localStorage.getItem("useWinsLosses");
    if (savedUse && useWL) useWL.checked = savedUse === "1";
  } catch (e) {}
  // If user has token, attempt to fetch bankroll from server to sync
  try {
    const token = localStorage.getItem("token");
    const bankrollInputEl = document.getElementById("profitBankroll");
    if (token && bankrollInputEl) {
      fetch(`${API_BASE_URL}/api/auth/user/bankroll`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then((r) => r.json())
        .then((data) => {
          if (data && data.bankroll !== undefined) {
            bankrollInputEl.value = Number(data.bankroll).toFixed(2);
            try {
              localStorage.setItem("profitBankroll", bankrollInputEl.value);
            } catch (e) {}
            try {
              updateMartingaleUI();
            } catch (e) {}
          }
        })
        .catch((er) => {});
    }
  } catch (e) {}
});

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

  // Atualizar profit card caso esteja visível
  try {
    if (typeof updateProfitCard === "function") updateProfitCard();
  } catch (e) {}
  // Ajustar a banca com base no outcome / tentativas
  try {
    adjustBankrollOnOutcome(outcome, attemptsUsed);
  } catch (e) {}
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

// Configurações de Alertas
document.getElementById("btnSettings").addEventListener("click", () => {
  loadUserPreferences();
  document.getElementById("settingsModal").style.display = "block";
});

document.getElementById("closeSettings").addEventListener("click", () => {
  document.getElementById("settingsModal").style.display = "none";
});

document
  .getElementById("settingsForm")
  .addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveUserPreferences();
  });

async function loadUserPreferences() {
  try {
    const token = localStorage.getItem("token");
    const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const user = await response.json();

    document.getElementById("receiveAlerts").checked = user.receive_alerts;
    document.getElementById("colorRed").checked =
      user.enabled_colors.includes("red");
    document.getElementById("colorBlack").checked =
      user.enabled_colors.includes("black");
    document.getElementById("colorWhite").checked =
      user.enabled_colors.includes("white");
    document.getElementById("enabledPatterns").value =
      user.enabled_patterns.join(", ");
  } catch (error) {
    console.error("Erro ao carregar preferências:", error);
  }
}

async function saveUserPreferences() {
  try {
    const token = localStorage.getItem("token");
    const enabledColors = [];
    if (document.getElementById("colorRed").checked) enabledColors.push("red");
    if (document.getElementById("colorBlack").checked)
      enabledColors.push("black");
    if (document.getElementById("colorWhite").checked)
      enabledColors.push("white");

    const enabledPatterns = document
      .getElementById("enabledPatterns")
      .value.split(",")
      .map((p) => p.trim())
      .filter((p) => p.length > 0);

    const preferences = {
      receive_alerts: document.getElementById("receiveAlerts").checked,
      enabled_colors: enabledColors,
      enabled_patterns: enabledPatterns,
    };

    const response = await fetch(`${API_BASE_URL}/api/auth/preferences`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(preferences),
    });

    if (response.ok) {
      alert("Preferências salvas com sucesso!");
      document.getElementById("settingsModal").style.display = "none";
      // Reconnect SSE with new preferences
      connectSSE();
    } else {
      alert("Erro ao salvar preferências");
    }
  } catch (error) {
    console.error("Erro ao salvar preferências:", error);
    alert("Erro ao salvar preferências");
  }
}
