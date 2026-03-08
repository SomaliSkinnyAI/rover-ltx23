const state = {
  prompts: [],
  promptFiles: [],
  images: [],
  activePromptFile: null,
  selectedPromptNumbers: new Set(),
  activeJobId: null,
  recentJobs: [],
  defaults: null,
};

const THEME_KEY = "ltx23-theme";
const RUNTIME_CONFIG_KEY = "ltx23-runtime-config";
const DEFAULT_THEME = "signal";

const elements = {
  serverUrlInput: document.getElementById("serverUrlInput"),
  comfyInputDirInput: document.getElementById("comfyInputDirInput"),
  outputRootInput: document.getElementById("outputRootInput"),
  reloadPathsButton: document.getElementById("reloadPathsButton"),
  pathStatusNote: document.getElementById("pathStatusNote"),
  promptFileSelect: document.getElementById("promptFileSelect"),
  promptPackNote: document.getElementById("promptPackNote"),
  promptDeckSubtitle: document.getElementById("promptDeckSubtitle"),
  imageSelect: document.getElementById("imageSelect"),
  variationsInput: document.getElementById("variationsInput"),
  seedBaseInput: document.getElementById("seedBaseInput"),
  promptGrid: document.getElementById("promptGrid"),
  selectionSummary: document.getElementById("selectionSummary"),
  promptCount: document.getElementById("promptCount"),
  imageCount: document.getElementById("imageCount"),
  recentCount: document.getElementById("recentCount"),
  outputRootDisplay: document.getElementById("outputRootDisplay"),
  comfyHealthPill: document.getElementById("comfyHealthPill"),
  refreshHealthButton: document.getElementById("refreshHealthButton"),
  themeSelect: document.getElementById("themeSelect"),
  jobGuardLabel: document.getElementById("jobGuardLabel"),
  startRunButton: document.getElementById("startRunButton"),
  selectAllButton: document.getElementById("selectAllButton"),
  clearAllButton: document.getElementById("clearAllButton"),
  runForm: document.getElementById("runForm"),
  jobStatusText: document.getElementById("jobStatusText"),
  livePanel: document.getElementById("livePanel"),
  missionState: document.getElementById("missionState"),
  progressBar: document.getElementById("progressBar"),
  currentJobPanel: document.getElementById("currentJobPanel"),
  eventLog: document.getElementById("eventLog"),
  recentOutputs: document.getElementById("recentOutputs"),
  promptCardTemplate: document.getElementById("promptCardTemplate"),
};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function applyTheme(theme) {
  const nextTheme = theme || DEFAULT_THEME;
  document.documentElement.dataset.theme = nextTheme;
  elements.themeSelect.value = nextTheme;
  window.localStorage.setItem(THEME_KEY, nextTheme);
}

function loadRuntimeConfig() {
  try {
    return JSON.parse(window.localStorage.getItem(RUNTIME_CONFIG_KEY) || "{}");
  } catch {
    return {};
  }
}

function getRuntimeConfig() {
  return {
    serverUrl: elements.serverUrlInput.value.trim() || state.defaults?.defaultServerUrl || "",
    comfyInputDir: elements.comfyInputDirInput.value.trim() || state.defaults?.comfyInputDir || "",
    outputRoot: elements.outputRootInput.value.trim() || state.defaults?.outputRoot || "",
  };
}

function updateOutputRootDisplay(value) {
  elements.outputRootDisplay.textContent = value || state.defaults?.outputRoot || "Not set";
}

function persistRuntimeConfig() {
  const runtimeConfig = getRuntimeConfig();
  window.localStorage.setItem(RUNTIME_CONFIG_KEY, JSON.stringify(runtimeConfig));
  updateOutputRootDisplay(runtimeConfig.outputRoot);
}

function formatDate(value) {
  if (!value) {
    return "Unknown";
  }
  return new Date(value).toLocaleString();
}

function formatInteger(value) {
  if (value === null || value === undefined || value === "") {
    return "Not set";
  }
  return Number(value).toLocaleString();
}

function updateSelectionSummary() {
  if (state.selectedPromptNumbers.size === state.prompts.length && state.prompts.length > 0) {
    elements.selectionSummary.value = "All prompts selected";
    return;
  }
  if (state.selectedPromptNumbers.size === 0) {
    elements.selectionSummary.value = "No prompts selected";
    return;
  }
  const selected = [...state.selectedPromptNumbers].sort((a, b) => a - b);
  elements.selectionSummary.value = `Prompts ${selected.join(", ")}`;
}

function renderPromptGrid() {
  elements.promptGrid.innerHTML = "";
  if (!state.prompts.length) {
    elements.promptGrid.innerHTML = '<p class="empty-state">No prompts found in the selected pack.</p>';
    return;
  }
  for (const prompt of state.prompts) {
    const fragment = elements.promptCardTemplate.content.cloneNode(true);
    const label = fragment.querySelector(".prompt-card");
    const checkbox = fragment.querySelector(".prompt-toggle");
    const badge = fragment.querySelector(".prompt-badge");
    const title = fragment.querySelector(".prompt-title");
    const concept = fragment.querySelector(".prompt-concept");
    const duration = fragment.querySelector(".prompt-duration");

    badge.textContent = String(prompt.number).padStart(2, "0");
    title.textContent = prompt.title;
    concept.textContent = prompt.concept || prompt.preview || "No concept summary";
    duration.textContent = prompt.duration || "Duration not specified";
    checkbox.checked = state.selectedPromptNumbers.has(prompt.number);
    label.classList.toggle("is-selected", checkbox.checked);

    label.addEventListener("click", (event) => {
      event.preventDefault();
      if (state.selectedPromptNumbers.has(prompt.number)) {
        state.selectedPromptNumbers.delete(prompt.number);
      } else {
        state.selectedPromptNumbers.add(prompt.number);
      }
      renderPromptGrid();
      updateSelectionSummary();
    });

    elements.promptGrid.appendChild(fragment);
  }
}

function renderPromptFileOptions() {
  elements.promptFileSelect.innerHTML = "";
  for (const promptFile of state.promptFiles) {
    const option = document.createElement("option");
    option.value = promptFile.key;
    option.textContent = `${promptFile.name} (${promptFile.promptCount})`;
    elements.promptFileSelect.appendChild(option);
  }
  if (state.activePromptFile) {
    elements.promptFileSelect.value = state.activePromptFile;
  }
}

function renderPromptPackMeta(pack) {
  if (!pack) {
    elements.promptPackNote.textContent = "No prompt pack loaded.";
    elements.promptDeckSubtitle.textContent = "No prompt pack loaded";
    return;
  }
  const detail = pack.description
    ? `${pack.description} ${pack.promptCount} prompts ready.`
    : `${pack.promptCount} prompts ready from ${pack.name}.`;
  elements.promptPackNote.textContent = detail;
  elements.promptDeckSubtitle.textContent = `${pack.name} • click cards to include or exclude them`;
}

function renderImageOptions() {
  elements.imageSelect.innerHTML = "";
  for (const image of state.images) {
    const option = document.createElement("option");
    option.value = image.name;
    option.textContent = image.name;
    elements.imageSelect.appendChild(option);
  }
}

function renderPathStatus(imagesPayload, recentPayload) {
  const statusBits = [];
  const hasImageDir =
    typeof imagesPayload?.exists === "boolean" ? imagesPayload.exists : null;
  const hasOutputRoot =
    typeof recentPayload?.exists === "boolean" ? recentPayload.exists : null;

  if (hasImageDir === null || hasOutputRoot === null) {
    elements.pathStatusNote.textContent =
      "Path status needs a web UI restart to report accurately.";
    elements.pathStatusNote.classList.remove("field-note-error");
    return;
  }

  statusBits.push(
    hasImageDir
      ? `Input dir ready • ${imagesPayload.items.length} image${imagesPayload.items.length === 1 ? "" : "s"}`
      : "Input dir not found"
  );
  statusBits.push(
    hasOutputRoot
      ? `Output root ready • ${recentPayload.items.length} recent render${recentPayload.items.length === 1 ? "" : "s"}`
      : "Output root not found"
  );

  elements.pathStatusNote.textContent = statusBits.join(" • ");
  elements.pathStatusNote.classList.toggle("field-note-error", !hasImageDir || !hasOutputRoot);
}

function renderRecentOutputs(items) {
  elements.recentOutputs.innerHTML = "";
  elements.recentCount.textContent = String(items.length);
  if (!items.length) {
    elements.recentOutputs.innerHTML = '<p class="empty-state">No renders found yet.</p>';
    return;
  }

  for (const item of items) {
    const row = document.createElement("article");
    row.className = "recent-item";
    row.innerHTML = `
      <time>${formatDate(item.modifiedAt)}</time>
      <strong class="recent-name">${item.name}</strong>
      <div class="recent-size">${formatInteger(item.size)} bytes</div>
      <button class="recent-open-button" type="button">Launch video</button>
      <code>${item.folder}</code>
    `;
    row.querySelector(".recent-open-button").addEventListener("click", async () => {
      try {
        await fetchJson("/api/open-output", {
          method: "POST",
          body: JSON.stringify({
            path: item.path,
            outputRoot: elements.outputRootInput.value.trim() || null,
          }),
        });
      } catch (error) {
        alert(error.message);
      }
    });
    elements.recentOutputs.appendChild(row);
  }
}

function renderEventLog(job) {
  elements.eventLog.innerHTML = "";
  if (!job || !job.events.length) {
    elements.eventLog.innerHTML = '<p class="empty-state">No events yet.</p>';
    return;
  }

  const items = [...job.events].reverse();
  for (const event of items) {
    const row = document.createElement("article");
    row.className = "log-item";
    row.innerHTML = `
      <time>${formatDate(new Date(event.timestamp * 1000).toISOString())}</time>
      <strong>${event.event_type.replaceAll("_", " ")}</strong>
      <div>${event.message}</div>
    `;
    elements.eventLog.appendChild(row);
  }
}

function renderCurrentJob(job) {
  elements.currentJobPanel.innerHTML = "";
  if (!job) {
    elements.missionState.textContent = "Idle";
    elements.missionState.className = "mission-state";
    elements.jobStatusText.textContent = "No active job";
    elements.jobStatusText.classList.remove("live");
    elements.livePanel.classList.remove("is-live");
    elements.progressBar.style.width = "0%";
    elements.currentJobPanel.innerHTML =
      '<p class="empty-state">Start a batch to watch prompt-by-prompt progress here.</p>';
    return;
  }

  const percent = job.totalRuns ? Math.round((job.completedRuns / job.totalRuns) * 100) : 0;
  if (job.status === "running" && job.totalRuns) {
    const activeRun = job.currentRunIndex || Math.max(job.completedRuns + 1, 1);
    elements.jobStatusText.textContent = `running • run ${activeRun}/${job.totalRuns}`;
  } else if (job.status === "completed") {
    elements.jobStatusText.textContent = `completed • ${job.completedRuns}/${job.totalRuns || job.completedRuns} runs`;
  } else if (job.status === "failed") {
    elements.jobStatusText.textContent = `failed • ${job.completedRuns}/${job.totalRuns || 0} complete`;
  } else {
    elements.jobStatusText.textContent = `${job.status} • ${job.completedRuns}/${job.totalRuns || 0} runs`;
  }
  elements.missionState.textContent = job.status;
  elements.missionState.className = `mission-state ${job.status}`;
  elements.jobStatusText.classList.toggle("live", job.status === "running");
  elements.livePanel.classList.toggle("is-live", job.status === "running");
  elements.progressBar.style.width = `${percent}%`;

  const panel = document.createElement("article");
  panel.className = "status-card";
  panel.innerHTML = `
    <strong>${job.currentPromptTitle || "Waiting for prompt assignment"}</strong>
    <p>${job.currentMessage || "No progress message yet."}</p>
    <dl>
      <div>
        <dt>Prompt</dt>
        <dd>${job.currentPromptNumber ?? "Not started"}</dd>
      </div>
      <div>
        <dt>Variation</dt>
        <dd>${job.currentVariation ?? "Not started"}</dd>
      </div>
      <div>
        <dt>Seed 1</dt>
        <dd class="mono">${job.currentSeed1 ?? "Pending"}</dd>
      </div>
      <div>
        <dt>Seed 2</dt>
        <dd class="mono">${job.currentSeed2 ?? "Pending"}</dd>
      </div>
      <div>
        <dt>Prompt ID</dt>
        <dd class="mono">${job.currentPromptId || "Pending"}</dd>
      </div>
      <div>
        <dt>Started</dt>
        <dd>${formatDate(job.startedAt)}</dd>
      </div>
    </dl>
  `;
  elements.currentJobPanel.appendChild(panel);

  if (job.error) {
    const errorPanel = document.createElement("article");
    errorPanel.className = "status-card";
    errorPanel.innerHTML = `<strong>Failure</strong><p>${job.error}</p>`;
    elements.currentJobPanel.appendChild(errorPanel);
  }

  for (const result of job.results || []) {
    const resultPanel = document.createElement("article");
    resultPanel.className = "status-card";
    resultPanel.innerHTML = `
      <strong>Prompt ${result.prompt_number} • Variation ${result.variation}</strong>
      <p>Completed with seeds ${result.seed_1} / ${result.seed_2}</p>
      <div class="mono">${result.output_paths.join("<br>")}</div>
    `;
    elements.currentJobPanel.appendChild(resultPanel);
  }
}

function setRunLocked(isLocked) {
  elements.startRunButton.disabled = isLocked;
  elements.jobGuardLabel.textContent = isLocked ? "Batch in progress" : "Idle";
}

async function refreshHealth() {
  const serverUrl = elements.serverUrlInput.value.trim();
  if (!serverUrl) {
    return;
  }
  elements.comfyHealthPill.textContent = "Checking backend";
  elements.comfyHealthPill.className = "status-pill";
  try {
    const payload = await fetchJson(`/api/health?serverUrl=${encodeURIComponent(serverUrl)}`);
    elements.comfyHealthPill.textContent = payload.ok
      ? `Backend ready • ${payload.statusCode || 200}`
      : "Backend unreachable";
    elements.comfyHealthPill.className = `status-pill ${payload.ok ? "ok" : "down"}`;
  } catch (error) {
    elements.comfyHealthPill.textContent = "Backend check failed";
    elements.comfyHealthPill.className = "status-pill down";
  }
}

async function refreshStatus() {
  const payload = await fetchJson("/api/status");
  state.activeJobId = payload.activeJobId;
  state.recentJobs = payload.recentJobs || [];
  renderCurrentJob(payload.activeJob || state.recentJobs[0] || null);
  renderEventLog(payload.activeJob || state.recentJobs[0] || null);
  setRunLocked(Boolean(payload.activeJobId));
}

async function refreshImageLibrary() {
  const selectedImage = elements.imageSelect.value;
  const inputDir = elements.comfyInputDirInput.value.trim();
  const query = inputDir ? `?inputDir=${encodeURIComponent(inputDir)}` : "";
  const payload = await fetchJson(`/api/images${query}`);
  state.images = payload.items || [];
  elements.imageCount.textContent = String(state.images.length);
  renderImageOptions();

  if (selectedImage && state.images.some((item) => item.name === selectedImage)) {
    elements.imageSelect.value = selectedImage;
  } else if (state.defaults?.defaultImage && state.images.some((item) => item.name === state.defaults.defaultImage)) {
    elements.imageSelect.value = state.defaults.defaultImage;
  } else if (state.images.length > 0) {
    elements.imageSelect.value = state.images[0].name;
  }

  return payload;
}

async function refreshRecentOutputs() {
  const outputRoot = elements.outputRootInput.value.trim();
  const query = outputRoot ? `?outputRoot=${encodeURIComponent(outputRoot)}` : "";
  const payload = await fetchJson(`/api/recent-outputs${query}`);
  updateOutputRootDisplay(payload.outputRoot || outputRoot);
  renderRecentOutputs(payload.items || []);
  return payload;
}

async function refreshPathViews() {
  persistRuntimeConfig();
  const [imagesPayload, recentPayload] = await Promise.all([refreshImageLibrary(), refreshRecentOutputs()]);
  renderPathStatus(imagesPayload, recentPayload);
}

async function loadPromptPack(promptFileKey) {
  const query = promptFileKey ? `?file=${encodeURIComponent(promptFileKey)}` : "";
  const payload = await fetchJson(`/api/prompts${query}`);
  state.prompts = payload.items || [];
  state.activePromptFile = payload.pack?.key || promptFileKey || null;
  state.selectedPromptNumbers = new Set(state.prompts.map((prompt) => prompt.number));
  elements.promptCount.textContent = String(state.prompts.length);
  renderPromptFileOptions();
  renderPromptPackMeta(payload.pack || null);
  renderPromptGrid();
  updateSelectionSummary();
}

async function initialize() {
  const [config, promptFilesPayload] = await Promise.all([
    fetchJson("/api/config"),
    fetchJson("/api/prompt-files"),
  ]);

  state.defaults = config;
  state.promptFiles = promptFilesPayload.items || [];

  const savedTheme = window.localStorage.getItem(THEME_KEY) || DEFAULT_THEME;
  applyTheme(savedTheme);

  const runtimeConfig = loadRuntimeConfig();
  elements.serverUrlInput.value = runtimeConfig.serverUrl || config.defaultServerUrl;
  elements.comfyInputDirInput.value = runtimeConfig.comfyInputDir || config.comfyInputDir;
  elements.outputRootInput.value = runtimeConfig.outputRoot || config.outputRoot;
  updateOutputRootDisplay(elements.outputRootInput.value.trim() || config.outputRoot);

  state.activePromptFile = config.defaultPromptFile || state.promptFiles[0]?.key || null;
  renderPromptFileOptions();
  await loadPromptPack(state.activePromptFile);
  await Promise.all([refreshHealth(), refreshStatus(), refreshPathViews()]);
}

async function startRun(event) {
  event.preventDefault();
  const promptNumbers = [...state.selectedPromptNumbers].sort((a, b) => a - b);
  if (!promptNumbers.length) {
    alert("Select at least one prompt.");
    return;
  }

  const payload = {
    serverUrl: elements.serverUrlInput.value.trim(),
    comfyInputDir: elements.comfyInputDirInput.value.trim() || null,
    outputRoot: elements.outputRootInput.value.trim() || null,
    promptFile: state.activePromptFile,
    image: elements.imageSelect.value,
    variations: Number(elements.variationsInput.value),
    seedBase: elements.seedBaseInput.value.trim() || null,
    promptNumbers,
  };

  try {
    setRunLocked(true);
    persistRuntimeConfig();
    await fetchJson("/api/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await refreshStatus();
    await refreshRecentOutputs();
  } catch (error) {
    alert(error.message);
    setRunLocked(false);
  }
}

function selectAllPrompts() {
  state.selectedPromptNumbers = new Set(state.prompts.map((prompt) => prompt.number));
  renderPromptGrid();
  updateSelectionSummary();
}

function clearAllPrompts() {
  state.selectedPromptNumbers = new Set();
  renderPromptGrid();
  updateSelectionSummary();
}

async function handlePromptFileChange(event) {
  const previous = state.activePromptFile;
  const nextFile = event.target.value;
  try {
    await loadPromptPack(nextFile);
  } catch (error) {
    state.activePromptFile = previous;
    renderPromptFileOptions();
    alert(error.message);
  }
}

async function handlePathReload() {
  try {
    await refreshPathViews();
  } catch (error) {
    elements.pathStatusNote.textContent = error.message;
    elements.pathStatusNote.classList.add("field-note-error");
    alert(error.message);
  }
}

function handleRuntimeConfigInput() {
  persistRuntimeConfig();
}

elements.runForm.addEventListener("submit", startRun);
elements.selectAllButton.addEventListener("click", selectAllPrompts);
elements.clearAllButton.addEventListener("click", clearAllPrompts);
elements.refreshHealthButton.addEventListener("click", refreshHealth);
elements.themeSelect.addEventListener("change", (event) => applyTheme(event.target.value));
elements.promptFileSelect.addEventListener("change", handlePromptFileChange);
elements.reloadPathsButton.addEventListener("click", handlePathReload);
elements.serverUrlInput.addEventListener("change", handleRuntimeConfigInput);
elements.comfyInputDirInput.addEventListener("change", handlePathReload);
elements.outputRootInput.addEventListener("change", handlePathReload);

initialize()
  .then(() => {
    window.setInterval(() => {
      refreshStatus().catch(() => {});
      refreshRecentOutputs().catch(() => {});
    }, 3000);
    window.setInterval(() => {
      refreshHealth().catch(() => {});
    }, 10000);
  })
  .catch((error) => {
    console.error(error);
    alert(`Failed to load the web UI: ${error.message}`);
  });
