const state = {
  scenarios: [],
  mode: "",
  scenarioId: "",
};

const modeSelect = document.querySelector("#mode-select");
const scenarioSelect = document.querySelector("#scenario-select");
const scenarioCard = document.querySelector("#scenario-card");
const rosterInput = document.querySelector("#roster-input");
const statusCard = document.querySelector("#status");
const metaStrip = document.querySelector("#meta");
const resultsEl = document.querySelector("#results");
const recommendButton = document.querySelector("#recommend-button");
const fileInput = document.querySelector("#file-input");
const loadSampleButton = document.querySelector("#load-sample");
const resultTemplate = document.querySelector("#result-template");

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "请求失败");
  }
  return payload;
}

function setStatus(message, kind = "") {
  statusCard.textContent = message;
  statusCard.className = "status-card";
  if (kind) {
    statusCard.classList.add(kind);
  }
}

function uniqueModes(scenarios) {
  return Array.from(
    scenarios.reduce((map, scenario) => {
      map.set(scenario.mode, scenario.modeLabel);
      return map;
    }, new Map())
  );
}

function renderModeOptions() {
  const modes = uniqueModes(state.scenarios);
  modeSelect.innerHTML = modes
    .map(([value, label]) => `<option value="${value}">${label}</option>`)
    .join("");
  state.mode = modes[0]?.[0] || "";
}

function renderScenarioOptions() {
  const filtered = state.scenarios.filter((scenario) => scenario.mode === state.mode);
  scenarioSelect.innerHTML = filtered
    .map((scenario) => `<option value="${scenario.id}">${scenario.name}</option>`)
    .join("");
  state.scenarioId = filtered[0]?.id || "";
  renderScenarioCard();
}

function renderScenarioCard() {
  const scenario = state.scenarios.find((item) => item.id === state.scenarioId);
  if (!scenario) {
    scenarioCard.innerHTML = "";
    return;
  }

  const halves = scenario.halves
    .map(
      (half) => `
        <li><strong>${half.name}</strong>：${half.enemySummary}</li>
      `
    )
    .join("");

  const buffs = (scenario.buffs || []).map((buff) => `<li>${buff}</li>`).join("");

  scenarioCard.innerHTML = `
    <h3>${scenario.name}</h3>
    <p>${scenario.description}</p>
    <ul>${halves}</ul>
    <ul>${buffs}</ul>
  `;
}

function renderMeta(meta, simulationMeta = null) {
  const items = [
    ["识别角色", `${meta.rosterSize}`],
    ["枚举队伍", `${meta.evaluatedTeams}`],
    ["上半候选", `${meta.topTeamCandidates}`],
    ["下半候选", `${meta.bottomTeamCandidates}`],
  ];

  if ((meta.parsedRelicDetailUnits || 0) > 0) {
    items.push(["遗器细节", `${meta.parsedRelicDetailUnits}`]);
  }

  if (simulationMeta?.simulatedResults) {
    items.push(["回合模拟", `Top ${simulationMeta.simulatedResults}`]);
    items.push(["单队抽样", `${simulationMeta.runsPerResult} 次`]);
  }

  metaStrip.innerHTML = items
    .map(
      ([label, value]) => `
        <div class="meta-chip">
          <span>${label}</span>
          <strong>${value}</strong>
        </div>
      `
    )
    .join("");
}

function formatPercent(value) {
  return `${Math.round((value || 0) * 100)}%`;
}

function riskClass(label) {
  if (label === "稳定") {
    return "good";
  }
  if (label === "可接受") {
    return "mid";
  }
  return "bad";
}

function renderSimulation(simulation) {
  if (!simulation) {
    return "";
  }

  const overview = simulation.overall || {};
  const overviewItems = [
    ["双清率", formatPercent(overview.pairClearRate)],
    ["均分", `${overview.averagePairScore ?? "-"}`],
    ["波动区间", `${overview.minPairScore ?? "-"} - ${overview.maxPairScore ?? "-"}`],
    ["平均插队", `${overview.averageInterrupts ?? "-"}`],
    ["平均险招", `${overview.averageDangerousSkills ?? "-"}`],
  ];

  const profiles = (simulation.profiles || [])
    .map(
      (profile) => `
        <article class="sim-profile">
          <header class="sim-profile-header">
            <div>
              <h5>${profile.label}</h5>
              <p class="sim-description">${profile.description}</p>
            </div>
            <div class="sim-profile-score">
              <strong>${profile.pairScore}</strong>
              <span>${profile.bothCleared ? "双清" : "未稳定双清"}</span>
            </div>
          </header>
          <div class="sim-profile-meta">
            <span>等效轮次 ${profile.pairCycles}</span>
          </div>
          <div class="sim-halves">
            ${profile.halves
              .map(
                (half) => `
                  <section class="sim-half">
                    <div class="sim-half-head">
                      <strong>${half.half}</strong>
                      <span class="sim-risk ${riskClass(half.riskLabel)}">${half.riskLabel}</span>
                    </div>
                    <div class="sim-metrics">
                      <span>半场 ${half.score}</span>
                      <span>轮次 ${half.cycleEquivalent}</span>
                      <span>敌动 ${half.enemyTurns}</span>
                      <span>破韧 ${half.breaks}</span>
                      <span>插队 ${half.interruptsUsed ?? 0}</span>
                      <span>险招 ${half.dangerousSkillsSeen ?? 0}</span>
                      <span>转阶段 ${half.phaseTransitions ?? 0}</span>
                      ${half.specialMetric ? `<span>${half.specialMetric.label} ${half.specialMetric.value}</span>` : ""}
                    </div>
                    <ul>
                      ${(half.keyMoments || []).map((item) => `<li>${item}</li>`).join("")}
                    </ul>
                  </section>
                `
              )
              .join("")}
          </div>
        </article>
      `
    )
    .join("");

  const notes = (simulation.notes || []).map((note) => `<li>${note}</li>`).join("");

  return `
    <section class="simulation-card">
      <header class="simulation-header">
        <div>
          <h4>回合模拟原型</h4>
          <p>当前版本会对 Top 结果抽样 ${simulation.runs} 次，并模拟终结技插队、危险技能、召唤物与阶段转换。</p>
        </div>
        <div class="simulation-overview">
          ${overviewItems
            .map(
              ([label, value]) => `
                <div class="simulation-stat">
                  <span>${label}</span>
                  <strong>${value}</strong>
                </div>
              `
            )
            .join("")}
        </div>
      </header>
      <div class="simulation-profiles">${profiles}</div>
      ${notes ? `<ul class="simulation-notes">${notes}</ul>` : ""}
    </section>
  `;
}

function renderAlternatives(alternatives) {
  const cards = alternatives
    .map((entry) => {
      if (!entry.suggestions.length) {
        return "";
      }

      const items = entry.suggestions
        .map((suggestion) => {
          const options = suggestion.options
            .map(
              (option) =>
                `<li>没有 <strong>${suggestion.missing}</strong> 时，可换 <strong>${option.name}</strong>，总分 ${option.newScore}（${option.delta >= 0 ? "+" : ""}${option.delta}）。${option.reason}</li>`
            )
            .join("");

          return `<ul>${options}</ul>`;
        })
        .join("");

      return `
        <section class="alternative-card">
          <header>
            <h4>${entry.half} 替补</h4>
          </header>
          ${items}
        </section>
      `;
    })
    .join("");

  return cards || `<section class="alternative-card"><h4>替补</h4><p>当前候选没有找到明显更优的关键位替代。</p></section>`;
}

function renderResults(results) {
  resultsEl.innerHTML = "";
  results.forEach((result, index) => {
    const node = resultTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".rank").textContent = `Rank ${index + 1}`;
    node.querySelector(".result-score").textContent = `综合评分 ${result.score}`;
    node.querySelector(".badge").textContent = result.scoreLabel;
    node.querySelector(".summary").textContent = result.summary;

    const teamsEl = node.querySelector(".teams");
    teamsEl.innerHTML = result.teams
      .map(
        (team) => `
          <section class="team-card">
            <header>
              <div>
                <h4>${team.half}</h4>
                <div class="characters">${team.characters.join(" / ")}</div>
              </div>
              <div class="team-side-score">半场评分 ${team.score}</div>
            </header>
            <div class="key-units"><span class="muted-label">关键位：</span>${team.keyUnits.join("、")}</div>
            <ul>${team.reasons.map((reason) => `<li>${reason}</li>`).join("")}</ul>
          </section>
        `
      )
      .join("");

    node.querySelector(".simulation").innerHTML = renderSimulation(result.simulation);
    node.querySelector(".alternatives").innerHTML = renderAlternatives(result.alternatives);
    resultsEl.appendChild(node);
  });
}

async function loadSampleRoster() {
  const sample = await fetchJson("/api/sample-roster");
  rosterInput.value = JSON.stringify(sample, null, 2);
  setStatus("已载入示例盒子，可以直接点击“生成推荐”。");
}

async function submitRecommendation() {
  const roster = rosterInput.value.trim();
  if (!roster) {
    setStatus("先粘贴或上传一个盒子 JSON。", "error");
    return;
  }

  setStatus("正在枚举双队并计算评分，请稍等。", "loading");
  resultsEl.innerHTML = "";
  metaStrip.innerHTML = "";

  try {
    const payload = await fetchJson("/api/recommend", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        scenarioId: state.scenarioId,
        roster,
      }),
    });

    const skipped = payload.meta.skipped || [];
    const skippedText = skipped.length ? ` 有 ${skipped.length} 条角色记录未识别。` : "";
    const simCount = payload.simulationMeta?.simulatedResults || 0;
    const simText = simCount ? ` 已对 Top ${simCount} 跑回合模拟。` : "";
    setStatus(`已生成 ${payload.results.length} 套候选。${skippedText}${simText}`);
    renderMeta(payload.meta, payload.simulationMeta);
    renderResults(payload.results);
  } catch (error) {
    setStatus(error.message || "生成推荐失败。", "error");
  }
}

async function bootstrap() {
  setStatus("正在加载场景配置。", "loading");
  try {
    const payload = await fetchJson("/api/scenarios");
    state.scenarios = payload.scenarios || [];
    renderModeOptions();
    renderScenarioOptions();
    setStatus("场景加载完成。你可以先载入示例盒子感受一下原型。");
  } catch (error) {
    setStatus(error.message || "初始化失败。", "error");
  }
}

modeSelect.addEventListener("change", () => {
  state.mode = modeSelect.value;
  renderScenarioOptions();
});

scenarioSelect.addEventListener("change", () => {
  state.scenarioId = scenarioSelect.value;
  renderScenarioCard();
});

loadSampleButton.addEventListener("click", async () => {
  try {
    await loadSampleRoster();
  } catch (error) {
    setStatus(error.message || "示例盒子加载失败。", "error");
  }
});

recommendButton.addEventListener("click", submitRecommendation);

fileInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) {
    return;
  }
  const text = await file.text();
  rosterInput.value = text;
  setStatus(`已载入文件：${file.name}`);
});

bootstrap();
