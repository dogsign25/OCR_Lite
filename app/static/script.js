const form = document.querySelector("#upload-form");
const fileInput = document.querySelector("#pdf-files");
const fileList = document.querySelector("#file-list");
const filterWords = document.querySelector("#filter-words");
const filterMode = document.querySelector("#filter-mode");
const excludeWords = document.querySelector("#exclude-words");
const filterPreset = document.querySelector("#filter-preset");
const presetName = document.querySelector("#preset-name");
const savePresetButton = document.querySelector("#save-preset");
const deletePresetButton = document.querySelector("#delete-preset");
const presetStatus = document.querySelector("#preset-status");
const dropZone = document.querySelector("#drop-zone");
const submitButton = document.querySelector("#submit-button");
const progressWrap = document.querySelector("#progress-wrap");
const progressBar = document.querySelector("#progress-bar");
const statusMessage = document.querySelector("#status-message");
const resultsSection = document.querySelector("#results");
const resultList = document.querySelector("#result-list");
const PRESET_STORAGE_KEY = "ocrLiteFilterPresets";

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function formatEta(seconds) {
  if (seconds === null || seconds === undefined) return "estimating time remaining";
  if (seconds < 60) return `about ${seconds}s remaining`;
  const minutes = Math.ceil(seconds / 60);
  return `about ${minutes} min remaining`;
}

function renderFiles() {
  fileList.replaceChildren();
  [...fileInput.files].forEach((file) => {
    const item = document.createElement("div");
    item.className = "file-item";
    const name = document.createElement("span");
    name.textContent = file.name;
    const size = document.createElement("span");
    size.className = "file-size";
    size.textContent = formatBytes(file.size);
    item.append(name, size);
    fileList.append(item);
  });
}

function setDroppedFiles(files) {
  const pdfFiles = [...files].filter(
    (file) => file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"),
  );
  const transfer = new DataTransfer();
  pdfFiles.forEach((file) => transfer.items.add(file));
  fileInput.files = transfer.files;
  renderFiles();
}

function readPresets() {
  try {
    const presets = JSON.parse(localStorage.getItem(PRESET_STORAGE_KEY) || "[]");
    if (!Array.isArray(presets)) return [];
    return presets.filter(
      (preset) => preset
        && typeof preset.name === "string"
        && typeof preset.filterWords === "string"
        && ["any", "all"].includes(preset.filterMode)
        && typeof preset.excludeWords === "string",
    );
  } catch {
    return [];
  }
}

function writePresets(presets) {
  try {
    localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(presets));
    return true;
  } catch {
    return false;
  }
}

function renderPresets(selectedName = "") {
  filterPreset.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose a saved preset";
  filterPreset.append(placeholder);
  readPresets().forEach((preset) => {
    const option = document.createElement("option");
    option.value = preset.name;
    option.textContent = preset.name;
    option.selected = preset.name === selectedName;
    filterPreset.append(option);
  });
}

filterPreset.addEventListener("change", () => {
  const preset = readPresets().find((item) => item.name === filterPreset.value);
  if (!preset) return;
  presetName.value = preset.name;
  filterWords.value = preset.filterWords || "";
  filterMode.value = preset.filterMode || "any";
  excludeWords.value = preset.excludeWords || "";
  presetStatus.textContent = `Loaded "${preset.name}".`;
});

savePresetButton.addEventListener("click", () => {
  const name = presetName.value.trim();
  if (!name) {
    presetStatus.textContent = "Enter a preset name.";
    presetStatus.className = "inline-status error";
    return;
  }
  const presets = readPresets().filter((item) => item.name !== name);
  presets.push({
    name,
    filterWords: filterWords.value,
    filterMode: filterMode.value,
    excludeWords: excludeWords.value,
  });
  presets.sort((left, right) => left.name.localeCompare(right.name));
  if (!writePresets(presets)) {
    presetStatus.className = "inline-status error";
    presetStatus.textContent = "This browser could not save the preset.";
    return;
  }
  renderPresets(name);
  presetStatus.className = "inline-status";
  presetStatus.textContent = `Saved "${name}" in this browser.`;
});

deletePresetButton.addEventListener("click", () => {
  const name = filterPreset.value || presetName.value.trim();
  if (!name) {
    presetStatus.textContent = "Choose a preset to delete.";
    presetStatus.className = "inline-status error";
    return;
  }
  if (!writePresets(readPresets().filter((item) => item.name !== name))) {
    presetStatus.className = "inline-status error";
    presetStatus.textContent = "This browser could not update saved presets.";
    return;
  }
  renderPresets();
  presetStatus.className = "inline-status";
  presetStatus.textContent = `Deleted "${name}".`;
});

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

dropZone.addEventListener("drop", (event) => setDroppedFiles(event.dataTransfer.files));
fileInput.addEventListener("change", renderFiles);
renderPresets();

function makeDownloadLink(className, output, label) {
  const link = document.createElement("a");
  link.className = className;
  link.href = output.download_url;
  link.textContent = `${label} (${output.filename})`;
  return link;
}

function updateDownloadLink(link, output, label) {
  link.href = `${output.download_url}?v=${Date.now()}`;
  link.textContent = `${label} (${output.filename})`;
  link.classList.remove("hidden");
}

function buildOcrEditor(result, searchableLink, zipLink, editedLink) {
  const editor = document.createElement("details");
  editor.className = "ocr-editor";
  const summary = document.createElement("summary");
  summary.textContent = "Review OCR text and page layout";

  const toolbar = document.createElement("div");
  toolbar.className = "review-toolbar";
  const reviewOnlyLabel = document.createElement("label");
  const reviewOnly = document.createElement("input");
  reviewOnly.type = "checkbox";
  reviewOnly.checked = false;
  reviewOnlyLabel.append(reviewOnly, " Show only pages needing review");
  const reviewSummary = document.createElement("span");
  toolbar.append(reviewOnlyLabel, reviewSummary);

  const fields = document.createElement("div");
  fields.className = "ocr-editor-fields";

  function updateReviewView() {
    let visible = 0;
    [...fields.children].forEach((field) => {
      const shouldShow = !reviewOnly.checked || field.dataset.reviewRequired === "true";
      field.classList.toggle("hidden", !shouldShow);
      if (shouldShow) visible += 1;
    });
    const reviewCount = [...fields.children].filter(
      (field) => field.dataset.reviewRequired === "true",
    ).length;
    reviewSummary.textContent = `${reviewCount} review page${reviewCount === 1 ? "" : "s"}`;
    fields.classList.toggle("empty-review", visible === 0);
  }

  result.ocr_pages.forEach((page) => {
    const field = document.createElement("article");
    field.className = "ocr-page-field";
    field.dataset.pageNumber = String(page.page_number);
    field.dataset.rotation = String(page.rotation || 0);
    field.dataset.reviewRequired = String(Boolean(page.review_required));

    const pageHeader = document.createElement("div");
    pageHeader.className = "page-header";
    const label = document.createElement("strong");
    label.textContent = `Source page ${page.page_number}`;
    const badge = document.createElement("span");
    badge.className = page.review_required ? "review-badge" : "review-badge reviewed";
    badge.textContent = page.review_required
      ? `Review: ${(page.review_reasons || []).join(", ")}`
      : "Reviewed";
    pageHeader.append(label, badge);

    const image = result.images.find((item) => item.filename === page.image_file);
    if (image) {
      const preview = document.createElement("img");
      preview.className = "page-preview";
      preview.src = image.download_url;
      preview.alt = `Preview of source page ${page.page_number}`;
      preview.style.transform = `rotate(${page.rotation || 0}deg)`;
      field.append(preview);
    }

    const textarea = document.createElement("textarea");
    textarea.rows = 7;
    textarea.value = page.text || "";
    textarea.dataset.originalText = textarea.value;

    const controls = document.createElement("div");
    controls.className = "page-controls";
    const up = document.createElement("button");
    up.type = "button";
    up.className = "small-button";
    up.textContent = "Move up";
    up.addEventListener("click", () => {
      if (field.previousElementSibling) fields.insertBefore(field, field.previousElementSibling);
    });
    const down = document.createElement("button");
    down.type = "button";
    down.className = "small-button";
    down.textContent = "Move down";
    down.addEventListener("click", () => {
      if (field.nextElementSibling) fields.insertBefore(field.nextElementSibling, field);
    });
    const rotate = document.createElement("button");
    rotate.type = "button";
    rotate.className = "small-button";
    rotate.textContent = "Rotate 90 degrees";
    rotate.addEventListener("click", () => {
      const rotation = (Number(field.dataset.rotation) + 90) % 360;
      field.dataset.rotation = String(rotation);
      const preview = field.querySelector(".page-preview");
      if (preview) preview.style.transform = `rotate(${rotation}deg)`;
    });
    controls.append(up, down, rotate);
    field.append(pageHeader, textarea, controls);
    fields.append(field);
  });

  const actionRow = document.createElement("div");
  actionRow.className = "editor-actions";
  const saveText = document.createElement("button");
  saveText.type = "button";
  saveText.textContent = "Save OCR corrections";
  const saveLayout = document.createElement("button");
  saveLayout.type = "button";
  saveLayout.className = "secondary-button";
  saveLayout.textContent = "Apply page order and rotation";
  actionRow.append(saveText, saveLayout);

  const saveStatus = document.createElement("p");
  saveStatus.className = "correction-status";

  saveText.addEventListener("click", async () => {
    const pages = [...fields.children]
      .map((field) => {
        const textarea = field.querySelector("textarea");
        return {
          page_number: Number(field.dataset.pageNumber),
          text: textarea.value,
          originalText: textarea.dataset.originalText,
        };
      })
      .filter((page) => page.text !== page.originalText)
      .map(({ page_number, text }) => ({ page_number, text }));
    if (!pages.length) {
      saveStatus.className = "correction-status";
      saveStatus.textContent = "No OCR text changes to save.";
      return;
    }

    saveText.disabled = true;
    saveStatus.className = "correction-status";
    saveStatus.textContent = "Saving corrections...";
    try {
      const response = await fetch(`/api/ocr/${encodeURIComponent(result.json_file)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pages }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Could not save corrections.");
      result.ocr_pages = payload.pages;
      result.review_required_pages = payload.review_required_pages;
      payload.pages.forEach((page) => {
        const field = fields.querySelector(`[data-page-number="${page.page_number}"]`);
        if (!field) return;
        field.dataset.reviewRequired = String(Boolean(page.review_required));
        const badge = field.querySelector(".review-badge");
        badge.className = page.review_required ? "review-badge" : "review-badge reviewed";
        badge.textContent = page.review_required ? "Needs review" : "Reviewed";
        field.querySelector("textarea").dataset.originalText = page.text || "";
      });
      updateDownloadLink(searchableLink, payload.searchable_pdf, "Searchable PDF");
      updateDownloadLink(zipLink, payload.result_zip, "Download all results as ZIP");
      updateReviewView();
      saveStatus.textContent = "Corrections saved and output files regenerated.";
    } catch (error) {
      saveStatus.className = "correction-status error";
      saveStatus.textContent = error.message;
    } finally {
      saveText.disabled = false;
    }
  });

  saveLayout.addEventListener("click", async () => {
    saveLayout.disabled = true;
    saveStatus.className = "correction-status";
    saveStatus.textContent = "Applying page layout...";
    const pages = [...fields.children].map((field) => ({
      page_number: Number(field.dataset.pageNumber),
      rotation: Number(field.dataset.rotation),
    }));
    try {
      const response = await fetch(`/api/pages/${encodeURIComponent(result.json_file)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pages }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Could not apply page layout.");
      result.ocr_pages = payload.pages;
      updateDownloadLink(editedLink, payload.edited_pdf, "Edited PDF");
      updateDownloadLink(searchableLink, payload.searchable_pdf, "Searchable PDF");
      updateDownloadLink(zipLink, payload.result_zip, "Download all results as ZIP");
      saveStatus.textContent = "Page order and rotation applied.";
    } catch (error) {
      saveStatus.className = "correction-status error";
      saveStatus.textContent = error.message;
    } finally {
      saveLayout.disabled = false;
    }
  });

  reviewOnly.addEventListener("change", updateReviewView);
  editor.append(summary, toolbar, fields, actionRow, saveStatus);
  updateReviewView();
  return editor;
}

function showResults(results) {
  resultList.replaceChildren();
  results.forEach((result) => {
    const card = document.createElement("article");
    card.className = "result-card";
    const title = document.createElement("h3");
    title.textContent = result.source_pdf;

    if (result.status === "failed") {
      const error = document.createElement("p");
      error.className = "warnings";
      error.textContent = result.error || "Processing failed.";
      card.append(title, error);
      resultList.append(card);
      return;
    }

    const meta = document.createElement("p");
    meta.className = "result-meta";
    const reviewCount = result.review_required_pages || 0;
    meta.textContent = result.filtered_pdf
      ? `${result.total_pages} of ${result.source_total_pages} pages retained`
      : `${result.total_pages} page${result.total_pages === 1 ? "" : "s"} processed`;
    if (reviewCount) meta.textContent += `, ${reviewCount} need review`;

    const downloads = document.createElement("div");
    downloads.className = "primary-downloads";
    if (result.filtered_pdf) {
      downloads.append(makeDownloadLink("download-pdf", result.filtered_pdf, "Filtered PDF"));
    }
    const editedLink = document.createElement("a");
    editedLink.className = "download-pdf hidden";
    const searchableLink = makeDownloadLink(
      "download-pdf searchable-download",
      result.searchable_pdf,
      "Searchable PDF",
    );
    const zipLink = makeDownloadLink(
      "download-pdf zip-download",
      result.result_zip,
      "Download all results as ZIP",
    );
    downloads.append(editedLink, searchableLink, zipLink);

    const jsonLinks = document.createElement("div");
    jsonLinks.className = "json-links";
    (result.json_files || []).forEach((output) => {
      jsonLinks.append(makeDownloadLink(
        output.kind === "verified" ? "download-primary" : "download-secondary",
        output,
        output.label,
      ));
    });

    const imageLinks = document.createElement("div");
    imageLinks.className = "image-links";
    result.images.forEach((image) => {
      const link = document.createElement("a");
      link.href = image.download_url;
      link.textContent = image.filename;
      imageLinks.append(link);
    });

    card.append(title, meta, downloads, jsonLinks, imageLinks);
    if (result.ocr_pages?.length) {
      card.append(buildOcrEditor(result, searchableLink, zipLink, editedLink));
    }
    if (result.warnings.length) {
      const warnings = document.createElement("p");
      warnings.className = "warnings";
      warnings.textContent = `Completed with warnings: ${result.warnings.join(" | ")}`;
      card.append(warnings);
    }
    resultList.append(card);
  });
  resultsSection.classList.remove("hidden");
  resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!fileInput.files.length) {
    statusMessage.textContent = "Select at least one PDF file.";
    statusMessage.className = "error";
    progressWrap.classList.remove("hidden");
    return;
  }

  const jobId = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}_${Math.random().toString(16).slice(2)}`;
  const formData = new FormData();
  [...fileInput.files].forEach((file) => formData.append("files", file));
  formData.append("filter_words", filterWords.value);
  formData.append("filter_mode", filterMode.value);
  formData.append("exclude_words", excludeWords.value);
  formData.append("job_id", jobId);

  submitButton.disabled = true;
  progressWrap.classList.remove("hidden");
  resultsSection.classList.add("hidden");
  progressBar.style.width = "0%";
  statusMessage.className = "";
  statusMessage.textContent = "Uploading PDF files...";
  let displayedProgress = 0;
  const setProgress = (percent) => {
    displayedProgress = Math.max(displayedProgress, Math.min(100, percent));
    progressBar.style.width = `${displayedProgress}%`;
  };

  let pollTimer = null;
  const pollProgress = async () => {
    try {
      const response = await fetch(`/api/progress/${encodeURIComponent(jobId)}`);
      if (!response.ok) return;
      const progress = await response.json();
      setProgress(progress.percent);
      statusMessage.textContent = progress.status === "processing"
        ? `${progress.message} ${formatEta(progress.eta_seconds)}.`
        : progress.message;
    } catch {
      // The upload request still reports connection failures.
    }
  };
  pollTimer = setInterval(pollProgress, 600);

  const request = new XMLHttpRequest();
  request.open("POST", "/api/process");
  request.upload.addEventListener("progress", (uploadEvent) => {
    if (uploadEvent.lengthComputable) {
      const percent = Math.round((uploadEvent.loaded / uploadEvent.total) * 100);
      setProgress(Math.min(8, Math.round(percent * 0.08)));
      statusMessage.textContent = percent < 100
        ? `Uploading: ${percent}%`
        : "Starting PDF conversion and OCR...";
    }
  });

  request.addEventListener("load", () => {
    clearInterval(pollTimer);
    submitButton.disabled = false;
    if (request.status >= 200 && request.status < 300) {
      let results;
      try {
        results = JSON.parse(request.responseText).results;
      } catch {
        statusMessage.textContent = "The server returned an invalid response.";
        statusMessage.className = "error";
        return;
      }
      if (!Array.isArray(results)) {
        statusMessage.textContent = "The server returned an invalid result list.";
        statusMessage.className = "error";
        return;
      }
      const failedCount = results.filter((result) => result.status === "failed").length;
      setProgress(100);
      statusMessage.textContent = failedCount
        ? `Processing finished with ${failedCount} failed file${failedCount === 1 ? "" : "s"}.`
        : "Processing complete.";
      statusMessage.className = failedCount ? "error" : "";
      showResults(results);
      return;
    }
    let message = "Processing failed.";
    try {
      message = JSON.parse(request.responseText).detail || message;
    } catch {
      // Keep the generic message when the server response is not JSON.
    }
    statusMessage.textContent = message;
    statusMessage.className = "error";
  });

  request.addEventListener("error", () => {
    clearInterval(pollTimer);
    submitButton.disabled = false;
    statusMessage.textContent = "Could not connect to the server.";
    statusMessage.className = "error";
  });
  request.addEventListener("abort", () => {
    clearInterval(pollTimer);
    submitButton.disabled = false;
    statusMessage.textContent = "Processing request was canceled.";
    statusMessage.className = "error";
  });

  request.send(formData);
});
