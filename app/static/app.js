"use strict";

const fileInput = document.querySelector("#image-file");
const fileName = document.querySelector("#file-name");
const uploadZone = document.querySelector("#upload-zone");
const tokenInput = document.querySelector("#api-token");
const analyzeButton = document.querySelector("#analyze-button");
const buttonLabel = document.querySelector("#button-label");
const errorMessage = document.querySelector("#error-message");
const canvas = document.querySelector("#result-canvas");
const context = canvas.getContext("2d");
const imageStage = document.querySelector("#image-stage");
const previewEmpty = document.querySelector("#preview-empty");
const resultCount = document.querySelector("#result-count");
const resultsEmpty = document.querySelector("#results-empty");
const detectionList = document.querySelector("#detection-list");
const analysisMeta = document.querySelector("#analysis-meta");
const readinessMessage = document.querySelector("#readiness-message");

let selectedFile = null;
let previewUrl = null;
let currentDetections = [];

function clearAnalysis() {
  errorMessage.hidden = true;
  errorMessage.textContent = "";
  resultCount.hidden = true;
  resultsEmpty.hidden = false;
  detectionList.hidden = true;
  detectionList.replaceChildren();
  analysisMeta.hidden = true;
  analysisMeta.textContent = "";
}

function updateButton() {
  analyzeButton.disabled = !selectedFile || analyzeButton.dataset.busy === "true";
}

function showPreview(file) {
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl);
  }
  previewUrl = URL.createObjectURL(file);
  const image = new Image();
  image.onload = () => {
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0);
    drawDetections(currentDetections);
    imageStage.hidden = false;
    previewEmpty.hidden = true;
  };
  image.onerror = () => {
    imageStage.hidden = true;
    previewEmpty.hidden = false;
    showError("The selected file could not be previewed as an image.");
  };
  image.src = previewUrl;
}

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = false;
}

function detectionColor(className) {
  if (className === "face") return "#62c8ff";
  if (className === "license_plate") return "#ffd166";
  return "#a9f074";
}

function drawDetections(detections) {
  if (canvas.width === 0 || canvas.height === 0) return;
  context.lineWidth = Math.max(2, Math.round(canvas.width / 500));
  context.font = `600 ${Math.max(12, Math.round(canvas.width / 55))}px "DM Sans", sans-serif`;
  context.textBaseline = "top";

  for (const detection of detections) {
    const box = detection.bounding_box;
    const x = box.x * canvas.width;
    const y = box.y * canvas.height;
    const width = box.width * canvas.width;
    const height = box.height * canvas.height;
    const color = detectionColor(detection.class_name);
    const title = detection.confidence === null
      ? detection.class_name
      : `${detection.class_name} ${(detection.confidence * 100).toFixed(0)}%`;
    const textWidth = context.measureText(title).width;
    const labelHeight = Math.max(19, Math.round(canvas.width / 35));

    context.strokeStyle = color;
    context.strokeRect(x, y, width, height);
    context.fillStyle = color;
    context.fillRect(x, Math.max(0, y - labelHeight), textWidth + 12, labelHeight);
    context.fillStyle = "#101a1d";
    context.fillText(title, x + 6, Math.max(1, y - labelHeight + 2));
  }
}

function appendDetection(detection) {
  const row = document.createElement("div");
  row.className = "detection-row";

  const name = document.createElement("span");
  name.className = "detection-name";
  const swatch = document.createElement("span");
  swatch.className = "detection-swatch";
  swatch.style.setProperty("--swatch", detectionColor(detection.class_name));
  const title = document.createElement("span");
  title.textContent = detection.class_name.replaceAll("_", " ");
  name.append(swatch, title);

  const detail = document.createElement("span");
  detail.className = "detection-detail";
  const values = [];
  if (detection.confidence !== null) {
    values.push(`${(detection.confidence * 100).toFixed(1)}% confidence`);
  }
  if (detection.plate_text) {
    values.push(`${detection.plate_text} · OCR ${((detection.ocr_confidence ?? 0) * 100).toFixed(1)}%`);
  }
  detail.textContent = values.join(" · ") || "confidence not provided";
  row.append(name, detail);
  detectionList.append(row);
}

function renderResult(result) {
  currentDetections = result.detections;
  drawDetections(currentDetections);
  detectionList.replaceChildren();
  for (const detection of result.detections) {
    appendDetection(detection);
  }
  detectionList.hidden = result.detections.length === 0;
  resultsEmpty.hidden = result.detections.length > 0;
  resultsEmpty.querySelector("p").textContent = result.detections.length === 0
    ? "No detections returned for the selected analytics."
    : "Results are listed below.";
  resultCount.textContent = `${result.detections.length} ${result.detections.length === 1 ? "detection" : "detections"}`;
  resultCount.hidden = false;
  const timestamp = new Date(result.analyzed_at);
  analysisMeta.textContent = `IMAGE ${result.image_width} × ${result.image_height} PX  ·  ${timestamp.toLocaleString()}`;
  analysisMeta.hidden = false;
}

async function loadReadiness() {
  try {
    const response = await fetch("/ready");
    if (!response.ok) {
      throw new Error(`Readiness check returned HTTP ${response.status}.`);
    }
    const readiness = await response.json();
    const options = [...document.querySelectorAll('input[name="analytics"]')];
    const unavailable = [];
    for (const option of options) {
      const available = readiness.capabilities[option.dataset.capability] === true;
      option.disabled = !available;
      if (!available) {
        option.checked = false;
        unavailable.push(option.value.replaceAll("_", " "));
      }
    }
    if (!options.some((option) => option.checked && !option.disabled)) {
      const firstAvailable = options.find((option) => !option.disabled);
      if (firstAvailable) firstAvailable.checked = true;
    }
    const availableNames = options
      .filter((option) => !option.disabled)
      .map((option) => option.parentElement.querySelector("strong").textContent.toLowerCase());
    const message = availableNames.length
      ? `Available now: ${availableNames.join(", ")}.${unavailable.length ? ` Configure compatible model/runtime files to enable ${unavailable.join(", ")}.` : ""}`
      : "No analytics are ready. Configure a compatible model/runtime, then reload this page.";
    readinessMessage.textContent = message;
    updateButton();
  } catch (error) {
    readinessMessage.dataset.state = "error";
    readinessMessage.textContent = error instanceof Error
      ? `Could not check local model readiness: ${error.message}`
      : "Could not check local model readiness.";
  }
}

fileInput.addEventListener("change", () => {
  clearAnalysis();
  currentDetections = [];
  selectedFile = fileInput.files?.[0] ?? null;
  if (!selectedFile) {
    fileName.textContent = "No image selected";
    imageStage.hidden = true;
    previewEmpty.hidden = false;
    updateButton();
    return;
  }
  fileName.textContent = selectedFile.name;
  showPreview(selectedFile);
  updateButton();
});

uploadZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  uploadZone.classList.add("dragging");
});
uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("dragging"));
uploadZone.addEventListener("drop", (event) => {
  event.preventDefault();
  uploadZone.classList.remove("dragging");
  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  fileInput.dispatchEvent(new Event("change", { bubbles: true }));
});

analyzeButton.addEventListener("click", async () => {
  clearAnalysis();
  const token = tokenInput.value.trim();
  if (!token) {
    showError("Enter the local service API token before analyzing an image.");
    tokenInput.focus();
    return;
  }
  const analytics = [...document.querySelectorAll('input[name="analytics"]:checked')].map((input) => input.value);
  if (!analytics.length) {
    showError("Select at least one analytics option.");
    return;
  }
  if (!selectedFile) return;
  if (selectedFile.size > 10 * 1024 * 1024) {
    showError("The selected image is larger than the 10 MiB upload limit.");
    return;
  }

  analyzeButton.dataset.busy = "true";
  buttonLabel.textContent = "Analyzing…";
  updateButton();
  const form = new FormData();
  form.append("image", selectedFile);
  for (const capability of analytics) {
    form.append("analytics", capability);
  }

  try {
    const response = await fetch("/api/v1/images/analyze", {
      method: "POST",
      headers: { "X-API-Key": token },
      body: form,
    });
    const result = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(result.detail)
        ? result.detail.map((entry) => entry.msg).join("; ")
        : result.detail;
      throw new Error(detail || `Analysis failed with HTTP ${response.status}.`);
    }
    renderResult(result);
  } catch (error) {
    showError(error instanceof Error ? error.message : "Image analysis failed.");
  } finally {
    analyzeButton.dataset.busy = "false";
    buttonLabel.textContent = "Analyze image";
    updateButton();
  }
});

window.addEventListener("beforeunload", () => {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
});

loadReadiness();
