// VeraBet Double - Frontend JavaScript
// Versão simplificada do app.js para VeraBet

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

let pendingSignals = [];
let signalJustResolved = false;
let currentActiveSignal = null;
let winCount = 0;
let lossCount = 0;
let lastWinTimestamp = null;
let lastLossTimestamp = null;
let roundIndex = 0;

// Cooldown system
const COOLDOWN_BASIC = 4;
const COOLDOWN_AFTER_LOSS = 8;
const STOP_AFTER_3_LOSSES = 12;
const MIN_COOLDOWN_AFTER_WIN = 3;
const GLOBAL_WINDOW_ROUNDS = 30;
const GLOBAL_MAX_ALERTS = 4;
const SIGNAL_RESOLUTION_DISPLAY_MS = 5000;

let cooldown_contador = 0;
let perdas_consecutivas = 0;
let modo_stop = false;
let stop_counter = 0;
let modo_conservador = false;
let historico_alertas = [];

// Stats tracking
let currentWinStreak = 0;
let maxWinStreak = 0;
let consecutiveLossesCount = 0;
let lastConsecutiveLossTime = null;
// Configuração de tentativas do usuário (2 ou 3)
let userMaxAttempts = 3;

function decrementar_cooldown() {
  if (modo_stop) {
    stop_counter = Math.max(0, stop_counter - 1);
    if (stop_counter === 0) {
      modo_stop = false;
      perdas_consecutivas = 0;
    }
    return;
  }
  if (cooldown_contador > 0) {
    cooldown_contador = Math.max(0, cooldown_contador - 1);
  }
}

function ativar_cooldown(tipo) {
  if (tipo === "basico") {
    cooldown_contador = COOLDOWN_BASIC;
  } else if (tipo === "perda") {
    cooldown_contador = COOLDOWN_AFTER_LOSS;
    modo_conservador = true;
  } else if (tipo === "stop") {
    modo_stop = true;
    stop_counter = STOP_AFTER_3_LOSSES;
    cooldown_contador = 0;
  }
}

function registrar_resultado(acertou) {
  if (acertou) {
    cooldown_contador = Math.max(
      MIN_COOLDOWN_AFTER_WIN,
      Math.floor(cooldown_contador / 2)
    );
    perdas_consecutivas = 0;
    modo_conservador = false;
    currentWinStreak++;
    if (currentWinStreak > maxWinStreak) {
      maxWinStreak = currentWinStreak;
    }
  } else {
    perdas_consecutivas++;
    currentWinStreak = 0;
    ativar_cooldown("perda");
    if (perdas_consecutivas >= 3) {
      ativar_cooldown("stop");
    }
  }
  // Buscar dados atualizados do backend (inclui contagem correta de sequências)
  fetchUpdatedStats();
}

function updateWinStreakUI() {
  try {
    const currentEl = document.getElementById("currentWinStreak");
    const maxEl = document.getElementById("maxWinStreak");
    const lossCountEl = document.getElementById("consecutiveLosses");
    const lossTimeEl = document.getElementById("lastConsecutiveLossTime");
    if (currentEl) currentEl.textContent = String(currentWinStreak);
    if (maxEl) maxEl.textContent = String(maxWinStreak);
    if (lossCountEl) lossCountEl.textContent = String(consecutiveLossesCount);
    if (lossTimeEl) lossTimeEl.textContent = lastConsecutiveLossTime ? formatTimestamp(lastConsecutiveLossTime) : "-";
  } catch (e) {}
}

// Authentication
async function ensureAuthenticated() {
  try {
    const path = window.location.pathname || "/";
    const token = localStorage.getItem("token");
    
    if (path === "/auth") {
      if (!token) return;
      const resp = await fetch(`${API_BASE_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok) {
        window.location = "/verabet";
      } else {
        localStorage.removeItem("token");
      }
      return;
    }
    
    if (!token) {
      window.location = "/auth";
      return;
    }
    
    const resp = await fetch(`${API_BASE_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp.ok) {
      localStorage.removeItem("token");
      window.location = "/auth";
      return;
    }
  } catch (e) {
    try {
      localStorage.removeItem("token");
    } catch (e) {}
    window.location = "/auth";
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  await ensureAuthenticated();
  await initializeApp();
});

async function initializeApp() {
  // Buscar histórico inicial
  try {
    const resp = await fetch(`${API_BASE_URL}/verabet/api/results?limit=50`);
    const data = await resp.json();
    if (data && data.ok && Array.isArray(data.results)) {
      results = (data.results || []).reverse();
    }
  } catch (e) {
    console.error("Erro ao buscar histórico:", e);
  }
  
  // Buscar stats
  try {
    const sresp = await fetch(`${API_BASE_URL}/verabet/api/signal_stats`);
    const sdata = await sresp.json();
    if (sdata && sdata.ok) {
      winCount = parseInt(sdata.wins || 0);
      lossCount = parseInt(sdata.losses || 0);
      lastWinTimestamp = sdata.lastWinTime || null;
      lastLossTimestamp = sdata.lastLossTime || null;
      if (lastWinTimestamp) setLastTimeDom("win", lastWinTimestamp);
      if (lastLossTimestamp) setLastTimeDom("loss", lastLossTimestamp);
    }
  } catch (e) {}
  
  // Buscar win streaks
  try {
    const wresp = await fetch(`${API_BASE_URL}/verabet/api/win_streaks`);
    const wdata = await wresp.json();
    if (wdata && wdata.ok) {
      currentWinStreak = wdata.currentStreak || 0;
      maxWinStreak = wdata.maxStreak || 0;
      consecutiveLossesCount = wdata.consecutiveLossesCount || 0;
      lastConsecutiveLossTime = wdata.lastConsecutiveLossTime || null;
      updateWinStreakUI();
      
      const avgEl = document.getElementById("avgWinsBetweenLosses");
      if (avgEl) avgEl.textContent = (wdata.averageWinsBetweenLosses || 0).toFixed(2);
    }
  } catch (e) {}
  
  // Buscar dicas de padrões (melhor e pior)
  try {
    await loadPatternTips();
  } catch (e) {}
  
  // Iniciar verificação de cooldown
  try {
    checkCooldownStatus();
    setInterval(checkCooldownStatus, 5000); // Verificar a cada 5 segundos
  } catch (e) {}
  
  connectSSE();
  updateStats();
  renderResults();
  setSearchingState();
  
  // Atualizar contadores de wins/losses no DOM
  const winsEl = document.getElementById("statWins");
  const lossesEl = document.getElementById("statLosses");
  const winsPctEl = document.getElementById("statWinsPct");
  if (winsEl) winsEl.textContent = String(winCount);
  if (lossesEl) lossesEl.textContent = String(lossCount);
  if (winsPctEl) {
    const total = (winCount || 0) + (lossCount || 0);
    const pct = total > 0 ? Math.round((winCount / total) * 100) : 0;
    winsPctEl.textContent = `${pct}%`;
  }
  
  showUserInfo();
  
  // Carregar max_attempts do usuário
  try {
    const token = localStorage.getItem("token");
    if (token) {
      const meResp = await fetch(`${API_BASE_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (meResp.ok) {
        const meData = await meResp.json();
        userMaxAttempts = meData.max_attempts || 3;
        const maxAttemptsSelect = document.getElementById("maxAttempts");
        if (maxAttemptsSelect) maxAttemptsSelect.value = String(userMaxAttempts);
      }
    }
  } catch (e) {}
  
  // Handler para formulário de configurações
  try {
    const settingsForm = document.getElementById("settingsForm");
    if (settingsForm) {
      settingsForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const token = localStorage.getItem("token");
        if (!token) return;
        
        const enabledColors = [];
        if (document.getElementById("colorRed")?.checked) enabledColors.push("red");
        if (document.getElementById("colorBlack")?.checked) enabledColors.push("black");
        if (document.getElementById("colorWhite")?.checked) enabledColors.push("white");
        
        const receiveAlerts = document.getElementById("receiveAlerts")?.checked ?? true;
        const patternsInput = document.getElementById("enabledPatterns")?.value || "";
        const enabledPatterns = patternsInput.split(",").map(p => p.trim()).filter(p => p);
        const maxAttempts = parseInt(document.getElementById("maxAttempts")?.value) || 3;
        
        try {
          const resp = await fetch(`${API_BASE_URL}/api/auth/preferences`, {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({
              enabled_colors: enabledColors,
              enabled_patterns: enabledPatterns,
              receive_alerts: receiveAlerts,
              max_attempts: maxAttempts
            }),
          });
          
          if (resp.ok) {
            const data = await resp.json();
            userMaxAttempts = data.max_attempts || 3;
            alert("Configurações salvas com sucesso!");
            const settingsModal = document.getElementById("settingsModal");
            if (settingsModal) settingsModal.style.display = "none";
          } else {
            alert("Erro ao salvar configurações");
          }
        } catch (err) {
          console.error("Erro ao salvar preferências:", err);
          alert("Erro ao salvar configurações");
        }
      });
    }
  } catch (e) {}
  
  // Wire logout button
  try {
    const btnLogout = document.getElementById("btnLogout");
    if (btnLogout) {
      btnLogout.addEventListener("click", (e) => {
        e.preventDefault();
        logout();
      });
    }
  } catch (e) {}
  
  // Wire settings button
  try {
    const btnSettings = document.getElementById("btnSettings");
    const settingsModal = document.getElementById("settingsModal");
    const closeSettings = document.getElementById("closeSettings");
    
    if (btnSettings && settingsModal) {
      btnSettings.addEventListener("click", () => {
        settingsModal.style.display = "block";
      });
    }
    
    if (closeSettings && settingsModal) {
      closeSettings.addEventListener("click", () => {
        settingsModal.style.display = "none";
      });
    }
    
    window.addEventListener("click", (e) => {
      if (e.target === settingsModal) {
        settingsModal.style.display = "none";
      }
    });
  } catch (e) {}
  
  // Inicializar quadrado do header
  try {
    const headerSquare = document.getElementById("headerSquare");
    if (headerSquare) {
      headerSquare.classList.remove("black");
      headerSquare.title = "Estado: Vermelho (clique para alternar)";
      headerSquare.addEventListener("click", () => {
        headerSquare.classList.toggle("black");
        const isBlack = headerSquare.classList.contains("black");
        headerSquare.title = isBlack
          ? "Estado: Preto (clique para alternar)"
          : "Estado: Vermelho (clique para alternar)";
      });
    }
  } catch (e) {}
  
  // Botão de recarregar iframe
  try {
    const reloadBtn = document.getElementById("reloadGameBtn");
    const gameContainer = document.querySelector(".game-container");
    const iframe = document.getElementById("verabetIframe");
    if (reloadBtn && iframe) {
      reloadBtn.addEventListener("click", () => {
        if (gameContainer) gameContainer.classList.add("reloading");
        try {
          const src = iframe.getAttribute("src") || "";
          const sep = src.includes("?") ? "&" : "?";
          iframe.setAttribute("src", src + sep + "t=" + Date.now());
        } catch (e) {}
        setTimeout(() => {
          if (gameContainer) gameContainer.classList.remove("reloading");
        }, 1200);
      });
    }
  } catch (e) {}
  
  // Info modal
  try {
    const infoModal = document.getElementById("infoModal");
    const closeInfo = document.getElementById("closeInfoModal");
    const infoOkBtn = document.getElementById("infoOkBtn");
    const dontShow = document.getElementById("dontShowInfoAgain");
    const dismissed = localStorage.getItem("verabetInfoModalDismissed") === "true";
    if (infoModal && !dismissed) infoModal.style.display = "block";
    function hideInfoModal() {
      if (infoModal) infoModal.style.display = "none";
      if (dontShow && dontShow.checked)
        localStorage.setItem("verabetInfoModalDismissed", "true");
    }
    if (closeInfo) closeInfo.addEventListener("click", hideInfoModal);
    if (infoOkBtn) infoOkBtn.addEventListener("click", hideInfoModal);
    window.addEventListener("click", (event) => {
      if (event.target === infoModal) hideInfoModal();
    });
  } catch (e) {}
}

async function showUserInfo() {
  const token = localStorage.getItem("token");
  if (!token) return;
  
  try {
    const resp = await fetch(`${API_BASE_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    
    if (resp.ok) {
      const userData = await resp.json();
      const userInfo = document.getElementById("userInfo");
      const userEmail = document.getElementById("userEmail");
      
      if (userInfo && userEmail) {
        userEmail.textContent = userData.email;
        userInfo.style.display = "flex";
        
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
  } catch (e) {}
}

async function logout() {
  try {
    await fetch(`${API_BASE_URL}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
  } catch (e) {}
  localStorage.removeItem("token");
  window.location.href = "/auth";
}

// Verificar status do cooldown e atualizar banner
async function checkCooldownStatus() {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/cooldown_status?platform=verabet`);
    const data = await resp.json();
    
    const banner = document.getElementById("cooldownBanner");
    const timer = document.getElementById("cooldownTimer");
    
    if (!banner || !timer) return;
    
    if (data.ok && data.active) {
      // Cooldown ativo - mostrar banner
      banner.style.display = "block";
      
      const remainingSecs = data.remaining_secs;
      const mins = Math.floor(remainingSecs / 60);
      const secs = remainingSecs % 60;
      timer.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
      
      // Atualizar a cada segundo enquanto ativo
      if (!window.cooldownInterval) {
        window.cooldownInterval = setInterval(() => {
          const currentText = timer.textContent;
          const parts = currentText.split(':');
          if (parts.length === 2) {
            let m = parseInt(parts[0]) || 0;
            let s = parseInt(parts[1]) || 0;
            
            if (s > 0) {
              s--;
            } else if (m > 0) {
              m--;
              s = 59;
            } else {
              // Tempo acabou
              clearInterval(window.cooldownInterval);
              window.cooldownInterval = null;
              banner.style.display = "none";
              return;
            }
            
            timer.textContent = `${m}:${s.toString().padStart(2, '0')}`;
          }
        }, 1000);
      }
    } else {
      // Cooldown não ativo - esconder banner
      banner.style.display = "none";
      if (window.cooldownInterval) {
        clearInterval(window.cooldownInterval);
        window.cooldownInterval = null;
      }
    }
  } catch (e) {
    console.error("Erro ao verificar cooldown:", e);
  }
}

// SSE Connection
function connectSSE() {
  if (eventSource) {
    eventSource.close();
  }
  
  eventSource = new EventSource(`${API_BASE_URL}/verabet/events`);
  
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
  
  eventSource.addEventListener("ping", () => {
    console.log("Ping recebido");
  });
  
  eventSource.onerror = (error) => {
    console.error("Erro SSE:", error);
    updateConnectionStatus(false);
    setTimeout(() => {
      if (eventSource.readyState === EventSource.CLOSED) {
        connectSSE();
      }
    }, 3000);
  };
}

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

function handleNewResult(data) {
  roundIndex++;
  decrementar_cooldown();
  
  results.unshift(data);
  if (results.length > 50) {
    results = results.slice(0, 50);
  }
  
  updateStats();
  renderResults();
  evaluatePendingSignals(data);
}

function evaluatePendingSignals(newResult) {
  // Apenas atualizar UI de tentativas - backend faz a avaliação real e envia bet_result
  if (!pendingSignals || pendingSignals.length === 0) return;
  
  pendingSignals.forEach((p) => {
    if (p.resolved) return;
    // Incrementar contador de tentativas para display (backend controla resolução)
    p.evaluatedRounds = (p.evaluatedRounds || 0) + 1;
    p.attemptsUsed = p.evaluatedRounds;
  });
  
  // NÃO resolver aqui - esperar bet_result do backend para evitar dupla contagem
  updatePendingStatusUI();
}

function updateHistoryWithOutcome(signalUiId, outcome, attemptsUsed, resolvedAt, color) {
  console.log(`Signal ${signalUiId} resolved as ${outcome.toUpperCase()} after ${attemptsUsed} attempt(s)`);
  // Não incrementar localmente - buscar valores atualizados do backend
  fetchUpdatedStats();
}

async function fetchUpdatedStats() {
  // Buscar stats atualizados do backend para evitar dupla contagem
  try {
    const sresp = await fetch(`${API_BASE_URL}/verabet/api/signal_stats`);
    const sdata = await sresp.json();
    if (sdata && sdata.ok) {
      winCount = parseInt(sdata.wins || 0);
      lossCount = parseInt(sdata.losses || 0);
      lastWinTimestamp = sdata.lastWinTime || null;
      lastLossTimestamp = sdata.lastLossTime || null;
      if (lastWinTimestamp) setLastTimeDom("win", lastWinTimestamp);
      if (lastLossTimestamp) setLastTimeDom("loss", lastLossTimestamp);
      
      // Atualizar DOM
      const winsEl = document.getElementById("statWins");
      const lossesEl = document.getElementById("statLosses");
      const winsPctEl = document.getElementById("statWinsPct");
      if (winsEl) winsEl.textContent = String(winCount);
      if (lossesEl) lossesEl.textContent = String(lossCount);
      if (winsPctEl) {
        const total = (winCount || 0) + (lossCount || 0);
        const pct = total > 0 ? Math.round((winCount / total) * 100) : 0;
        winsPctEl.textContent = `${pct}%`;
      }
    }
  } catch (e) {
    console.error("Erro ao buscar stats atualizados:", e);
  }
  
  // Buscar win streaks atualizados
  try {
    const wresp = await fetch(`${API_BASE_URL}/verabet/api/win_streaks`);
    const wdata = await wresp.json();
    if (wdata && wdata.ok) {
      currentWinStreak = wdata.currentStreak || 0;
      maxWinStreak = wdata.maxStreak || 0;
      consecutiveLossesCount = wdata.consecutiveLossesCount || 0;
      lastConsecutiveLossTime = wdata.lastConsecutiveLossTime || null;
      updateWinStreakUI();
      
      const avgEl = document.getElementById("avgWinsBetweenLosses");
      if (avgEl) avgEl.textContent = (wdata.averageWinsBetweenLosses || 0).toFixed(2);
    }
  } catch (e) {
    console.error("Erro ao buscar win streaks atualizados:", e);
  }
}

function updatePendingStatusUI() {
  const pendingStatusEl = document.getElementById("signalPendingStatus");
  if (!pendingStatusEl) return;
  
  if (!pendingSignals || pendingSignals.length === 0) {
    pendingStatusEl.style.display = "none";
    return;
  }
  
  const p = pendingSignals[pendingSignals.length - 1];
  const max = userMaxAttempts || 3;  // Usa configuração do usuário
  const currentAttempt = Math.min((p.evaluatedRounds || 0) + 1, max);  // Limitar ao máximo
  pendingStatusEl.style.display = "block";
  pendingStatusEl.textContent = `Tentativa ${currentAttempt}/${max}`;
}

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

// Função para carregar dicas de padrões (melhor e pior taxa de acerto)
async function loadPatternTips() {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/stats/pattern-tips?platform=verabet&days=7&min_signals=3`);
    const data = await resp.json();
    
    if (data && data.ok) {
      // Melhor padrão
      const bestNameEl = document.getElementById("bestPatternName");
      const bestRateEl = document.getElementById("bestPatternRate");
      const bestTotalEl = document.getElementById("bestPatternTotal");
      
      if (data.best) {
        if (bestNameEl) bestNameEl.textContent = data.best.pattern;
        if (bestRateEl) bestRateEl.textContent = data.best.rate;
        if (bestTotalEl) bestTotalEl.textContent = data.best.total;
      } else {
        if (bestNameEl) bestNameEl.textContent = "Aguardando dados";
        if (bestRateEl) bestRateEl.textContent = "-";
        if (bestTotalEl) bestTotalEl.textContent = "-";
      }
      
      // Pior padrão
      const worstNameEl = document.getElementById("worstPatternName");
      const worstRateEl = document.getElementById("worstPatternRate");
      const worstTotalEl = document.getElementById("worstPatternTotal");
      
      if (data.worst) {
        if (worstNameEl) worstNameEl.textContent = data.worst.pattern;
        if (worstRateEl) worstRateEl.textContent = data.worst.rate;
        if (worstTotalEl) worstTotalEl.textContent = data.worst.total;
      } else {
        if (worstNameEl) worstNameEl.textContent = "Aguardando dados";
        if (worstRateEl) worstRateEl.textContent = "-";
        if (worstTotalEl) worstTotalEl.textContent = "-";
      }
    }
  } catch (e) {
    console.error("Erro ao carregar dicas de padrões:", e);
  }
}

function updateWinLossCounts(outcome, signalUiId, resolvedAt, color) {
  const now = resolvedAt || Date.now();
  
  if (outcome === "win") {
    winCount++;
    lastWinTimestamp = now;
    setLastTimeDom("win", now);
  } else {
    lossCount++;
    lastLossTimestamp = now;
    setLastTimeDom("loss", now);
  }
  
  // Atualizar DOM
  const winsEl = document.getElementById("statWins");
  const lossesEl = document.getElementById("statLosses");
  const winsPctEl = document.getElementById("statWinsPct");
  
  if (winsEl) winsEl.textContent = String(winCount);
  if (lossesEl) lossesEl.textContent = String(lossCount);
  if (winsPctEl) {
    const total = (winCount || 0) + (lossCount || 0);
    const pct = total > 0 ? Math.round((winCount / total) * 100) : 0;
    winsPctEl.textContent = `${pct}%`;
  }
  
  // Enviar resultado ao backend para salvar no histórico de estatísticas
  try {
    const pendingSignal = pendingSignals.find(p => p.id === signalUiId);
    const signalData = {
      id: signalUiId,
      result: outcome,
      attemptsUsed: pendingSignal?.attemptsUsed || 1,
      platform: "verabet",
      patternKey: pendingSignal?.patternKey || currentActiveSignal?.patternKey || "unknown",
      color: color || pendingSignal?.expectedColor || currentActiveSignal?.color,
      chance: pendingSignal?.chance || currentActiveSignal?.chance || 0,
      createdAt: pendingSignal?.createdAt || currentActiveSignal?.createdAt || Date.now()
    };
    
    fetch(`${API_BASE_URL}/api/signal/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(signalData)
    }).then(() => {
      // Atualizar cards de padrões após salvar resultado
      setTimeout(() => loadPatternTips(), 1000);
    }).catch(e => console.error("Erro ao enviar resultado ao backend:", e));
  } catch (e) {
    console.error("Erro ao preparar dados do sinal:", e);
  }
}

function updateStats() {
  stats = {
    total: results.length,
    red: 0,
    black: 0,
    white: 0,
    currentStreak: { color: null, length: 0 },
  };
  
  let streakColor = null;
  let streakLen = 0;
  
  for (let i = 0; i < results.length; i++) {
    const r = results[i];
    if (!r) continue;
    
    const c = r.color;
    if (c === "red") stats.red++;
    else if (c === "black") stats.black++;
    else if (c === "white") stats.white++;
    
    // Calcular streak atual (do mais recente)
    if (i === 0) {
      streakColor = c;
      streakLen = 1;
    } else if (c === streakColor) {
      streakLen++;
    }
  }
  
  stats.currentStreak = { color: streakColor, length: streakLen };
  
  // Atualizar DOM
  try {
    document.getElementById("statRed").textContent = String(stats.red);
    document.getElementById("statBlack").textContent = String(stats.black);
    document.getElementById("statWhite").textContent = String(stats.white);
    
    const streakEl = document.getElementById("statStreak");
    if (streakEl && stats.currentStreak.color) {
      const colorName = stats.currentStreak.color === "red" ? "Vermelho" :
                        stats.currentStreak.color === "black" ? "Preto" : "Branco";
      streakEl.textContent = `${stats.currentStreak.length}x ${colorName}`;
    }
  } catch (e) {}
}

function renderResults() {
  const grid = document.getElementById("resultsGrid");
  if (!grid) return;
  
  grid.innerHTML = "";
  
  const toShow = results.slice(0, 30);
  
  for (const r of toShow) {
    const div = document.createElement("div");
    div.className = `result-item ${r.color}`;
    div.textContent = String(r.number);
    div.title = `${r.color} - ${r.created_at || ""}`;
    grid.appendChild(div);
  }
}

function setSearchingState() {
  const signalCard = document.getElementById("signalCard");
  const signalBadge = document.getElementById("signalBadge");
  const signalDescription = document.getElementById("signalDescription");
  const signalConfidence = document.getElementById("signalConfidence");
  const signalBet = document.getElementById("signalBet");
  const signalNumbers = document.getElementById("signalNumbers");
  const signalProbability = document.getElementById("signalProbability");
  const signalColorSquare = document.getElementById("signalColorSquare");
  const signalReasons = document.getElementById("signalReasons");
  
  if (signalCard) signalCard.className = "signal-card searching";
  if (signalBadge) signalBadge.textContent = "ANALISANDO";
  if (signalDescription) signalDescription.textContent = "Buscando padrões nos resultados...";
  if (signalConfidence) signalConfidence.textContent = "";
  if (signalBet) signalBet.textContent = "-";
  if (signalNumbers) signalNumbers.textContent = "-";
  if (signalProbability) signalProbability.textContent = "-";
  if (signalColorSquare) signalColorSquare.style.display = "none";
  if (signalReasons) signalReasons.innerHTML = "";
}

function handleBackendSignal(signal) {
  if (signalJustResolved) return;
  
  console.log("Sinal recebido:", signal);
  
  currentActiveSignal = signal;
  
  const signalCard = document.getElementById("signalCard");
  const signalBadge = document.getElementById("signalBadge");
  const signalDescription = document.getElementById("signalDescription");
  const signalConfidence = document.getElementById("signalConfidence");
  const signalBet = document.getElementById("signalBet");
  const signalNumbers = document.getElementById("signalNumbers");
  const signalProbability = document.getElementById("signalProbability");
  const signalColorSquare = document.getElementById("signalColorSquare");
  const signalReasons = document.getElementById("signalReasons");
  
  const color = signal.color || signal.suggestion;
  const colorName = color === "red" ? "Vermelho" : color === "black" ? "Preto" : "Branco";
  const numbers = color === "red" ? "1-7" : color === "black" ? "8-14" : "0";
  const prob = signal.probability || signal.chance || "60%";
  const conf = signal.confidence || signal.confLabel || "média";
  
  if (signalCard) signalCard.className = `signal-card active ${color}`;
  if (signalBadge) signalBadge.textContent = "SINAL";
  if (signalDescription) signalDescription.textContent = signal.description || `Aposte no ${colorName}!`;
  if (signalConfidence) signalConfidence.textContent = `Confiança: ${conf}`;
  if (signalBet) signalBet.textContent = colorName;
  if (signalNumbers) signalNumbers.textContent = numbers;
  if (signalProbability) signalProbability.textContent = typeof prob === "number" ? `${prob}%` : prob;
  
  if (signalColorSquare) {
    signalColorSquare.style.display = "inline-block";
    signalColorSquare.className = `color-square ${color}`;
  }
  
  if (signalReasons && signal.reasons) {
    signalReasons.innerHTML = signal.reasons.map(r => `<div class="reason">${r}</div>`).join("");
  }
  
  // Adicionar sinal pendente
  const signalId = signal.id || `verabet_${Date.now()}`;
  if (!pendingSignals.find(p => p.id === signalId)) {
    pendingSignals.push({
      id: signalId,
      expectedColor: color,
      maxAttempts: signal.maxAttempts || 3,
      evaluatedRounds: 0,
      attemptsUsed: 0,
      resolved: false,
      protect_white: signal.protect_white || false,
    });
  }
  
  updatePendingStatusUI();
  
  // Tocar som
  try {
    const audio = document.getElementById("signalAlertSound");
    if (audio) {
      audio.currentTime = 0;
      audio.play().catch(() => {});
    }
  } catch (e) {}
}

function handleBetResult(betResult) {
  console.log("Resultado de aposta recebido:", betResult);
  
  const outcome = betResult.result;
  const attemptsUsed = betResult.attemptsUsed || 1;
  const signalId = betResult.id;
  
  // Remover da lista de pendentes
  pendingSignals = pendingSignals.filter(p => p.id !== signalId);
  
  updateHistoryWithOutcome(signalId, outcome, attemptsUsed, Date.now(), betResult.color);
  showSignalResolutionOnCard(outcome, attemptsUsed);
  
  signalJustResolved = true;
  setTimeout(() => { signalJustResolved = false; }, 5000);
  
  updatePendingStatusUI();
}

function showSignalResolutionOnCard(outcome, attemptsUsed) {
  const signalCard = document.getElementById("signalCard");
  const signalBadge = document.getElementById("signalBadge");
  const signalDescription = document.getElementById("signalDescription");
  const signalPendingStatus = document.getElementById("signalPendingStatus");
  
  const isWin = outcome === "win";
  
  if (signalCard) {
    signalCard.className = `signal-card resolved ${isWin ? "win" : "loss"}`;
  }
  
  if (signalBadge) {
    signalBadge.textContent = isWin ? "WIN ✓" : "LOSS ✗";
  }
  
  if (signalDescription) {
    signalDescription.textContent = isWin
      ? `Acertou na tentativa ${attemptsUsed}!`
      : `Perdeu após ${attemptsUsed} tentativas`;
  }
  
  if (signalPendingStatus) {
    signalPendingStatus.style.display = "none";
  }
  
  // Voltar ao estado de busca após delay
  setTimeout(() => {
    if (!pendingSignals.length) {
      setSearchingState();
    }
  }, SIGNAL_RESOLUTION_DISPLAY_MS);
}
