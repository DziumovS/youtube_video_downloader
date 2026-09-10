const urlForm = document.querySelector("#url-form");
const urlInput = document.querySelector("#youtube-url");
const inspectButton = document.querySelector("#inspect-button");
const modePanel = document.querySelector("#mode-panel");
const videoMode = document.querySelector("#video-mode");
const audioMode = document.querySelector("#audio-mode");
const formatsPanel = document.querySelector("#formats-panel");
const formatsList = document.querySelector("#formats-list");
const downloadVideoButton = document.querySelector("#download-video");
const statusBox = document.querySelector("#status");
const statusText = document.querySelector("#status-text");
const errorBox = document.querySelector("#error");
const downloadNotice = document.querySelector("#download-notice");
const downloadAgain = document.querySelector("#download-again");
const lightToggle = document.querySelector("#light-toggle");
const mediaParticles = document.querySelector("#media-particles");

let inspectionId = null;
let selectedFormat = null;
let operation = 0;

function setLights(on) {
  document.body.classList.toggle("lights-off", !on);
  lightToggle.setAttribute("aria-pressed", String(on));
  lightToggle.setAttribute("aria-label", on ? "Turn off the light" : "Turn on the light");
}

let lightsOn = true;
try {
  lightsOn = localStorage.getItem("youtube-downloader-light") !== "off";
} catch (_error) {
  lightsOn = true;
}
setLights(lightsOn);

lightToggle.addEventListener("click", () => {
  lightsOn = !lightsOn;
  setLights(lightsOn);
  try {
    localStorage.setItem("youtube-downloader-light", lightsOn ? "on" : "off");
  } catch (_error) {
    // The switch still works when storage is blocked by the browser.
  }
});

function createMediaParticles() {
  const symbols = ["▶", "♪", "↓", "◆", "·", "▣"];
  const area = window.innerWidth * window.innerHeight;
  const count = Math.min(160, Math.max(70, Math.floor(area / 6500)));
  const fragment = document.createDocumentFragment();
  for (let index = 0; index < count; index += 1) {
    const particle = document.createElement("span");
    particle.className = "media-particle";
    particle.textContent = symbols[index % symbols.length];
    particle.style.left = `${2 + scatter(index, 17) * 96}%`;
    particle.style.top = `${2 + scatter(index, 71) * 96}%`;
    particle.style.fontSize = `${0.72 + (index % 5) * 0.18}rem`;
    particle.style.setProperty("--delay", `${(index % 24) * 0.08}s`);
    particle.style.setProperty("--duration", `${2.8 + (index % 7) * 0.28}s`);
    fragment.append(particle);
  }
  mediaParticles.append(fragment);
}

function scatter(index, salt) {
  const value = Math.sin((index + 1) * 12.9898 + salt * 78.233) * 43758.5453;
  return value - Math.floor(value);
}

createMediaParticles();

function showStatus(message) {
  statusText.textContent = message;
  statusBox.hidden = false;
  errorBox.hidden = true;
}

function hideStatus() {
  statusBox.hidden = true;
}

function showError(message) {
  hideStatus();
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function setBusy(busy) {
  urlInput.disabled = busy;
  inspectButton.disabled = busy || !urlInput.value.trim();
  videoMode.disabled = busy;
  audioMode.disabled = busy;
  downloadVideoButton.disabled = busy || !selectedFormat;
  mediaParticles.hidden = !busy;
}

urlInput.addEventListener("input", () => {
  inspectButton.disabled = !urlInput.value.trim();
  if (inspectionId) {
    operation += 1;
    inspectionId = null;
    selectedFormat = null;
    modePanel.hidden = true;
    formatsPanel.hidden = true;
    formatsList.replaceChildren();
    downloadVideoButton.disabled = true;
  }
  if (!urlInput.value) errorBox.hidden = true;
});

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Could not connect to the server.");
  return data;
}

function resetApp() {
  operation += 1;
  inspectionId = null;
  selectedFormat = null;
  urlForm.reset();
  modePanel.hidden = true;
  formatsPanel.hidden = true;
  formatsList.replaceChildren();
  errorBox.hidden = true;
  hideStatus();
  setBusy(false);
  downloadVideoButton.disabled = true;
  downloadNotice.hidden = true;
  urlInput.focus();
}

urlForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  downloadNotice.hidden = true;
  const url = urlInput.value.trim();
  if (!url) {
    showError("Paste a YouTube link.");
    urlInput.focus();
    return;
  }
  const current = ++operation;
  setBusy(true);
  showStatus("Checking the link…");
  try {
    const data = await api("/api/inspect", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url}),
    });
    if (current !== operation) return;
    inspectionId = data.inspection_id;
    hideStatus();
    modePanel.hidden = false;
  } catch (error) {
    if (current === operation) showError(error.message);
  } finally {
    if (current === operation) setBusy(false);
  }
});

videoMode.addEventListener("click", async () => {
  const current = ++operation;
  setBusy(true);
  showStatus("Loading available formats…");
  try {
    const data = await api(`/api/inspections/${inspectionId}/formats`);
    if (current !== operation) return;
    if (!data.formats.length) throw new Error("No available formats were found for this video.");
    formatsList.replaceChildren(...data.formats.map(formatOption));
    selectedFormat = null;
    downloadVideoButton.disabled = true;
    formatsPanel.hidden = false;
    hideStatus();
    formatsPanel.scrollIntoView({behavior: "smooth", block: "nearest"});
  } catch (error) {
    if (current === operation) showError(error.message);
  } finally {
    if (current === operation) setBusy(false);
  }
});

function formatOption(format) {
  const label = document.createElement("label");
  label.className = "format-option";
  const input = document.createElement("input");
  input.type = "radio";
  input.name = "video-format";
  input.value = format.id;
  input.addEventListener("change", () => {
    selectedFormat = format.id;
    downloadVideoButton.disabled = false;
  });
  const copy = document.createElement("span");
  copy.className = "format-copy";
  const quality = document.createElement("span");
  quality.className = "format-quality";
  quality.textContent = `${format.height}p · MKV`;
  const size = document.createElement("span");
  size.className = "format-size";
  size.textContent = format.size_label;
  copy.append(quality, size);
  label.append(input, copy);
  return label;
}

audioMode.addEventListener("click", () => startJob("audio"));
downloadVideoButton.addEventListener("click", () => {
  if (selectedFormat) startJob("video", selectedFormat);
});

async function startJob(mode, formatId = null) {
  const current = ++operation;
  setBusy(true);
  showStatus(mode === "audio" ? "Preparing the MP3…" : "Downloading and merging the video…");
  try {
    const data = await api("/api/jobs", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        inspection_id: inspectionId,
        mode,
        format_id: formatId,
      }),
    });
    await pollJob(data.job_id, current);
  } catch (error) {
    if (current === operation) {
      setBusy(false);
      showError(error.message);
    }
  }
}

async function pollJob(jobId, current) {
  while (current === operation) {
    const data = await api(`/api/jobs/${jobId}`);
    if (data.status === "error") throw new Error(data.error);
    if (data.status === "ready") {
      beginBrowserDownload(data.file_url, data.filename);
      return;
    }
    showStatus(jobProgressMessage(data));
    await new Promise(resolve => setTimeout(resolve, 500));
  }
}

function jobProgressMessage(data) {
  if (data.status === "queued") return "Download queued…";
  if (data.stage === "checking_cache") return "Checking the cache…";
  if (data.stage === "using_cache") return "Preparing the cached file…";
  if (data.stage === "converting_audio") return "Converting audio to MP3…";
  if (data.stage === "merging_video") return "Merging video and audio…";
  if (data.stage === "normalizing_audio") return "Applying MP3Gain…";
  if (data.stage === "finalizing") return "Finalizing the file…";
  if (data.stage === "downloading_video" || data.stage === "downloading_audio") {
    const media = data.stage === "downloading_audio" ? "audio" : "video";
    const percentage = Number.isFinite(data.percent) ? ` ${data.percent}%` : "";
    const byteProgress = data.total_bytes > 0 && data.downloaded_bytes >= 0
      ? ` · ${formatBytes(data.downloaded_bytes)} / ${formatBytes(data.total_bytes)}`
      : "";
    return `Downloading ${media}…${percentage}${byteProgress}`;
  }
  return "Processing the file on the server…";
}

function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let value = Math.max(0, Number(bytes) || 0);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 10 || unit === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

function beginBrowserDownload(url, filename) {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  downloadAgain.href = url;
  downloadAgain.download = filename;
  resetApp();
}
