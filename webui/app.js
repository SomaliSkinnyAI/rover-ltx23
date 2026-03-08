const state = {
  prompts: [],
  promptFiles: [],
  images: [],
  activePromptFile: null,
  selectedPromptNumbers: new Set(),
  activeJobId: null,
  recentJobs: [],
  defaults: null,
  viewedVideos: new Set(),
};

const THEME_KEY = "ltx23-theme";
const RUNTIME_CONFIG_KEY = "ltx23-runtime-config";
const VIEWED_VIDEOS_KEY = "ltx23-viewed-videos";
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
  videoLengthInput: document.getElementById("videoLengthInput"),
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
  stopRunButton: document.getElementById("stopRunButton"),
  selectAllButton: document.getElementById("selectAllButton"),
  clearAllButton: document.getElementById("clearAllButton"),
  runForm: document.getElementById("runForm"),
  jobStatusText: document.getElementById("jobStatusText"),
  livePanel: document.getElementById("livePanel"),
  missionAlert: document.getElementById("missionAlert"),
  missionAlertText: document.getElementById("missionAlertText"),
  missionState: document.getElementById("missionState"),
  progressBar: document.getElementById("progressBar"),
  currentJobPanel: document.getElementById("currentJobPanel"),
  eventLog: document.getElementById("eventLog"),
  recentOutputs: document.getElementById("recentOutputs"),
  promptCardTemplate: document.getElementById("promptCardTemplate"),
  promptModal: document.getElementById("promptModal"),
  promptModalTitle: document.getElementById("promptModalTitle"),
  promptModalBody: document.getElementById("promptModalBody"),
  promptModalCloseButton: document.getElementById("promptModalCloseButton"),
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

function loadViewedVideos() {
  try {
    const raw = JSON.parse(window.localStorage.getItem(VIEWED_VIDEOS_KEY) || "[]");
    if (!Array.isArray(raw)) {
      return new Set();
    }
    return new Set(raw.filter((value) => typeof value === "string"));
  } catch {
    return new Set();
  }
}

function getRuntimeConfig() {
  return {
    serverUrl: elements.serverUrlInput.value.trim() || state.defaults?.defaultServerUrl || "",
    comfyInputDir: elements.comfyInputDirInput.value.trim() || state.defaults?.comfyInputDir || "",
    outputRoot: elements.outputRootInput.value.trim() || state.defaults?.outputRoot || "",
    videoLengthSeconds: elements.videoLengthInput.value.trim() || String(state.defaults?.defaultVideoLength || ""),
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

function persistViewedVideos() {
  window.localStorage.setItem(VIEWED_VIDEOS_KEY, JSON.stringify([...state.viewedVideos]));
}

function markVideoViewed(path) {
  if (!path) {
    return;
  }
  state.viewedVideos.add(path);
  persistViewedVideos();
}

function isVideoViewed(path) {
  return state.viewedVideos.has(path);
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

function titleCaseStatus(status) {
  if (!status) {
    return "Idle";
  }
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function clearNode(node) {
  node.innerHTML = "";
}

function appendModalSection(title, bodyNode) {
  const section = document.createElement("section");
  section.className = "prompt-modal-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.appendChild(heading);
  section.appendChild(bodyNode);
  elements.promptModalBody.appendChild(section);
}

function openPromptModal(prompt) {
  elements.promptModalTitle.textContent = `Prompt ${prompt.number}: ${prompt.title}`;
  clearNode(elements.promptModalBody);

  const summaryBlock = document.createElement("div");
  summaryBlock.className = "prompt-modal-grid";

  const conceptCard = document.createElement("article");
  conceptCard.className = "prompt-modal-card";
  const conceptLabel = document.createElement("span");
  conceptLabel.textContent = "Concept";
  const conceptText = document.createElement("p");
  conceptText.textContent = prompt.concept || "Not provided";
  conceptCard.append(conceptLabel, conceptText);
  summaryBlock.appendChild(conceptCard);

  const durationCard = document.createElement("article");
  durationCard.className = "prompt-modal-card";
  const durationLabel = document.createElement("span");
  durationLabel.textContent = "Duration";
  const durationText = document.createElement("p");
  durationText.textContent = prompt.duration || "Not provided";
  durationCard.append(durationLabel, durationText);
  summaryBlock.appendChild(durationCard);

  appendModalSection("Overview", summaryBlock);

  if (Array.isArray(prompt.beats) && prompt.beats.length) {
    const beatList = document.createElement("div");
    beatList.className = "prompt-beat-list";
    for (const beat of prompt.beats) {
      const row = document.createElement("article");
      row.className = "prompt-beat-item";
      const timestamp = document.createElement("strong");
      timestamp.textContent = beat.timestamp;
      const description = document.createElement("p");
      description.textContent = beat.description;
      row.append(timestamp, description);
      beatList.appendChild(row);
    }
    appendModalSection("Beats", beatList);
  }

  if (Array.isArray(prompt.extras) && prompt.extras.length) {
    const extrasList = document.createElement("ul");
    extrasList.className = "prompt-extra-list";
    for (const extra of prompt.extras) {
      const item = document.createElement("li");
      item.textContent = extra;
      extrasList.appendChild(item);
    }
    appendModalSection("Extras", extrasList);
  }

  if (prompt.speechSound) {
    const speechBlock = document.createElement("pre");
    speechBlock.className = "prompt-modal-code";
    speechBlock.textContent = prompt.speechSound;
    appendModalSection("Speech & Sound", speechBlock);
  }

  const fullPromptBlock = document.createElement("pre");
  fullPromptBlock.className = "prompt-modal-code";
  fullPromptBlock.textContent = prompt.positivePrompt || "Prompt text unavailable.";
  appendModalSection("Full Prompt", fullPromptBlock);

  if (typeof elements.promptModal.showModal === "function") {
    elements.promptModal.showModal();
  } else {
    elements.promptModal.setAttribute("open", "open");
  }
}

function closePromptModal() {
  if (typeof elements.promptModal.close === "function") {
    elements.promptModal.close();
  } else {
    elements.promptModal.removeAttribute("open");
  }
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
    const detailButton = fragment.querySelector(".prompt-detail-button");

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

    detailButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openPromptModal(prompt);
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
    const viewed = isVideoViewed(item.path);
    if (viewed) {
      row.classList.add("is-viewed");
    }
    row.innerHTML = `
      <time>${formatDate(item.modifiedAt)}</time>
      <strong class="recent-name">${item.name}</strong>
      <div class="recent-size">${formatInteger(item.size)} bytes</div>
      <button class="recent-open-button ${viewed ? "is-viewed" : ""}" type="button">
        ${viewed ? "Viewed" : "Launch video"}
      </button>
      <code>${item.folder}</code>
    `;
    const openButton = row.querySelector(".recent-open-button");
    openButton.addEventListener("click", async () => {
      try {
        await fetchJson("/api/open-output", {
          method: "POST",
          body: JSON.stringify({
            path: item.path,
            outputRoot: elements.outputRootInput.value.trim() || null,
          }),
        });
        markVideoViewed(item.path);
        row.classList.add("is-viewed");
        openButton.classList.add("is-viewed");
        openButton.textContent = "Viewed";
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
    elements.missionAlert.className = "mission-alert";
    elements.missionAlertText.textContent = "Standby";
    elements.jobStatusText.textContent = "No active job";
    elements.jobStatusText.classList.remove("live");
    elements.jobStatusText.classList.remove("warning");
    elements.livePanel.classList.remove("is-live");
    elements.livePanel.classList.remove("is-stopping");
    elements.progressBar.style.width = "0%";
    elements.currentJobPanel.innerHTML =
      '<p class="empty-state">Start a batch to watch prompt-by-prompt progress here.</p>';
    return;
  }

  const percent = job.totalRuns ? Math.round((job.completedRuns / job.totalRuns) * 100) : 0;
  if (job.status === "running" && job.totalRuns) {
    const activeRun = job.currentRunIndex || Math.max(job.completedRuns + 1, 1);
    elements.jobStatusText.textContent = `LIVE • running run ${activeRun}/${job.totalRuns}`;
  } else if (job.status === "stopping") {
    elements.jobStatusText.textContent = `STOPPING • ${job.completedRuns}/${job.totalRuns || 0} runs complete`;
  } else if (job.status === "stopped") {
    elements.jobStatusText.textContent = `stopped • ${job.completedRuns}/${job.totalRuns || job.completedRuns} runs complete`;
  } else if (job.status === "completed") {
    elements.jobStatusText.textContent = `completed • ${job.completedRuns}/${job.totalRuns || job.completedRuns} runs`;
  } else if (job.status === "failed") {
    elements.jobStatusText.textContent = `failed • ${job.completedRuns}/${job.totalRuns || 0} complete`;
  } else {
    elements.jobStatusText.textContent = `${job.status} • ${job.completedRuns}/${job.totalRuns || 0} runs`;
  }
  elements.missionState.textContent = titleCaseStatus(job.status);
  elements.missionState.className = `mission-state ${job.status}`;
  elements.jobStatusText.classList.toggle("live", job.status === "running");
  elements.jobStatusText.classList.toggle("warning", job.status === "stopping");
  elements.livePanel.classList.toggle("is-live", job.status === "running");
  elements.livePanel.classList.toggle("is-stopping", job.status === "stopping");
  elements.missionAlert.className = `mission-alert ${
    job.status === "running" ? "is-live" : job.status === "stopping" ? "is-stopping" : ""
  }`.trim();
  elements.missionAlertText.textContent =
    job.status === "running" ? "Live render" : job.status === "stopping" ? "Stopping now" : "Standby";
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

function setRunControls(activeJob) {
  const hasActiveJob = Boolean(activeJob);
  const canStop = Boolean(activeJob && ["queued", "running"].includes(activeJob.status) && !activeJob.stopRequested);

  elements.startRunButton.disabled = hasActiveJob;
  elements.stopRunButton.disabled = !canStop;

  if (!activeJob) {
    elements.jobGuardLabel.textContent = "Idle";
    return;
  }
  if (activeJob.status === "stopping") {
    elements.jobGuardLabel.textContent = "Stopping batch";
    return;
  }
  elements.jobGuardLabel.textContent = "Batch in progress";
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
  setRunControls(payload.activeJob || null);
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
  state.viewedVideos = loadViewedVideos();

  const savedTheme = window.localStorage.getItem(THEME_KEY) || DEFAULT_THEME;
  applyTheme(savedTheme);

  const runtimeConfig = loadRuntimeConfig();
  elements.serverUrlInput.value = runtimeConfig.serverUrl || config.defaultServerUrl;
  elements.comfyInputDirInput.value = runtimeConfig.comfyInputDir || config.comfyInputDir;
  elements.outputRootInput.value = runtimeConfig.outputRoot || config.outputRoot;
  elements.videoLengthInput.value = runtimeConfig.videoLengthSeconds || String(config.defaultVideoLength || "");
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
    videoLengthSeconds: elements.videoLengthInput.value.trim() || null,
    seedBase: elements.seedBaseInput.value.trim() || null,
    promptNumbers,
  };

  try {
    setRunControls({ status: "queued", stopRequested: false });
    persistRuntimeConfig();
    await fetchJson("/api/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await refreshStatus();
    await refreshRecentOutputs();
  } catch (error) {
    alert(error.message);
    setRunControls(null);
  }
}

async function stopRun() {
  const shouldStop = window.confirm("Stop the current batch and interrupt the active render?");
  if (!shouldStop) {
    return;
  }

  try {
    elements.stopRunButton.disabled = true;
    await fetchJson("/api/jobs/stop", {
      method: "POST",
      body: "{}",
    });
    await refreshStatus();
  } catch (error) {
    alert(error.message);
    await refreshStatus();
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
elements.stopRunButton.addEventListener("click", stopRun);
elements.selectAllButton.addEventListener("click", selectAllPrompts);
elements.clearAllButton.addEventListener("click", clearAllPrompts);
elements.refreshHealthButton.addEventListener("click", refreshHealth);
elements.themeSelect.addEventListener("change", (event) => applyTheme(event.target.value));
elements.promptFileSelect.addEventListener("change", handlePromptFileChange);
elements.reloadPathsButton.addEventListener("click", handlePathReload);
elements.serverUrlInput.addEventListener("change", handleRuntimeConfigInput);
elements.comfyInputDirInput.addEventListener("change", handlePathReload);
elements.outputRootInput.addEventListener("change", handlePathReload);
elements.videoLengthInput.addEventListener("change", handleRuntimeConfigInput);
elements.promptModalCloseButton.addEventListener("click", closePromptModal);
elements.promptModal.addEventListener("click", (event) => {
  if (event.target === elements.promptModal) {
    closePromptModal();
  }
});

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
