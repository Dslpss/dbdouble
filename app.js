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

// -----------------------------
// Cooldown system for alerts
// -----------------------------
// Configuráveis
const COOLDOWN_BASIC = 4;
const COOLDOWN_AFTER_LOSS = 8;
const STOP_AFTER_3_LOSSES = 12;
const MIN_COOLDOWN_AFTER_WIN = 3;
const GLOBAL_WINDOW_ROUNDS = 30;
const GLOBAL_MAX_ALERTS = 4;
// Quanto tempo (ms) mostrar WIN/LOSS no card antes de voltar ao estado de busca
const SIGNAL_RESOLUTION_DISPLAY_MS = 5000;

// Estado do cooldown
let cooldown_contador = 0;
let perdas_consecutivas = 0;
let modo_stop = false;
let stop_counter = 0; // contador quando em modo stop
let modo_conservador = false;
let historico_alertas = []; // { ts: number, round: number }
let roundIndex = 0; // contador de rodadas incrementado a cada novo resultado
// ids de sinais que foram apenas exibidos como "suprimidos" (não ativos)
let suppressedSignalUiIds = new Set();
// ids vindas do backend que foram suprimidas (para ignorar futuras resoluções)
let suppressedSignalIds = new Set();
// Signatures de sinais suprimidos quando não há um id backend confiável
let suppressedSignatures = []; // { color, round, ts, backendId? }
// Configuração de tentativas do usuário (2 ou 3)
let userMaxAttempts = 3;

function registerSuppressedSignature(color, backendId = null) {
  try {
    suppressedSignatures.push({
      color,
      round: roundIndex,
      ts: Date.now(),
      backendId,
    });
    // manter apenas últimas 200 assinaturas para memória
    if (suppressedSignatures.length > 200)
      suppressedSignatures = suppressedSignatures.slice(-200);
  } catch (e) {}
}

function consumeMatchingSuppressedSignature(signalUiId, color) {
  try {
    const now = Date.now();
    for (let i = 0; i < suppressedSignatures.length; i++) {
      const s = suppressedSignatures[i];
      // se tiver backendId e coincidir com signalUiId -> consumir
      if (s.backendId && signalUiId && s.backendId === signalUiId) {
        suppressedSignatures.splice(i, 1);
        return true;
      }
      // senão, se cor coincidir e estiver dentro de prazo (3 rodadas ou 10s), consumir
      if (color && s.color === color) {
        if (
          Math.abs((roundIndex || 0) - (s.round || 0)) <= 3 ||
          now - (s.ts || 0) <= 10000
        ) {
          suppressedSignatures.splice(i, 1);
          return true;
        }
      }
    }
  } catch (e) {}
  return false;
}

// Deve ser chamada a cada nova rodada
function decrementar_cooldown() {
  // decrementar stop se ativo
  if (modo_stop) {
    stop_counter = Math.max(0, stop_counter - 1);
    if (stop_counter === 0) {
      modo_stop = false;
      perdas_consecutivas = 0; // reset após stop
      console.log("Cooldown: stop terminado, retomando detecção");
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
    cooldown_contador = 0; // stop tem prioridade
  }
}

function verificar_cooldown() {
  return !modo_stop && cooldown_contador === 0;
}

function registrar_alerta() {
  const ts = Date.now();
  historico_alertas.push({ ts: ts, round: roundIndex });
  // manter apenas últimos 50 registros
  if (historico_alertas.length > 100) {
    historico_alertas = historico_alertas.slice(-100);
  }
}

function contar_alertas_na_janela() {
  // contar alertas nos últimos GLOBAL_WINDOW_ROUNDS rodadas
  const minRound = Math.max(0, roundIndex - GLOBAL_WINDOW_ROUNDS + 1);
  return historico_alertas.filter((a) => a.round >= minRound).length;
}

function pode_emitir_alerta() {
  // se em stop, não pode
  if (modo_stop) return false;
  // verificar cooldown atual
  if (cooldown_contador > 0) return false;
  // verificar limite global (3 alertas por 50 rodadas)
  const count = contar_alertas_na_janela();
  if (count >= GLOBAL_MAX_ALERTS) return false;
  return true;
}

// registrar resultado de um sinal (chamar após resolver: win -> true, loss -> false)
function registrar_resultado(acertou) {
  if (acertou) {
    // reduzir cooldown pela metade (mínimo MIN_COOLDOWN_AFTER_WIN)
    cooldown_contador = Math.max(
      MIN_COOLDOWN_AFTER_WIN,
      Math.floor(cooldown_contador / 2)
    );
    perdas_consecutivas = 0;
    modo_conservador = false;
  } else {
    perdas_consecutivas += 1;
    // estender cooldown por perda
    ativar_cooldown("perda");
    // se 3 perdas consecutivas, ativar stop
    if (perdas_consecutivas >= 3) {
      ativar_cooldown("stop");
      console.log(
        "Cooldown: stop temporário ativado por 3 perdas consecutivas"
      );
    }
  }
}

function log_cooldown_status() {
  console.log(
    `Cooldown status -> contador=${cooldown_contador}, stop=${modo_stop}(${stop_counter}), perdas_consecutivas=${perdas_consecutivas}, historico_alertas=${historico_alertas.length}`
  );
}

// -----------------------------

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
  await initializeApp();
});

async function initializeApp() {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/results?limit=50`);
    const data = await resp.json();
    if (data && data.ok && Array.isArray(data.results)) {
      try {
        results = (data.results || []).reverse();
      } catch (e) {}
    }
  } catch (e) {}
  try {
    const sresp = await fetch(`${API_BASE_URL}/api/signal_stats`);
    const sdata = await sresp.json();
    if (sdata && sdata.ok) {
      try {
        winCount = parseInt(sdata.wins || 0);
        lossCount = parseInt(sdata.losses || 0);
        lastWinTimestamp = sdata.lastWinTime || null;
        lastLossTimestamp = sdata.lastLossTime || null;
        try {
          if (lastWinTimestamp) setLastTimeDom("win", lastWinTimestamp);
          if (lastLossTimestamp) setLastTimeDom("loss", lastLossTimestamp);
        } catch (e) {}
      } catch (e) {}
    }
  } catch (e) {}
  
  // Buscar estatísticas de sequências de wins
  try {
    await fetchWinStreaks();
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
  // Mostrar estado inicial de busca
  setSearchingState();
  // Inicializar contadores de wins/losses no DOM
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

  // Mostrar informações do usuário se logado
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
        // Atualizar select se existir
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
            // Fechar modal
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
    
    // Fechar ao clicar fora
    window.addEventListener("click", (e) => {
      if (e.target === settingsModal) {
        settingsModal.style.display = "none";
      }
    });
  } catch (e) {}

  try {
    const modal = document.getElementById("betSignupModal");
    const closeBtn = document.getElementById("closeBetSignup");
    if (modal) modal.style.display = "block";
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        modal.style.display = "none";
        const infoModal = document.getElementById("infoModal");
        const dismissed = localStorage.getItem("infoModalDismissed") === "true";
        if (infoModal && !dismissed) infoModal.style.display = "block";
      });
    }
    window.addEventListener("click", function (event) {
      if (event.target === modal) {
        modal.style.display = "none";
        const infoModal = document.getElementById("infoModal");
        const dismissed = localStorage.getItem("infoModalDismissed") === "true";
        if (infoModal && !dismissed) infoModal.style.display = "block";
      }
    });
  } catch (e) {}

  try {
    const infoModal = document.getElementById("infoModal");
    const closeInfo = document.getElementById("closeInfoModal");
    const infoOkBtn = document.getElementById("infoOkBtn");
    const dontShow = document.getElementById("dontShowInfoAgain");
    const signupModal = document.getElementById("betSignupModal");
    const dismissed = localStorage.getItem("infoModalDismissed") === "true";
    const signupVisible = signupModal && signupModal.style.display === "block";
    if (infoModal && !dismissed && !signupVisible)
      infoModal.style.display = "block";
    function hideInfoModal() {
      if (infoModal) infoModal.style.display = "none";
      if (dontShow && dontShow.checked)
        localStorage.setItem("infoModalDismissed", "true");
    }
    if (closeInfo) closeInfo.addEventListener("click", hideInfoModal);
    if (infoOkBtn) infoOkBtn.addEventListener("click", hideInfoModal);
    window.addEventListener("click", function (event) {
      if (event.target === infoModal) hideInfoModal();
    });
  } catch (e) {}

  // Inicializar quadrado do header (toggle vermelho/preto)
  try {
    const headerSquare = document.getElementById("headerSquare");
    if (headerSquare) {
      // Estado inicial: vermelho
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
  } catch (e) {
    console.error("Erro inicializando headerSquare:", e);
  }

  // Botão de recarregar iframe do cassino
  try {
    const reloadBtn = document.getElementById("reloadGameBtn");
    const gameContainer = document.querySelector(".game-container");
    const iframe = document.getElementById("playnaIframe");
    if (reloadBtn && iframe) {
      reloadBtn.addEventListener("click", () => {
        // Visual feedback
        if (gameContainer) {
          gameContainer.classList.add("reloading");
        }
        // Recarregar com cache-buster
        try {
          const src = iframe.getAttribute("src") || "";
          const sep = src.includes("?") ? "&" : "?";
          iframe.setAttribute("src", src + sep + "t=" + Date.now());
        } catch (e) {
          console.error("Erro ao recarregar iframe:", e);
        }
        // Remover feedback após 1.2s
        setTimeout(() => {
          if (gameContainer) gameContainer.classList.remove("reloading");
        }, 1200);
      });
    }
  } catch (e) {
    console.error("Erro inicializando reloadGameBtn:", e);
  }
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

      if (userInfo && userEmail) {
        userEmail.textContent = userData.email;
        userEmail.textContent = userData.email;
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

      try {
        const modal = document.getElementById("betSignupModal");
        const closeBtn = document.getElementById("closeBetSignup");
        if (modal && modal.style.display !== "block") {
          modal.style.display = "block";
        }
        if (closeBtn) {
          closeBtn.onclick = () => {
            modal.style.display = "none";
            const infoModal = document.getElementById("infoModal");
            const dismissed =
              localStorage.getItem("infoModalDismissed") === "true";
            if (infoModal && !dismissed) infoModal.style.display = "block";
          };
        }
        window.addEventListener("click", function (event) {
          if (event.target === modal) {
            modal.style.display = "none";
            const infoModal = document.getElementById("infoModal");
            const dismissed =
              localStorage.getItem("infoModalDismissed") === "true";
            if (infoModal && !dismissed) infoModal.style.display = "block";
          }
        });
      } catch (e) {}
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

// Verificar status do cooldown e atualizar banner
async function checkCooldownStatus() {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/cooldown_status?platform=playnabet`);
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
  // Nova rodada recebida -> incrementar índice de rodada e decrementar cooldowns
  try {
    roundIndex = (roundIndex || 0) + 1;
    decrementar_cooldown();
  } catch (e) {}
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

  // Sinais são enviados pelo backend; não detectar localmente
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
      const signalUiId = p.id;
      const color = p.expectedColor;
      if (
        signalUiId &&
        (suppressedSignalUiIds.has(signalUiId) ||
          suppressedSignalIds.has(signalUiId))
      ) {
        console.log(
          `[updateHistoryWithOutcome] Ignorando resolução do sinal suprimido ${signalUiId}`
        );
        // Remover das listas de suprimidos para liberar memória
        suppressedSignalUiIds.delete(signalUiId);
        suppressedSignalIds.delete(signalUiId);
        return;
      }
      // Se o signalUiId corresponde a um sinal atualmente exibido ou a um pendingSignal,
      // não tentar casar por assinatura: esse é um sinal visível e deve ser contabilizado.
      let isVisibleSignal = false;
      try {
        if (signalUiId) {
          if (
            pendingSignals &&
            pendingSignals.find((p) => p.id === signalUiId)
          ) {
            isVisibleSignal = true;
          }
          if (
            currentActiveSignal &&
            (currentActiveSignal._uiId === signalUiId ||
              currentActiveSignal.id === signalUiId)
          ) {
            isVisibleSignal = true;
          }
        }
      } catch (e) {}

      if (!isVisibleSignal) {
        // Se não veio id, ou id não estiver nas listas, tentar casar por assinatura (cor/rodada/tempo)
        const matchedBySignature = consumeMatchingSuppressedSignature(
          signalUiId,
          color
        );
        if (matchedBySignature) {
          console.log(
            `[updateHistoryWithOutcome] Ignorando resolução por assinatura suprimida (color=${color}, id=${signalUiId})`
          );
          return;
        }
      }
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
    } else if (p.evaluatedRounds >= userMaxAttempts) {
      // Loss - usa a configuração do usuário (2 ou 3 tentativas)
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
  // Ignorar resoluções referentes a sinais que foram apenas exibidos como "suprimidos"
  try {
    if (
      signalUiId &&
      (suppressedSignalUiIds.has(signalUiId) ||
        suppressedSignalIds.has(signalUiId))
    ) {
      console.log(
        `[updateHistoryWithOutcome] Ignorando resolução do sinal suprimido ${signalUiId}`
      );
      // Remover das listas de suprimidos para liberar memória
      suppressedSignalUiIds.delete(signalUiId);
      suppressedSignalIds.delete(signalUiId);
      return;
    }
  } catch (e) {}
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
  // Atualizar sistema de cooldown com base no resultado do sinal
  try {
    const acertou = (outcome || "").toString().toLowerCase() === "win";
    registrar_resultado(acertou);
    log_cooldown_status();
  } catch (e) {}
  // Atualizar o simulador martingale (agora com os dados do wins/losses)
  try {
    if (typeof updateMartingaleUI === "function") updateMartingaleUI();
  } catch (e) {}
  
  // Enviar resultado ao backend para salvar no histórico de estatísticas
  try {
    // Encontrar o sinal pendente para pegar dados adicionais
    const pendingSignal = pendingSignals.find(p => p.id === signalUiId);
    const signalData = {
      id: signalUiId,
      result: outcome,
      attemptsUsed: attemptsUsed,
      platform: "playnabet",
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

// Atualiza o texto do elemento de pendência para mostrar 'Tentativa X/Y'
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
  const max = userMaxAttempts || 3;  // Usa configuração do usuário
  const currentAttempt = Math.min((p.evaluatedRounds || 0) + 1, max);  // Limitar ao máximo
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
  // Conta quantas VEZES aconteceu uma sequência de 2+ losses consecutivos
  // Retorna { count, lastSequenceTs }
  let count = 0;
  let lastSequenceTs = null;
  let inLossStreak = false;
  let currentStreak = 0;
  let streakStartTs = null;
  
  for (const entry of signalOutcomeHistory) {
    if (entry.outcome === "loss") {
      if (!inLossStreak) {
        // Primeiro loss da possível sequência
        inLossStreak = true;
        currentStreak = 1;
        streakStartTs = entry.ts;
      } else {
        currentStreak++;
      }
    } else {
      if (inLossStreak && currentStreak >= 2) {
        count++; // Terminou uma sequência válida de 2+ losses
        lastSequenceTs = streakStartTs;
      }
      inLossStreak = false;
      currentStreak = 0;
      streakStartTs = null;
    }
  }
  
  // Checar se terminou em sequência ainda ativa
  if (inLossStreak && currentStreak >= 2) {
    count++;
    lastSequenceTs = streakStartTs;
  }
  
  return { count, lastSequenceTs };
}

// Fetch and update win streak statistics
async function fetchWinStreaks() {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/win_streaks`);
    const data = await resp.json();
    if (data && data.ok) {
      // Update DOM elements
      const currentStreakEl = document.getElementById("currentWinStreak");
      const maxStreakEl = document.getElementById("maxWinStreak");
      const avgWinsEl = document.getElementById("avgWinsBetweenLosses");
      
      if (currentStreakEl) currentStreakEl.textContent = String(data.currentStreak || 0);
      if (maxStreakEl) maxStreakEl.textContent = String(data.maxStreak || 0);
      
      if (avgWinsEl) {
          if (data.totalStreaks === 0) {
              avgWinsEl.textContent = "-";
          } else {
              avgWinsEl.textContent = String(data.averageWinsBetweenLosses || "0.00");
          }
      }
    }
  } catch (e) {
    console.error("Error fetching win streaks:", e);
  }
}

// Profit simulator removed: UI and logic for the profit/martingale card were removed.

// Debug helpers: add counts manually from UI
// Debug functions removed to avoid UI debug buttons in production

// Função para carregar dicas de padrões (melhor e pior taxa de acerto)
async function loadPatternTips() {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/stats/pattern-tips?platform=playnabet&days=7&min_signals=3`);
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
  const winsPctEl = document.getElementById("statWinsPct");
  if (winsEl) winsEl.textContent = String(winCount);
  if (lossesEl) lossesEl.textContent = String(lossCount);
  if (winsPctEl) {
    const total = (winCount || 0) + (lossCount || 0);
    const pct = total > 0 ? Math.round((winCount / total) * 100) : 0;
    winsPctEl.textContent = `${pct}%`;
  }

  // Atualizar estatísticas de sequências de wins
  try {
    fetchWinStreaks();
  } catch (e) {}

  // Atualizar perdas consecutivas
  try {
    const consecutiveLossesEl = document.getElementById("consecutiveLosses");
    const lastConsecutiveLossTimeEl = document.getElementById("lastConsecutiveLossTime");
    if (consecutiveLossesEl) {
      const { count, lastSequenceTs } = getConsecutiveSignalLosses();
      consecutiveLossesEl.textContent = String(count);
      if (lastConsecutiveLossTimeEl) {
        lastConsecutiveLossTimeEl.textContent = lastSequenceTs ? formatTimestamp(lastSequenceTs) : "-";
      }
    }
  } catch (e) {}

  // Atualizar profit card caso esteja visível (simulador removido)
  try {
    if (typeof updateProfitCard === "function") updateProfitCard();
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
  // Agendar retorno ao estado de busca após mostrar WIN/LOSS por um tempo configurável
  try {
    const resolvedSignalRef = currentActiveSignal;
    setTimeout(() => {
      try {
        // Só limpar se o mesmo sinal ainda for o atual (evitar sobrescrever novo sinal)
        if (
          currentActiveSignal &&
          resolvedSignalRef &&
          currentActiveSignal === resolvedSignalRef
        ) {
          // limpar estilos visuais do card
          try {
            const card = document.getElementById("signalCard");
            const badge = document.getElementById("signalBadge");
            const pendingStatusEl = document.getElementById(
              "signalPendingStatus"
            );
            const existingProtect =
              document.getElementById("protectWhiteBadge");
            if (badge) {
              badge.classList.remove("win", "loss");
            }
            if (card) {
              card.style.borderColor = "";
              card.style.boxShadow = "";
            }
            if (pendingStatusEl) pendingStatusEl.style.display = "none";
            if (existingProtect) existingProtect.remove();
          } catch (e) {}
          // permitir que setSearchingState sobrescreva
          signalJustResolved = false;
          currentActiveSignal = null;
          setSearchingState();
        }
      } catch (e) {}
    }, SIGNAL_RESOLUTION_DISPLAY_MS);
  } catch (e) {}
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
  const totalEl = document.getElementById("statTotal");
  if (totalEl) totalEl.textContent = stats.total;
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
  try {
    const existingProtect = document.getElementById("protectWhiteBadge");
    if (existingProtect) existingProtect.remove();
  } catch (e) {}
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
      `Existem ${pendingSignals.length} sinais pendentes — continuando detecção para não atrasar.`
    );
    updatePendingStatusUI();
  }

  // Mostrar que estamos procurando por padrões
  setSearchingState();

  // detectSignal já exige pelo menos 3 resultados internamente
  const signal = detectSignal();
  if (signal) {
    // Checar cooldown e limite global antes de emitir
    if (pode_emitir_alerta()) {
      displaySignal(signal);
      // Registrar alerta no histórico e ativar cooldown básico
      registrar_alerta();
      ativar_cooldown("basico");
      log_cooldown_status();
    } else {
      const expectedColor = signal.suggestedBet
        ? signal.suggestedBet.color
        : null;
      registerSuppressedSignature(expectedColor, null);
      if (modo_stop) {
        console.log(
          `Stop temporário ativo (${stop_counter} rodadas restantes)`
        );
      } else if (cooldown_contador > 0) {
        console.log(
          `Padrão detectado mas cooldown ativo (${cooldown_contador} rodadas restantes)`
        );
      } else {
        console.log(
          `Limite global atingido (${GLOBAL_MAX_ALERTS}/${GLOBAL_WINDOW_ROUNDS}) — sinal suprimido`
        );
      }
    }
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
  if (signal && signal.suggestedBet && signal.suggestedBet.color === "white") {
    console.log("[DBG] Ignorando sinal do backend que sugere BRANCO.");
    return;
  }
  // Antes de exibir, checar cooldown/pendências
  if (pode_emitir_alerta()) {
    displaySignal(signal);
    registrar_alerta();
    ativar_cooldown("basico");
    log_cooldown_status();

    // mark current signal as pending (if it has id)
    currentPendingSignalId = signalData.id || null;
    const pendingStatusEl = document.getElementById("signalPendingStatus");
    if (currentPendingSignalId && pendingStatusEl) {
      pendingStatusEl.style.display = "block";
    }
  } else {
    // Não exibir UI; marcar id do backend como suprimido para ignorar resoluções futuras
    const backendId = signalData.id || null;
    if (backendId) {
      suppressedSignalIds.add(backendId);
      // registrar assinatura também por cor/rodada para casos onde a resolução venha sem o mesmo id
      const expectedColor = signal.suggestedBet
        ? signal.suggestedBet.color
        : null;
      registerSuppressedSignature(expectedColor, backendId);
      console.log(
        `[DBG] Sinal backend id=${backendId} suprimido por cooldown/limite (registrado para ignorar resoluções).`
      );
    } else {
      console.log(`[DBG] Sinal backend suprimido (sem id disponível).`);
    }
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
function displaySignal(signal, options = {}) {
  const suppressed = options.suppressed === true;
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

  // Badge text: se suprimido, marcar como SUPRIMIDO
  const badgeText = suppressed
    ? `${signal.type.replace("_", " ")} (SUPRIMIDO)`
    : signal.type.replace("_", " ");
  document.getElementById("signalBadge").textContent = badgeText;
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

  if (!suppressed && protectWhite) {
    const protectBadge = document.createElement("span");
    protectBadge.id = "protectWhiteBadge";
    protectBadge.className = "protect-white-badge";
    protectBadge.style.cssText =
      "display: inline-block; background-color: #fff; color: #333; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; margin-left: 8px; font-weight: bold; border: 1px solid #ccc;";
    protectBadge.innerHTML = "Cobrir Branco ⚪";
    if (betGroup) betGroup.appendChild(protectBadge);
  }

  // Tocar som de alerta (somente se não for suprimido)
  try {
    if (!suppressed) {
      const audio = document.getElementById("signalAlertSound");
      if (audio) {
        audio.currentTime = 0;
        audio
          .play()
          .catch((e) =>
            console.log(
              "Audio play failed (user interaction needed first?):",
              e
            )
          );
      }
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
  // Se o sinal foi apenas suprimido, marcamos seu uiId para que
  // futuras resoluções (vindas do backend) sejam ignoradas.
  if (suppressed) {
    suppressedSignalUiIds.add(uiId);
  } else {
    // Marcar sinal como atual na UI (será preservado até remoção manual ou nova atribuição)
    currentActiveSignal = signal;
  }

  // Registrar sinal pendente para avaliação automática nas próximas rodadas
  // Somente se não for suprimido (suprimidos não criam pendingSignals)
  try {
    if (!suppressed) {
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
const _btnSettings = document.getElementById("btnSettings");
if (_btnSettings) {
  _btnSettings.addEventListener("click", () => {
    loadUserPreferences();
    const modal = document.getElementById("settingsModal");
    if (modal) modal.style.display = "block";
  });
}

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
