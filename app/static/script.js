const form = document.querySelector("#upload-form");
const fileInput = document.querySelector("#pdf-files");
const fileList = document.querySelector("#file-list");
const dropZone = document.querySelector("#drop-zone");
const submitButton = document.querySelector("#submit-button");
const progressWrap = document.querySelector("#progress-wrap");
const progressBar = document.querySelector("#progress-bar");
const statusMessage = document.querySelector("#status-message");
const resultsSection = document.querySelector("#results");
const resultList = document.querySelector("#result-list");

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
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

function showResults(results) {
  resultList.replaceChildren();
  results.forEach((result) => {
    const card = document.createElement("article");
    card.className = "result-card";

    const title = document.createElement("h3");
    title.textContent = result.source_pdf;

    const meta = document.createElement("p");
    meta.className = "result-meta";
    meta.textContent = `${result.total_pages} page${result.total_pages === 1 ? "" : "s"} processed`;

    const jsonLink = document.createElement("a");
    jsonLink.className = "download-primary";
    jsonLink.href = result.json_download_url;
    jsonLink.textContent = `Download ${result.json_file}`;

    const imageLinks = document.createElement("div");
    imageLinks.className = "image-links";
    result.images.forEach((image) => {
      const link = document.createElement("a");
      link.href = image.download_url;
      link.textContent = image.filename;
      imageLinks.append(link);
    });

    card.append(title, meta, jsonLink, imageLinks);

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

  const formData = new FormData();
  [...fileInput.files].forEach((file) => formData.append("files", file));

  submitButton.disabled = true;
  progressWrap.classList.remove("hidden");
  resultsSection.classList.add("hidden");
  progressBar.style.width = "0%";
  statusMessage.className = "";
  statusMessage.textContent = "Uploading PDF files...";

  const request = new XMLHttpRequest();
  request.open("POST", "/api/process");
  request.upload.addEventListener("progress", (uploadEvent) => {
    if (uploadEvent.lengthComputable) {
      const percent = Math.round((uploadEvent.loaded / uploadEvent.total) * 100);
      progressBar.style.width = `${Math.min(percent, 95)}%`;
      statusMessage.textContent = percent < 100
        ? `Uploading: ${percent}%`
        : "Running PDF conversion and OCR...";
    }
  });

  request.addEventListener("load", () => {
    submitButton.disabled = false;
    if (request.status >= 200 && request.status < 300) {
      progressBar.style.width = "100%";
      statusMessage.textContent = "Processing complete.";
      showResults(JSON.parse(request.responseText).results);
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
    submitButton.disabled = false;
    statusMessage.textContent = "Could not connect to the server.";
    statusMessage.className = "error";
  });

  request.send(formData);
});
