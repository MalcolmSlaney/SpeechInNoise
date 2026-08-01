/**
 * QuickSIN Results Dashboard - Core Logic & Sound File Speaker Player
 */

// Column Label Mappings
const COLUMN_LABELS = {
  results_id: "Results ID",
  results_subject: "Subject",
  results_trial: "Trial",
  results_reply_filename: "Sound File",
  results_time: "Results Time",
  trials_id: "Trial ID",
  trials_project: "Project",
  trials_snr: "SNR",
  trials_lang: "Language",
  trials_level_number: "Level",
  trials_trial_number: "Trial #",
  trials_filename: "Filename",
  trials_answer: "Answer",
  trials_active: "Active",
  user_id: "User ID",
  user_name: "User Name",
  user_ip: "User IP",
  user_time: "User Time",
  user_info_id: "User Info ID",
  user_info_key: "Info Key",
  user_info_value: "Info Value",
  user_info_time: "Info Time",
  asr_id: "ASR ID",
  asr_results: "ASR Results",
  asr_gt_word_count: "GT Word Count",
  asr_correct_word_count: "Correct Word Count",
  asr_clean_tokens: "Clean Tokens",
  annotation_ref: "Annotation Ref",
  annotation_matches: "Annotation Matches",
  asr_words: "ASR Words",
  asr_matches: "ASR Matches",
  asr_times: "ASR Times",
  audiology_asr_matches: "Audiology ASR Matches"
};

// Default visible columns
const DEFAULT_VISIBLE_COLUMNS = [
  "results_subject",
  "results_trial",
  "results_reply_filename",
  "trials_project",
  "trials_snr",
  "trials_lang",
  "trials_answer",
  "asr_results"
];

// App State
let state = {
  allRecords: [],
  filteredRecords: [],
  filters: {
    searchText: "",
    language: "",
    subject: "",
    project: "",
    snr: "",
    mismatchedOnly: false
  },
  columnVisibility: {},
  sortColumn: null,
  sortOrder: "asc",
  currentPage: 1,
  pageSize: 50,
  dataSourceName: "QuickSIN Results (Stanford)",
  theme: localStorage.getItem("theme") || "light"
};

// Audio Controller for Sound File Speaker Column
const audioController = {
  activeAudio: null,
  activeBtn: null,
  activeFilename: null,

  stop() {
    if (this.activeAudio) {
      this.activeAudio.pause();
      this.activeAudio = null;
    }
    if (window.speechSynthesis && window.speechSynthesis.speaking) {
      window.speechSynthesis.cancel();
    }
    if (this.activeBtn) {
      this.activeBtn.classList.remove("playing");
      this.activeBtn.innerHTML = `
        <i data-feather="volume-2" style="width: 16px; height: 16px;"></i>
        <span>Play</span>
      `;
      feather.replace();
      this.activeBtn = null;
      this.activeFilename = null;
    }
  },

  play(filename, btnElement, phraseFallback) {
    // If clicking the same button that is already playing, pause it
    if (this.activeFilename === filename && this.activeBtn === btnElement) {
      this.stop();
      return;
    }

    // Stop any existing playing audio
    this.stop();

    this.activeBtn = btnElement;
    this.activeFilename = filename;

    // Update UI state to playing
    btnElement.classList.add("playing");
    btnElement.innerHTML = `
      <div class="sound-wave">
        <div class="sound-wave-bar"></div>
        <div class="sound-wave-bar"></div>
        <div class="sound-wave-bar"></div>
      </div>
      <span>Playing</span>
    `;

    // Attempt audio playback via proxy URL
    const audioUrl = `/api/audio/${filename}`;
    const audio = new Audio(audioUrl);
    this.activeAudio = audio;

    audio.onended = () => {
      this.stop();
    };

    audio.onerror = () => {
      console.warn("[AudioController] Primary audio URL failed, falling back to speech synthesis...", audioUrl);
      this.fallbackSpeech(phraseFallback);
    };

    audio.play().catch((err) => {
      console.warn("[AudioController] Play interrupted or blocked, falling back to speech synthesis...", err);
      this.fallbackSpeech(phraseFallback);
    });
  },

  fallbackSpeech(text) {
    if (!window.speechSynthesis) {
      showToast("Audio playback not available for this track");
      this.stop();
      return;
    }
    const speechText = text || "Audio sample playback";
    const utterance = new SpeechSynthesisUtterance(speechText);
    utterance.rate = 0.95;
    
    utterance.onend = () => {
      this.stop();
    };
    utterance.onerror = () => {
      this.stop();
    };

    window.speechSynthesis.speak(utterance);
  }
};

// Robust CSV Parser
function parseCSV(csvText) {
  const lines = csvText.split(/\r\n|\n/);
  if (lines.length < 2) return [];

  function parseRow(rowStr) {
    const fields = [];
    let current = '';
    let inQuotes = false;

    for (let i = 0; i < rowStr.length; i++) {
      const char = rowStr[i];
      const nextChar = rowStr[i + 1];

      if (char === '"') {
        if (inQuotes && nextChar === '"') {
          current += '"';
          i++; // Skip escaped quote
        } else {
          inQuotes = !inQuotes;
        }
      } else if (char === ',' && !inQuotes) {
        fields.push(current.trim());
        current = '';
      } else {
        current += char;
      }
    }
    fields.push(current.trim());
    return fields;
  }

  const headers = parseRow(lines[0]);
  const records = [];

  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    const values = parseRow(line);
    if (values.length < Math.max(1, headers.length - 5)) continue;

    const rowObj = {};
    headers.forEach((h, idx) => {
      rowObj[h] = values[idx] || "";
    });
    records.push(rowObj);
  }

  return records;
}

// Initial Data Load
async function initData() {
  try {
    const urlParams = new URLSearchParams(window.location.search);
    const customCsvUrl = urlParams.get("csv");

    let csvContent = "";
    if (customCsvUrl) {
      showToast("Loading CSV from URL parameter...");
      const res = await fetch('/api/csv-proxy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: customCsvUrl })
      });
      const data = await res.json();
      if (data.success) {
        csvContent = data.data;
        state.dataSourceName = customCsvUrl;
      } else {
        throw new Error(data.error || "Failed to load CSV from URL");
      }
    } else {
      // Load local preloaded CSV
      const res = await fetch('./data/quicksin.csv');
      csvContent = await res.text();
      state.dataSourceName = "QuickSIN Results (Stanford)";
    }

    state.allRecords = parseCSV(csvContent);
    initColumnVisibility();
    restoreStateFromURL();
    populateDropdowns();
    applyFilters();
    updateUI();

    document.getElementById("sourceText").textContent = `Source: ${state.dataSourceName}`;
  } catch (err) {
    console.error("Initialization error:", err);
    showToast("Error loading dataset. Check console for details.");
  }
}

// Helper to get user-friendly column label
function getColumnLabel(key) {
  if (COLUMN_LABELS[key]) return COLUMN_LABELS[key];
  return key
    .replace(/^(results|trials|user|asr|annotation|audiology)_/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, l => l.toUpperCase());
}

// Initialize Column Visibility map - all columns visible by default
function initColumnVisibility() {
  if (state.allRecords.length === 0) return;
  const allKeys = Object.keys(state.allRecords[0]);
  
  const visibility = {};
  allKeys.forEach(key => {
    visibility[key] = true;
  });
  state.columnVisibility = visibility;
  renderColumnToggles();
}

// Render Column Toggle checkboxes in sidebar
function renderColumnToggles() {
  const container = document.getElementById("columnTogglesContainer");
  if (!container) return;

  const visibleKeys = Object.keys(state.columnVisibility);
  const activeCount = visibleKeys.filter(k => state.columnVisibility[k]).length;
  document.getElementById("visibleColCount").textContent = activeCount;

  container.innerHTML = visibleKeys.map(key => {
    const label = getColumnLabel(key);
    const isChecked = state.columnVisibility[key] ? "checked" : "";
    return `
      <label class="column-toggle-item">
        <span>${label}</span>
        <input type="checkbox" data-col="${key}" ${isChecked}>
      </label>
    `;
  }).join("");

  // Attach toggle listeners
  container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener("change", (e) => {
      const colKey = e.target.getAttribute("data-col");
      state.columnVisibility[colKey] = e.target.checked;
      document.getElementById("visibleColCount").textContent = 
        Object.values(state.columnVisibility).filter(Boolean).length;
      renderTableHeader();
      renderTableBody();
    });
  });
}

// Populate Filter Dropdowns
function populateDropdowns() {
  const records = state.allRecords;
  const langs = new Set();
  const subjects = new Set();
  const projects = new Set();
  const snrs = new Set();

  records.forEach(r => {
    if (r.trials_lang) langs.add(r.trials_lang);
    if (r.results_subject) subjects.add(r.results_subject);
    if (r.trials_project) projects.add(r.trials_project);
    if (r.trials_snr) snrs.add(r.trials_snr);
  });

  populateSelect("languageSelect", Array.from(langs).sort(), "All Languages");
  populateSelect("subjectSelect", Array.from(subjects).sort((a,b) => Number(a)-Number(b)), "All Subjects");
  populateSelect("projectSelect", Array.from(projects).sort(), "All Projects");
  populateSelect("snrSelect", Array.from(snrs).sort((a,b) => Number(a)-Number(b)), "All SNR Levels");
}

function populateSelect(elemId, items, placeholder) {
  const sel = document.getElementById(elemId);
  if (!sel) return;
  sel.innerHTML = `<option value="">${placeholder}</option>` +
    items.map(item => `<option value="${item}">${item}</option>`).join("");
}

// Apply Filters to Data
function applyFilters() {
  const { searchText, language, subject, project, snr, mismatchedOnly } = state.filters;
  const sText = searchText.toLowerCase();

  state.filteredRecords = state.allRecords.filter(r => {
    if (language && r.trials_lang !== language) return false;
    if (subject && r.results_subject !== subject) return false;
    if (project && r.trials_project !== project) return false;
    if (snr && r.trials_snr !== snr) return false;

    if (mismatchedOnly) {
      const correctCount = parseInt(r.asr_correct_word_count || "0", 10);
      const gtCount = parseInt(r.asr_gt_word_count || "0", 10);
      if (correctCount === gtCount) return false;
    }

    if (sText) {
      const fullRowStr = Object.values(r).join(" ").toLowerCase();
      if (!fullRowStr.includes(sText)) return false;
    }

    return true;
  });

  // Apply sorting if active
  if (state.sortColumn) {
    const col = state.sortColumn;
    const order = state.sortOrder === "asc" ? 1 : -1;
    state.filteredRecords.sort((a, b) => {
      const valA = a[col] || "";
      const valB = b[col] || "";
      const numA = parseFloat(valA);
      const numB = parseFloat(valB);

      if (!isNaN(numA) && !isNaN(numB)) {
        return (numA - numB) * order;
      }
      return valA.localeCompare(valB) * order;
    });
  }

  state.currentPage = 1;
}

// Update UI
function updateUI() {
  renderStatCards();
  renderTableHeader();
  renderTableBody();
  renderPagination();
  feather.replace();
}

// Render Summary Statistics Cards
function renderStatCards() {
  const total = state.filteredRecords.length;
  const subjects = new Set(state.filteredRecords.map(r => r.results_subject).filter(Boolean)).size;
  const projects = new Set(state.filteredRecords.map(r => r.trials_project).filter(Boolean)).size;
  const languages = new Set(state.filteredRecords.map(r => r.trials_lang).filter(Boolean)).size;

  document.getElementById("statTotalRecords").textContent = total.toLocaleString();
  document.getElementById("statUniqueSubjects").textContent = subjects.toLocaleString();
  document.getElementById("statProjects").textContent = projects.toLocaleString();
  document.getElementById("statLanguages").textContent = languages.toLocaleString();
}

// Render Table Header
function renderTableHeader() {
  const headerRow = document.getElementById("tableHeaderRow");
  if (!headerRow) return;

  const activeCols = Object.keys(state.columnVisibility).filter(k => state.columnVisibility[k]);
  
  headerRow.innerHTML = activeCols.map(colKey => {
    const label = getColumnLabel(colKey);
    const isSorted = state.sortColumn === colKey;
    const sortIcon = isSorted ? (state.sortOrder === "asc" ? "chevron-up" : "chevron-down") : "minus";
    
    return `
      <th data-col="${colKey}">
        <div class="th-content">
          <span>${label}</span>
          ${isSorted ? `<i data-feather="${sortIcon}" style="width: 14px; height: 14px; color: var(--primary);"></i>` : ''}
        </div>
      </th>
    `;
  }).join("");

  // Attach header click listeners for sorting
  headerRow.querySelectorAll("th").forEach(th => {
    th.addEventListener("click", () => {
      const colKey = th.getAttribute("data-col");
      if (state.sortColumn === colKey) {
        state.sortOrder = state.sortOrder === "asc" ? "desc" : "asc";
      } else {
        state.sortColumn = colKey;
        state.sortOrder = "asc";
      }
      applyFilters();
      updateUI();
    });
  });

  feather.replace();
}

// Render Table Body
function renderTableBody() {
  const tbody = document.getElementById("tableBody");
  if (!tbody) return;

  const activeCols = Object.keys(state.columnVisibility).filter(k => state.columnVisibility[k]);
  const startIdx = (state.currentPage - 1) * state.pageSize;
  const endIdx = startIdx + state.pageSize;
  const pageRecords = state.filteredRecords.slice(startIdx, endIdx);

  if (pageRecords.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="${activeCols.length}" style="text-align: center; padding: 2rem; color: var(--text-muted);">
          No records match your filters
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = pageRecords.map((r, rowIdx) => {
    const cells = activeCols.map(colKey => {
      const val = r[colKey] || "";

      // SPECIAL CELL RENDERING FOR "SOUND FILE" COLUMN
      if (colKey === "results_reply_filename") {
        const audioFile = val || r.trials_filename || "";
        const targetPhrase = r.trials_answer || r.asr_results || "";
        
        return `
          <td>
            <button class="speaker-btn" data-filename="${audioFile}" data-phrase="${targetPhrase.replace(/"/g, '&quot;')}">
              <i data-feather="volume-2" style="width: 16px; height: 16px;"></i>
              <span>Play</span>
            </button>
          </td>
        `;
      }

      // Render SNR level badge
      if (colKey === "trials_snr") {
        return `<td><span class="badge badge-snr">${val} dB</span></td>`;
      }

      // Truncate long text strings (e.g. ASR results)
      if (val.length > 75) {
        const truncated = val.substring(0, 75) + "…";
        return `<td><span title="${val.replace(/"/g, '&quot;')}">${truncated}</span></td>`;
      }

      return `<td>${val}</td>`;
    }).join("");

    return `<tr>${cells}</tr>`;
  }).join("");

  // Attach speaker button play listeners
  tbody.querySelectorAll(".speaker-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const filename = btn.getAttribute("data-filename");
      const phrase = btn.getAttribute("data-phrase");
      audioController.play(filename, btn, phrase);
    });
  });

  feather.replace();
}

// Render Pagination Bar Controls
function renderPagination() {
  const total = state.filteredRecords.length;
  const start = total === 0 ? 0 : (state.currentPage - 1) * state.pageSize + 1;
  const end = Math.min(state.currentPage * state.pageSize, total);

  document.getElementById("showingCount").textContent = `Showing ${total} records`;
  document.getElementById("paginationSummary").textContent = `Showing ${start} to ${end} of ${total}`;

  const totalPages = Math.ceil(total / state.pageSize) || 1;
  const controlsContainer = document.getElementById("paginationControls");
  if (!controlsContainer) return;

  let btnsHtml = `
    <button class="page-btn" id="prevPageBtn" ${state.currentPage === 1 ? "disabled" : ""}>
      <i data-feather="chevron-left" style="width: 16px; height: 16px;"></i>
    </button>
  `;

  // Render Page Number Buttons (Max 5 buttons around current page)
  let startPage = Math.max(1, state.currentPage - 2);
  let endPage = Math.min(totalPages, startPage + 4);
  if (endPage - startPage < 4) {
    startPage = Math.max(1, endPage - 4);
  }

  for (let p = startPage; p <= endPage; p++) {
    btnsHtml += `
      <button class="page-btn ${p === state.currentPage ? 'active' : ''}" data-page="${p}">
        ${p}
      </button>
    `;
  }

  btnsHtml += `
    <button class="page-btn" id="nextPageBtn" ${state.currentPage === totalPages ? "disabled" : ""}>
      <i data-feather="chevron-right" style="width: 16px; height: 16px;"></i>
    </button>
  `;

  controlsContainer.innerHTML = btnsHtml;

  // Pagination click handlers
  controlsContainer.querySelectorAll(".page-btn[data-page]").forEach(b => {
    b.addEventListener("click", () => {
      state.currentPage = parseInt(b.getAttribute("data-page"), 10);
      updateUI();
    });
  });

  const prevBtn = document.getElementById("prevPageBtn");
  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      if (state.currentPage > 1) {
        state.currentPage--;
        updateUI();
      }
    });
  }

  const nextBtn = document.getElementById("nextPageBtn");
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      if (state.currentPage < totalPages) {
        state.currentPage++;
        updateUI();
      }
    });
  }

  feather.replace();
}

// Restore state from URL query parameters
function restoreStateFromURL() {
  const params = new URLSearchParams(window.location.search);
  
  if (params.has("search")) state.filters.searchText = params.get("search");
  if (params.has("lang")) state.filters.language = params.get("lang");
  if (params.has("subject")) state.filters.subject = params.get("subject");
  if (params.has("project")) state.filters.project = params.get("project");
  if (params.has("snr")) state.filters.snr = params.get("snr");
  if (params.has("mismatched")) state.filters.mismatchedOnly = params.get("mismatched") === "true";

  document.getElementById("searchInput").value = state.filters.searchText;
  document.getElementById("mismatchedOnlyCheck").checked = state.filters.mismatchedOnly;

  if (params.has("cols")) {
    const visibleList = params.get("cols").split(",");
    Object.keys(state.columnVisibility).forEach(key => {
      state.columnVisibility[key] = visibleList.includes(key);
    });
    renderColumnToggles();
  }
}

// Sync state to URL for Share functionality
function getShareableURL() {
  const url = new URL(window.location.origin + window.location.pathname);
  const params = url.searchParams;

  if (state.filters.searchText) params.set("search", state.filters.searchText);
  if (state.filters.language) params.set("lang", state.filters.language);
  if (state.filters.subject) params.set("subject", state.filters.subject);
  if (state.filters.project) params.set("project", state.filters.project);
  if (state.filters.snr) params.set("snr", state.filters.snr);
  if (state.filters.mismatchedOnly) params.set("mismatched", "true");

  const visibleCols = Object.keys(state.columnVisibility).filter(k => state.columnVisibility[k]);
  if (visibleCols.length > 0) {
    params.set("cols", visibleCols.join(","));
  }

  return url.toString();
}

// Toast Notifications
function showToast(message) {
  const container = document.getElementById("toastContainer");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerHTML = `<i data-feather="check-circle" style="width: 16px; height: 16px;"></i><span>${message}</span>`;
  container.appendChild(toast);
  feather.replace();

  setTimeout(() => {
    toast.remove();
  }, 3000);
}

// Event Listeners Setup
function setupEventListeners() {
  // Search input
  document.getElementById("searchInput").addEventListener("input", (e) => {
    state.filters.searchText = e.target.value;
    applyFilters();
    updateUI();
  });

  // Dropdown filters
  document.getElementById("languageSelect").addEventListener("change", (e) => {
    state.filters.language = e.target.value;
    applyFilters();
    updateUI();
  });

  document.getElementById("subjectSelect").addEventListener("change", (e) => {
    state.filters.subject = e.target.value;
    applyFilters();
    updateUI();
  });

  document.getElementById("projectSelect").addEventListener("change", (e) => {
    state.filters.project = e.target.value;
    applyFilters();
    updateUI();
  });

  document.getElementById("snrSelect").addEventListener("change", (e) => {
    state.filters.snr = e.target.value;
    applyFilters();
    updateUI();
  });

  document.getElementById("mismatchedOnlyCheck").addEventListener("change", (e) => {
    state.filters.mismatchedOnly = e.target.checked;
    applyFilters();
    updateUI();
  });

  // Clear filters
  document.getElementById("clearFiltersBtn").addEventListener("click", () => {
    state.filters = {
      searchText: "",
      language: "",
      subject: "",
      project: "",
      snr: "",
      mismatchedOnly: false
    };
    document.getElementById("searchInput").value = "";
    document.getElementById("languageSelect").value = "";
    document.getElementById("subjectSelect").value = "";
    document.getElementById("projectSelect").value = "";
    document.getElementById("snrSelect").value = "";
    document.getElementById("mismatchedOnlyCheck").checked = false;

    applyFilters();
    updateUI();
  });

  // Reset columns
  document.getElementById("resetColsBtn").addEventListener("click", () => {
    initColumnVisibility();
    renderTableHeader();
    renderTableBody();
  });

  // Theme Toggle
  document.getElementById("themeToggleBtn").addEventListener("click", () => {
    state.theme = state.theme === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", state.theme);
    localStorage.setItem("theme", state.theme);
    
    const icon = document.querySelector("#themeToggleBtn i");
    if (icon) {
      icon.setAttribute("data-feather", state.theme === "light" ? "moon" : "sun");
      feather.replace();
    }
  });

  // Set initial theme attribute
  document.documentElement.setAttribute("data-theme", state.theme);

  // Share Button
  document.getElementById("shareBtn").addEventListener("click", () => {
    const shareUrl = getShareableURL();
    navigator.clipboard.writeText(shareUrl).then(() => {
      showToast("Dashboard URL copied to clipboard!");
    }).catch(() => {
      showToast("Failed to copy URL to clipboard");
    });
  });

  // Load CSV Modal
  const modal = document.getElementById("csvModal");
  document.getElementById("loadCsvBtn").addEventListener("click", () => {
    modal.classList.add("active");
  });
  document.getElementById("closeCsvModalBtn").addEventListener("click", () => {
    modal.classList.remove("active");
  });

  // Load CSV from URL
  document.getElementById("loadFromUrlBtn").addEventListener("click", async () => {
    const urlInput = document.getElementById("csvUrlInput").value.trim();
    if (!urlInput) return;

    try {
      showToast("Fetching CSV from URL...");
      const res = await fetch('/api/csv-proxy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: urlInput })
      });
      const data = await res.json();
      if (data.success) {
        state.allRecords = parseCSV(data.data);
        state.dataSourceName = urlInput;
        document.getElementById("sourceText").textContent = `Source: ${urlInput}`;
        initColumnVisibility();
        populateDropdowns();
        applyFilters();
        updateUI();
        modal.classList.remove("active");
        showToast("CSV data loaded successfully!");
      } else {
        throw new Error(data.error);
      }
    } catch (err) {
      showToast("Failed to load CSV: " + err.message);
    }
  });

  // File Upload / Dropzone
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");

  dropZone.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) handleFile(file);
  });

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.style.borderColor = "var(--primary)";
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.style.borderColor = "var(--border-color)";
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.style.borderColor = "var(--border-color)";
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  });

  function handleFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target.result;
      state.allRecords = parseCSV(content);
      state.dataSourceName = `File: ${file.name}`;
      document.getElementById("sourceText").textContent = `Source: ${state.dataSourceName}`;
      initColumnVisibility();
      populateDropdowns();
      applyFilters();
      updateUI();
      modal.classList.remove("active");
      showToast(`Loaded ${file.name} successfully!`);
    };
    reader.readAsText(file);
  }
}

// Start application on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  initData();
});
