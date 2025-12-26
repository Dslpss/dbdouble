// stats.js - Dashboard de Estatísticas DBcolor

const API_BASE_URL = window && (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
  ? "http://localhost:3001"
  : "";

let chartByDay = null;
let chartByHour = null;
let chartByPattern = null;
let currentPage = 1;
let totalPages = 1;

document.addEventListener("DOMContentLoaded", async () => {
  await loadAllStats();
  
  // Event listeners para filtros
  document.getElementById("platformFilter").addEventListener("change", loadAllStats);
  document.getElementById("periodFilter").addEventListener("change", loadAllStats);
  
  // Paginação
  document.getElementById("prevPage").addEventListener("click", () => {
    if (currentPage > 1) {
      currentPage--;
      loadHistory();
    }
  });
  
  document.getElementById("nextPage").addEventListener("click", () => {
    if (currentPage < totalPages) {
      currentPage++;
      loadHistory();
    }
  });
});

function getFilters() {
  return {
    platform: document.getElementById("platformFilter").value,
    days: parseInt(document.getElementById("periodFilter").value)
  };
}

async function loadAllStats() {
  const filters = getFilters();
  currentPage = 1;
  
  await Promise.all([
    loadOverview(filters),
    loadAttemptStats(filters),
    loadChartByDay(filters),
    loadChartByHour(filters),
    loadChartByPattern(filters),
    loadHistory()
  ]);
}

async function loadOverview(filters) {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/stats/overview?platform=${filters.platform}&days=${filters.days}`);
    const data = await resp.json();
    
    if (data.ok) {
      document.getElementById("totalSignals").textContent = data.total || 0;
      document.getElementById("totalWins").textContent = data.wins || 0;
      document.getElementById("totalLosses").textContent = data.losses || 0;
      document.getElementById("winRate").textContent = (data.rate || 0) + "%";
      
      const roi = data.roi || 0;
      const roiEl = document.getElementById("roiValue");
      roiEl.textContent = (roi >= 0 ? "+" : "") + roi + "%";
      roiEl.style.color = roi >= 0 ? "#00ff88" : "#ff4444";
    }
  } catch (e) {
    console.error("Erro ao carregar overview:", e);
  }
}

async function loadAttemptStats(filters) {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/stats/by-attempt?platform=${filters.platform}&days=${filters.days}`);
    const data = await resp.json();
    
    if (data.ok && data.data) {
      document.getElementById("firstAttempt").textContent = data.data.first_attempt || 0;
      document.getElementById("secondAttempt").textContent = data.data.second_attempt || 0;
      document.getElementById("thirdAttempt").textContent = data.data.third_attempt || 0;
      
      document.getElementById("firstPct").textContent = (data.percentages.first || 0) + "% dos wins";
      document.getElementById("secondPct").textContent = (data.percentages.second || 0) + "% dos wins";
      document.getElementById("thirdPct").textContent = (data.percentages.third || 0) + "% dos wins";
    }
  } catch (e) {
    console.error("Erro ao carregar estatísticas por tentativa:", e);
  }
}

async function loadChartByDay(filters) {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/stats/by-day?platform=${filters.platform}&days=${filters.days}`);
    const data = await resp.json();
    
    if (data.ok && data.data) {
      const labels = data.data.map(d => d.date);
      const rates = data.data.map(d => d.rate);
      const totals = data.data.map(d => d.total);
      
      const ctx = document.getElementById("chartByDay").getContext("2d");
      
      if (chartByDay) chartByDay.destroy();
      
      chartByDay = new Chart(ctx, {
        type: "line",
        data: {
          labels: labels,
          datasets: [
            {
              label: "Taxa de Acerto (%)",
              data: rates,
              borderColor: "#667eea",
              backgroundColor: "rgba(102, 126, 234, 0.1)",
              fill: true,
              tension: 0.4
            },
            {
              label: "Total de Sinais",
              data: totals,
              borderColor: "#ffd700",
              backgroundColor: "transparent",
              borderDash: [5, 5],
              yAxisID: "y1"
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: {
            intersect: false,
            mode: "index"
          },
          scales: {
            y: {
              beginAtZero: true,
              max: 100,
              ticks: { color: "#8a8fa8" },
              grid: { color: "rgba(255,255,255,0.1)" }
            },
            y1: {
              position: "right",
              beginAtZero: true,
              ticks: { color: "#8a8fa8" },
              grid: { display: false }
            },
            x: {
              ticks: { color: "#8a8fa8", maxRotation: 45 },
              grid: { color: "rgba(255,255,255,0.1)" }
            }
          },
          plugins: {
            legend: {
              labels: { color: "#e0e4f0" }
            }
          }
        }
      });
    }
  } catch (e) {
    console.error("Erro ao carregar gráfico por dia:", e);
  }
}

async function loadChartByHour(filters) {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/stats/by-hour?platform=${filters.platform}&days=${filters.days}`);
    const data = await resp.json();
    
    if (data.ok && data.data) {
      const labels = data.data.map(d => `${d.hour}h`);
      const rates = data.data.map(d => d.rate);
      const totals = data.data.map(d => d.total);
      
      // Cores baseadas na taxa
      const colors = rates.map(r => {
        if (r >= 70) return "#00ff88";
        if (r >= 50) return "#667eea";
        if (r > 0) return "#ff9800";
        return "#3a3f5c";
      });
      
      const ctx = document.getElementById("chartByHour").getContext("2d");
      
      if (chartByHour) chartByHour.destroy();
      
      chartByHour = new Chart(ctx, {
        type: "bar",
        data: {
          labels: labels,
          datasets: [{
            label: "Taxa de Acerto (%)",
            data: rates,
            backgroundColor: colors,
            borderRadius: 4
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: {
              beginAtZero: true,
              max: 100,
              ticks: { color: "#8a8fa8" },
              grid: { color: "rgba(255,255,255,0.1)" }
            },
            x: {
              ticks: { color: "#8a8fa8" },
              grid: { display: false }
            }
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                afterLabel: (context) => {
                  const index = context.dataIndex;
                  return `Total: ${totals[index]} sinais`;
                }
              }
            }
          }
        }
      });
    }
  } catch (e) {
    console.error("Erro ao carregar gráfico por hora:", e);
  }
}

async function loadChartByPattern(filters) {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/stats/by-pattern?platform=${filters.platform}&days=${filters.days}`);
    const data = await resp.json();
    
    if (data.ok && data.data && data.data.length > 0) {
      const labels = data.data.map(d => d.pattern);
      const rates = data.data.map(d => d.rate);
      const totals = data.data.map(d => d.total);
      
      // Cores variadas para padrões
      const colors = [
        "#667eea", "#764ba2", "#00ff88", "#ffd700", "#ff4444",
        "#00bcd4", "#e91e63", "#9c27b0", "#ff9800", "#4caf50"
      ];
      
      const ctx = document.getElementById("chartByPattern").getContext("2d");
      
      if (chartByPattern) chartByPattern.destroy();
      
      chartByPattern = new Chart(ctx, {
        type: "doughnut",
        data: {
          labels: labels,
          datasets: [{
            data: totals,
            backgroundColor: colors.slice(0, labels.length),
            borderWidth: 0
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: "right",
              labels: { color: "#e0e4f0", padding: 16 }
            },
            tooltip: {
              callbacks: {
                label: (context) => {
                  const index = context.dataIndex;
                  return `${labels[index]}: ${totals[index]} sinais (${rates[index]}% taxa)`;
                }
              }
            }
          }
        }
      });
    } else {
      const ctx = document.getElementById("chartByPattern").getContext("2d");
      if (chartByPattern) chartByPattern.destroy();
      ctx.font = "16px sans-serif";
      ctx.fillStyle = "#8a8fa8";
      ctx.textAlign = "center";
      ctx.fillText("Sem dados suficientes", ctx.canvas.width / 2, ctx.canvas.height / 2);
    }
  } catch (e) {
    console.error("Erro ao carregar gráfico por padrão:", e);
  }
}

async function loadHistory() {
  const filters = getFilters();
  const loadingEl = document.getElementById("historyLoading");
  const tableEl = document.getElementById("historyTable");
  const paginationEl = document.getElementById("pagination");
  const bodyEl = document.getElementById("historyBody");
  
  loadingEl.style.display = "block";
  tableEl.style.display = "none";
  paginationEl.style.display = "none";
  
  try {
    const resp = await fetch(`${API_BASE_URL}/api/stats/signals-history?platform=${filters.platform}&days=${filters.days}&page=${currentPage}&limit=20`);
    const data = await resp.json();
    
    if (data.ok && data.data) {
      totalPages = data.totalPages || 1;
      
      if (data.data.length === 0) {
        loadingEl.textContent = "Nenhum sinal encontrado para o período selecionado.";
        loadingEl.className = "no-data";
        return;
      }
      
      bodyEl.innerHTML = "";
      
      for (const signal of data.data) {
        const row = document.createElement("tr");
        
        const dateStr = signal.createdAt 
          ? new Date(signal.createdAt).toLocaleString("pt-BR")
          : "-";
        
        const platformName = signal.platform === "playnabet" ? "PlayNaBet" : "VeraBet";
        
        row.innerHTML = `
          <td>${dateStr}</td>
          <td>${platformName}</td>
          <td>${signal.patternKey || "-"}</td>
          <td><span class="color-badge ${signal.color || ""}"></span></td>
          <td><span class="result-badge ${signal.result}">${signal.result === "win" ? "WIN" : "LOSS"}</span></td>
          <td>${signal.attemptsUsed || 1}</td>
        `;
        
        bodyEl.appendChild(row);
      }
      
      loadingEl.style.display = "none";
      tableEl.style.display = "table";
      paginationEl.style.display = "flex";
      
      document.getElementById("pageInfo").textContent = `${currentPage} de ${totalPages}`;
      document.getElementById("prevPage").disabled = currentPage <= 1;
      document.getElementById("nextPage").disabled = currentPage >= totalPages;
    }
  } catch (e) {
    console.error("Erro ao carregar histórico:", e);
    loadingEl.textContent = "Erro ao carregar histórico.";
    loadingEl.className = "no-data";
  }
}
