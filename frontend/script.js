const SAMPLE_TRANSCRIPT = `Driver: Like, tell me a little bit about how y'all can assist me.
Dispatch: I think you're based out in San Antonio. Is that correct?
Driver: Yes, that's correct. I'm usually in that area, but I'm in Dallas.
Dispatch: So for example, I've got about 30 loads that need to be moved on Tuesday, and most of my best loads are at least $4 per mile.
Driver: For that Huntsville load, what's the weight and the loaded miles?
Dispatch: So this load is 44,000 pounds, and the loaded miles is about two seventeen in total.
Driver: Do y'all deal with hotshots too, like flatbeds or goosenecks?
Dispatch: Yes, we work with hotshots.
Driver: I might only run two or three days a week, but I still make good money. I run a hotshot gooseneck trailer.
Driver: It just depends on the rate. I don't like going north because of Austin, Houston, and Waco traffic. I prefer South Texas lanes like Laredo, Corpus, Rio Grande Valley, Midland, and Odessa.
Driver: As long as it's above $2 per mile, I'll consider it.`;

const state = {
  loads: [],
  runToken: 0,
  hasProfile: false,
  hasRanking: false,
};

const els = {
  screens: {
    1: document.getElementById("screen-1"),
    2: document.getElementById("screen-2"),
    3: document.getElementById("screen-3"),
  },
  transcript: document.getElementById("transcript"),
  analyzeButtons: document.querySelectorAll("[data-action='analyze']"),
  runAgainBtn: document.getElementById("run-again-btn"),
  viewResultsBtn: document.getElementById("view-results-btn"),
  newTranscriptBtn: document.getElementById("new-transcript-btn"),
  loadStatus: document.getElementById("load-status"),
  error: document.getElementById("analysis-error"),
  processingEmpty: document.getElementById("processing-empty"),
  profileEmpty: document.getElementById("profile-empty"),
  loadsEmpty: document.getElementById("loads-empty"),
  rankEmpty: document.getElementById("rank-empty"),
  profileFields: document.getElementById("profile-fields"),
  loadRows: document.getElementById("load-rows"),
  rankCards: document.getElementById("rank-cards"),
};

els.transcript.value = SAMPLE_TRANSCRIPT;
setEmptyState();

function showScreen(index) {
  els.screens[index].scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
}

function clearNode(node) {
  node.innerHTML = "";
}

function setNodeVisible(node, visible) {
  node.classList.toggle("is-visible", visible);
}

function setAnalyzeButtonsDisabled(disabled) {
  els.analyzeButtons.forEach((button) => {
    button.disabled = disabled;
    button.textContent = disabled ? "Analyzing..." : "Analyze Transcript";
  });
}

function setEmptyState() {
  setNodeVisible(els.processingEmpty, !state.hasProfile && !state.hasRanking);
  setNodeVisible(els.profileEmpty, !state.hasProfile);
  setNodeVisible(els.loadsEmpty, !state.hasRanking);
  setNodeVisible(els.rankEmpty, !state.hasRanking);
  els.viewResultsBtn.classList.toggle("hidden", !state.hasRanking);
}

function setError(message) {
  els.error.textContent = message;
  els.error.classList.toggle("hidden", !message);
}

function formatNumber(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }
  const num = Number(value);
  return Number.isInteger(num)
    ? String(num)
    : num.toFixed(digits).replace(/0+$/, "").replace(/\.$/, "");
}

function formatLeg1(value) {
  const num = Number(value);
  if (value !== null && value !== undefined && !Number.isNaN(num) && num < 1.0) {
    return "0.0 mi (same city)";
  }
  return `${formatNumber(value)} mi`;
}

function formatRate(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }
  return Number(value).toFixed(3);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function renderProfile(profile, token) {
  clearNode(els.profileFields);
  state.hasProfile = true;
  setEmptyState();
  const rows = [
    ["Current location", profile.current_location],
    ["Home base", profile.home_base],
    ["Min rate per mile", `$${formatNumber(profile.min_rate_per_mile)}`],
    [
      "Equipment types",
      Array.isArray(profile.equipment_types)
        ? profile.equipment_types.join(", ")
        : "N/A",
    ],
    ["Weight capacity lb", formatNumber(profile.weight_capacity_lb, 0)],
  ];

  rows.forEach(([label, value], index) => {
    const row = document.createElement("div");
    row.className = "profile-field";
    row.innerHTML = `
      <div class="profile-key">${label}</div>
      <div class="profile-value">${value ?? "N/A"}</div>
    `;
    els.profileFields.appendChild(row);
    setTimeout(() => {
      if (token === state.runToken) {
        row.classList.add("visible");
      }
    }, index * 80);
  });
}

function renderLoadEvaluation(result, token) {
  clearNode(els.loadRows);
  state.hasRanking = true;
  setEmptyState();
  const loadsById = new Map(state.loads.map((load) => [load.load_id, load]));

  const rows = [
    ...(result.top3 || []).map((load) => ({
      kind: "pass",
      load_id: load.load_id,
      origin: load.origin,
      destination: load.destination,
      trailer: load.trailer,
      weight: load.weight,
      price: load.price,
      reason: `${formatNumber(load.leg1_mi)} + ${formatNumber(load.leg2_mi)} + ${formatNumber(load.leg3_mi)} mi = ${formatNumber(load.total_mi)} mi`,
      metric: `$${formatRate(load.eff_rate_per_mile)}/mi`,
    })),
    ...(result.rejected || []).map((load) => {
      const fullLoad = loadsById.get(load.load_id) || {};
      return {
        kind: "rejected",
        load_id: load.load_id,
        origin: fullLoad.origin,
        destination: fullLoad.destination,
        trailer: fullLoad.trailer,
        weight: fullLoad.weight,
        reason: load.reason,
      };
    }),
  ];

  rows.forEach((load, index) => {
    const row = document.createElement("div");
    row.className = `load-row ${load.kind === "rejected" ? "rejected" : ""}`;
    row.innerHTML = `
      <div class="load-left">
        <div class="load-id">${load.load_id}</div>
        <div class="load-route">${load.origin ? `${load.origin} to ${load.destination ?? "Missing destination"}` : load.load_id}</div>
        <div class="load-details">${load.trailer || ""}${load.weight != null ? `${load.trailer ? " | " : ""}${load.weight} lb` : ""}</div>
        <div class="reason">${load.kind === "pass" ? load.reason : load.reason || ""}</div>
      </div>
      <div class="load-right">
        <span class="tag ${load.kind}">${load.kind === "pass" ? "pass" : "reject"}</span>
        ${load.kind === "pass" ? `<span class="reason">${load.metric}</span>` : ""}
      </div>
    `;
    els.loadRows.appendChild(row);
    setTimeout(() => {
      if (token === state.runToken) {
        row.classList.add("visible");
      }
    }, index * 60);
  });
}

function renderRankCards(top3, token) {
  clearNode(els.rankCards);
  state.hasRanking = true;
  setEmptyState();

  (top3 || []).forEach((load, index) => {
    const card = document.createElement("article");
    card.className = `rank-card ${load.rank === 1 ? "rank-1" : ""}`;
    card.innerHTML = `
      <div class="rank-badge">Rank ${load.rank}</div>
      <h3>${load.load_id} - ${load.origin} to ${load.destination}</h3>
      <div class="rank-metric"><span>Trailer</span><strong>${load.trailer}</strong></div>
      <div class="rank-metric"><span>Weight</span><strong>${formatNumber(load.weight, 0)} lb</strong></div>
      <div class="rank-metric"><span>Price</span><strong>$${formatNumber(load.price, 0)}</strong></div>
      <div class="rank-metric"><span>Leg 1</span><strong>${formatLeg1(load.leg1_mi)}</strong></div>
      <div class="rank-metric"><span>Leg 2</span><strong>${formatNumber(load.leg2_mi)} mi</strong></div>
      <div class="rank-metric"><span>Leg 3</span><strong>${formatNumber(load.leg3_mi)} mi</strong></div>
      <div class="rank-metric"><span>Total</span><strong>${formatNumber(load.total_mi)} mi</strong></div>
      <div class="rank-metric"><span>Eff rate / mi</span><strong>$${formatRate(load.eff_rate_per_mile)}</strong></div>
    `;
    els.rankCards.appendChild(card);
    setTimeout(() => {
      if (token === state.runToken) {
        card.classList.add("visible");
      }
    }, index * 100);
  });
}

async function fetchLoads() {
  try {
    const response = await fetch("/api/loads");
    if (!response.ok) {
      throw new Error("Failed to load loads");
    }
    state.loads = await response.json();
    els.loadStatus.textContent = `${state.loads.length} loads loaded`;
  } catch {
    els.loadStatus.textContent = "Load board unavailable";
  }
}

function resetProcessingView() {
  state.hasProfile = false;
  state.hasRanking = false;
  setError("");
  clearNode(els.profileFields);
  clearNode(els.loadRows);
  clearNode(els.rankCards);
  setEmptyState();
}

async function analyzeTranscript() {
  if (!state.loads.length) {
    await fetchLoads();
  }

  const token = ++state.runToken;
  resetProcessingView();
  showScreen(2);
  setAnalyzeButtonsDisabled(true);

  try {
    const extractResponse = await fetch("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript: els.transcript.value }),
    });
    const extractData = await extractResponse.json();
    if (!extractResponse.ok) {
      throw new Error(
        extractData?.error || extractData?.detail?.error || "extraction failed",
      );
    }

    renderProfile(extractData, token);
    await sleep(
      Math.max(400, ((extractData?.equipment_types?.length || 0) + 1) * 80),
    );

    const rankResponse = await fetch("/api/rank", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: extractData, loads: state.loads }),
    });
    const rankData = await rankResponse.json();
    if (!rankResponse.ok) {
      throw new Error(
        rankData?.error || rankData?.detail?.error || "ranking failed",
      );
    }

    renderLoadEvaluation(rankData, token);
    renderRankCards(rankData.top3 || [], token);
    await sleep(320 + Math.max(rankData?.top3?.length || 0, rankData?.rejected?.length || 0) * 60);

    if (token !== state.runToken) {
      return;
    }
  } catch (error) {
    if (token !== state.runToken) {
      return;
    }
    setError(error.message || "Something went wrong.");
    showScreen(2);
  } finally {
    if (token === state.runToken) {
      setAnalyzeButtonsDisabled(false);
    }
  }
}

function resetToTranscript() {
  state.runToken += 1;
  setError("");
  resetProcessingView();
  showScreen(1);
}

els.analyzeButtons.forEach((button) => {
  button.addEventListener("click", analyzeTranscript);
});
els.viewResultsBtn.addEventListener("click", () => showScreen(3));
els.newTranscriptBtn.addEventListener("click", resetToTranscript);

fetchLoads();
