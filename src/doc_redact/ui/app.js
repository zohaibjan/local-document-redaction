(() => {
  "use strict";

  const body = document.body;
  const maxBytes = Number(body.dataset.maxUploadBytes);
  const maxPatternLength = Number(body.dataset.maxPatternLength);
  const maxPatterns = Number(body.dataset.maxPatterns);
  const allowedExtensions = new Set(["pdf", "docx", "jpg", "jpeg", "png", "tif", "tiff"]);

  const form = document.querySelector("#redaction-form");
  const fileInput = document.querySelector("#document");
  const dropZone = document.querySelector("#drop-zone");
  const fileSelection = document.querySelector("#file-selection");
  const submitButton = document.querySelector("#submit-button");
  const errorPanel = document.querySelector("#upload-error");
  const errorMessage = document.querySelector("#upload-error-message");
  const progressPanel = document.querySelector("#progress-panel");
  const progressBar = document.querySelector("#upload-progress");
  const progressValue = document.querySelector("#progress-value");
  const progressStatus = document.querySelector("#progress-status");
  const resultPanel = document.querySelector("#result-panel");
  const resultSummary = document.querySelector("#result-summary");
  const downloadLink = document.querySelector("#download-link");
  const outputPreview = document.querySelector("#output-preview");
  const startOver = document.querySelector("#start-over");
  const stages = [
    document.querySelector("#stage-upload"),
    document.querySelector("#stage-process"),
    document.querySelector("#stage-verify"),
  ];

  let verifiedObjectUrl = null;

  function humanSize(bytes) {
    if (!Number.isFinite(bytes)) return "";
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function extensionFor(name) {
    const parts = name.toLowerCase().split(".");
    return parts.length > 1 ? parts.pop() : "";
  }

  function clearVerifiedOutput() {
    if (verifiedObjectUrl) URL.revokeObjectURL(verifiedObjectUrl);
    verifiedObjectUrl = null;
    downloadLink.removeAttribute("href");
    outputPreview.removeAttribute("src");
    resultPanel.hidden = true;
  }

  function showUploadError(message) {
    progressPanel.hidden = true;
    clearVerifiedOutput();
    errorMessage.textContent = message;
    errorPanel.hidden = false;
    errorPanel.focus();
  }

  function clearUploadError() {
    errorPanel.hidden = true;
    errorMessage.textContent = "";
  }

  function validateFile(file) {
    if (!file) return "Choose a document to continue.";
    if (!allowedExtensions.has(extensionFor(file.name))) {
      return "Choose a PDF, DOCX, JPEG/JPG, PNG or TIFF file.";
    }
    if (file.size === 0) return "The selected file is empty.";
    if (file.size > maxBytes) {
      return `The selected file is ${humanSize(file.size)} and exceeds the ${humanSize(maxBytes)} limit.`;
    }
    return null;
  }

  function updateSelection() {
    clearUploadError();
    clearVerifiedOutput();
    const file = fileInput.files[0];
    const validation = validateFile(file);
    if (!file) {
      fileSelection.textContent = "No document selected";
      submitButton.disabled = true;
      return;
    }
    fileSelection.textContent = `${file.name} · ${humanSize(file.size)}`;
    if (validation) {
      submitButton.disabled = true;
      showUploadError(validation);
      return;
    }
    submitButton.disabled = false;
  }

  function setProgress(value, message, stageIndex) {
    const boundedValue = Math.max(0, Math.min(100, value));
    progressBar.value = boundedValue;
    progressBar.textContent = `${boundedValue}%`;
    progressValue.textContent = value >= 100 && stageIndex > 0 ? "Working" : `${boundedValue}%`;
    progressStatus.textContent = message;
    stages.forEach((stage, index) => {
      stage.classList.toggle("complete", index < stageIndex);
      stage.classList.toggle("active", index === stageIndex);
    });
  }

  function safeUploadFailure(status) {
    if (status === 413) return "This document exceeds the configured upload limit.";
    if (status === 415) return "The file contents do not match a supported document format.";
    if (status === 422) {
      return "The document could not be safely read or verified. Check that it is not damaged, encrypted, or password protected.";
    }
    if (status === 429 || status === 503) {
      return "The local processor is busy. Wait a moment, then try again.";
    }
    return "No output was released. Try another document or check the local service.";
  }

  function beginRedaction(event) {
    event.preventDefault();
    clearUploadError();
    clearVerifiedOutput();
    const file = fileInput.files[0];
    const validation = validateFile(file);
    if (validation) {
      showUploadError(validation);
      return;
    }

    submitButton.disabled = true;
    fileInput.disabled = true;
    progressPanel.hidden = false;
    setProgress(0, "Uploading to the local processor…", 0);

    const payload = new FormData();
    payload.append("document", file, file.name);
    const request = new XMLHttpRequest();
    request.open("POST", "/redact");
    request.responseType = "blob";
    request.timeout = 15 * 60 * 1000;

    request.upload.addEventListener("progress", (progressEvent) => {
      if (!progressEvent.lengthComputable) return;
      const percent = Math.min(96, Math.round((progressEvent.loaded / progressEvent.total) * 100));
      setProgress(percent, "Uploading to the local processor…", 0);
    });
    request.upload.addEventListener("load", () => {
      setProgress(100, "Scanning pages and covering detected areas…", 1);
    });
    request.addEventListener("load", () => {
      fileInput.disabled = false;
      submitButton.disabled = false;
      const verified = request.getResponseHeader("X-Redaction-Verified") === "true";
      const contentType = request.getResponseHeader("Content-Type") || "";
      if (request.status < 200 || request.status >= 300 || !verified ||
          !contentType.startsWith("application/pdf")) {
        showUploadError(safeUploadFailure(request.status));
        return;
      }

      setProgress(100, "Verification passed. Preparing your download…", 2);
      const countHeader = request.getResponseHeader("X-Redaction-Detections") || "0";
      const pagesHeader = request.getResponseHeader("X-Redaction-Pages") || "0";
      const count = /^\d+$/.test(countHeader) ? Number(countHeader) : 0;
      const pages = /^\d+$/.test(pagesHeader) ? Number(pagesHeader) : 0;
      verifiedObjectUrl = URL.createObjectURL(request.response);
      downloadLink.href = verifiedObjectUrl;
      outputPreview.src = verifiedObjectUrl;
      const targetLabel = count === 1 ? "redaction target" : "redaction targets";
      const pageLabel = pages === 1 ? "page" : "pages";
      resultSummary.textContent = pages > 0
        ? `${count} ${targetLabel} covered across ${pages} ${pageLabel}.`
        : `${count} ${targetLabel} covered.`;
      progressPanel.hidden = true;
      resultPanel.hidden = false;
      resultPanel.focus();
      resultPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    request.addEventListener("error", () => {
      fileInput.disabled = false;
      submitButton.disabled = false;
      showUploadError("The local service could not be reached. Check that it is running, then try again.");
    });
    request.addEventListener("timeout", () => {
      fileInput.disabled = false;
      submitButton.disabled = false;
      showUploadError("Processing took too long, so no output was released. Try a smaller document.");
    });
    request.send(payload);
  }

  fileInput.addEventListener("change", updateSelection);
  form.addEventListener("submit", beginRedaction);
  submitButton.disabled = true;
  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragging");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragging");
    });
  });
  dropZone.addEventListener("drop", (event) => {
    const files = event.dataTransfer?.files;
    if (!files?.length) return;
    const transfer = new DataTransfer();
    transfer.items.add(files[0]);
    fileInput.files = transfer.files;
    updateSelection();
  });
  startOver.addEventListener("click", () => {
    clearVerifiedOutput();
    form.reset();
    updateSelection();
    fileInput.focus();
  });
  window.addEventListener("beforeunload", clearVerifiedOutput);

  const showPatternFormButton = document.querySelector("#show-pattern-form");
  const patternFormPanel = document.querySelector("#pattern-form-panel");
  const patternForm = document.querySelector("#pattern-form");
  const patternFormTitle = document.querySelector("#pattern-form-title");
  const patternIdentifier = document.querySelector("#pattern-identifier");
  const patternName = document.querySelector("#pattern-name");
  const patternLabel = document.querySelector("#pattern-label");
  const patternRegex = document.querySelector("#pattern-regex");
  const patternContext = document.querySelector("#pattern-context");
  const patternConfidence = document.querySelector("#pattern-confidence");
  const confidenceOutput = document.querySelector("#confidence-output");
  const patternEnabled = document.querySelector("#pattern-enabled");
  const patternFormError = document.querySelector("#pattern-form-error");
  const patternList = document.querySelector("#pattern-list");
  const patternCount = document.querySelector("#pattern-count");
  const patternStatus = document.querySelector("#pattern-status");
  const cancelPattern = document.querySelector("#cancel-pattern");
  const resetPattern = document.querySelector("#reset-pattern");
  let editingIdentifier = null;

  function setPatternStatus(message) {
    patternStatus.textContent = message;
    patternStatus.hidden = !message;
    if (message) patternStatus.focus();
  }

  function setPatternFormError(message) {
    patternFormError.textContent = message;
    patternFormError.hidden = !message;
    if (message) patternFormError.focus();
  }

  function createChip(text, className = "") {
    const chip = document.createElement("span");
    chip.className = `chip ${className}`.trim();
    chip.textContent = text;
    return chip;
  }

  function patternButton(text, action, danger = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `button button-small ${danger ? "button-danger" : "button-secondary"}`;
    button.textContent = text;
    button.addEventListener("click", action);
    return button;
  }

  async function requestPattern(url, options = {}) {
    const requestOptions = { credentials: "same-origin", cache: "no-store", ...options };
    if (options.body) {
      requestOptions.headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    }
    const response = await fetch(url, requestOptions);
    if (!response.ok) throw new Error("pattern-request-failed");
    if (response.status === 204) return null;
    return response.json();
  }

  function renderPatterns(protectedPattern, patterns) {
    patternList.replaceChildren();
    const protectedItem = document.createElement("li");
    protectedItem.className = "pattern-item";
    const protectedMain = document.createElement("div");
    protectedMain.className = "pattern-item-main";
    const protectedName = document.createElement("div");
    protectedName.className = "pattern-name";
    protectedName.append(document.createTextNode(protectedPattern.output_label));
    protectedName.append(createChip("Protected", "chip-protected"));
    const protectedMeta = document.createElement("p");
    protectedMeta.className = "pattern-meta";
    protectedMeta.textContent = `${protectedPattern.identifier} · Always enabled`;
    protectedMain.append(protectedName, protectedMeta);
    protectedItem.append(protectedMain);
    patternList.append(protectedItem);

    patterns.forEach((pattern) => {
      const item = document.createElement("li");
      item.className = "pattern-item";
      const main = document.createElement("div");
      main.className = "pattern-item-main";
      const name = document.createElement("div");
      name.className = "pattern-name";
      name.append(document.createTextNode(pattern.name));
      if (!pattern.enabled) name.append(createChip("Disabled", "chip-disabled"));
      const meta = document.createElement("p");
      meta.className = "pattern-meta";
      meta.textContent = `${pattern.output_label} · ${pattern.identifier} · confidence ${Number(pattern.confidence).toFixed(2)}`;
      main.append(name, meta);

      const actions = document.createElement("div");
      actions.className = "pattern-actions";
      actions.append(
        patternButton("Edit", () => openPatternForm(pattern)),
        patternButton(pattern.enabled ? "Disable" : "Enable", () => togglePattern(pattern)),
        patternButton("Delete", () => deletePattern(pattern), true),
      );
      item.append(main, actions);
      patternList.append(item);
    });
    patternCount.textContent =
      patterns.length === 0
        ? `Built-in recognizer only · up to ${maxPatterns} custom patterns`
        : `${patterns.length} of ${maxPatterns} custom patterns configured`;
  }

  async function loadPatterns() {
    setPatternStatus("");
    try {
      const response = await requestPattern("/api/patterns");
      renderPatterns(response.protected, response.patterns);
    } catch {
      patternCount.textContent = "Pattern status unavailable";
      setPatternStatus("Custom patterns could not be loaded. The protected built-in recognizer is unaffected.");
    }
  }

  function openPatternForm(pattern = null) {
    editingIdentifier = pattern?.identifier || null;
    patternForm.reset();
    patternIdentifier.readOnly = Boolean(pattern);
    patternIdentifier.value = pattern?.identifier || "";
    patternName.value = pattern?.name || "";
    patternLabel.value = pattern?.output_label || "";
    patternRegex.value = pattern?.regex || "";
    patternContext.value = pattern?.context_terms?.join(", ") || "";
    patternConfidence.value = String(pattern?.confidence ?? 0.6);
    confidenceOutput.value = Number(patternConfidence.value).toFixed(2);
    patternEnabled.checked = pattern?.enabled ?? true;
    patternFormTitle.textContent = pattern ? "Edit custom pattern" : "Add a custom pattern";
    setPatternFormError("");
    patternFormPanel.hidden = false;
    (pattern ? patternName : patternIdentifier).focus();
    patternFormPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function closePatternForm() {
    editingIdentifier = null;
    patternForm.reset();
    patternIdentifier.readOnly = false;
    patternFormPanel.hidden = true;
    showPatternFormButton.focus();
  }

  function patternPayload() {
    return {
      identifier: patternIdentifier.value.trim(),
      name: patternName.value.trim(),
      regex: patternRegex.value,
      context_terms: patternContext.value.split(",").map((term) => term.trim()).filter(Boolean),
      confidence: Number(patternConfidence.value),
      enabled: patternEnabled.checked,
      output_label: patternLabel.value.trim(),
    };
  }

  function validatePattern(payload) {
    if (!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(payload.identifier)) {
      return "Use a valid identifier that starts with a letter.";
    }
    if (!payload.name || payload.name.length > 64) {
      return "Provide a display name of 64 characters or fewer.";
    }
    if (!payload.output_label || payload.output_label.length > 64) {
      return "Provide a result label of 64 characters or fewer.";
    }
    if (!payload.regex || payload.regex.length > maxPatternLength) {
      return `Provide a regular expression of ${maxPatternLength} characters or fewer.`;
    }
    if (payload.context_terms.length > 20 ||
        payload.context_terms.some((term) => term.length > 64)) {
      return "Use no more than 20 context terms, each 64 characters or fewer.";
    }
    if (new Set(payload.context_terms.map((term) => term.toLowerCase())).size !==
        payload.context_terms.length) {
      return "Context terms must be unique.";
    }
    return null;
  }

  async function savePattern(event) {
    event.preventDefault();
    setPatternFormError("");
    const payload = patternPayload();
    const validation = validatePattern(payload);
    if (validation) {
      setPatternFormError(validation);
      return;
    }
    if (editingIdentifier && editingIdentifier !== payload.identifier) {
      setPatternFormError("Pattern identifiers cannot be changed. Create a new pattern instead.");
      return;
    }
    const submit = patternForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await requestPattern(`/api/patterns/${encodeURIComponent(payload.identifier)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      closePatternForm();
      await loadPatterns();
    } catch {
      setPatternFormError("The pattern was not accepted. Check its syntax and safe-pattern requirements.");
    } finally {
      submit.disabled = false;
    }
  }

  async function togglePattern(pattern) {
    if (pattern.enabled) {
      const accepted = window.confirm(
        `Disable “${pattern.name}”? Documents will no longer be scanned for this custom pattern.`,
      );
      if (!accepted) return;
    }
    setPatternStatus("");
    try {
      await requestPattern(`/api/patterns/${encodeURIComponent(pattern.identifier)}`, {
        method: "PUT",
        body: JSON.stringify({ ...pattern, enabled: !pattern.enabled }),
      });
      await loadPatterns();
    } catch {
      setPatternStatus("The pattern could not be updated. No settings were changed.");
    }
  }

  async function deletePattern(pattern) {
    const accepted = window.confirm(
      `Delete “${pattern.name}”? This removes the custom pattern from the running service.`,
    );
    if (!accepted) return;
    setPatternStatus("");
    try {
      await requestPattern(`/api/patterns/${encodeURIComponent(pattern.identifier)}`, {
        method: "DELETE",
      });
      await loadPatterns();
    } catch {
      setPatternStatus("The pattern could not be deleted. No settings were changed.");
    }
  }

  patternConfidence.addEventListener("input", () => {
    confidenceOutput.value = Number(patternConfidence.value).toFixed(2);
  });
  showPatternFormButton.addEventListener("click", () => openPatternForm());
  cancelPattern.addEventListener("click", closePatternForm);
  resetPattern.addEventListener("click", closePatternForm);
  patternForm.addEventListener("submit", savePattern);
  loadPatterns();
})();
