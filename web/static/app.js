"use strict";

const STAGE_KEYS = ["course_info", "modules", "items", "assemble", "write"];
const QC_STAGE_KEYS = ["qc_load", "qc_checks", "qc_judge", "qc_write"];

const els = {
  workflow: document.getElementById("workflow"),
  picker: document.getElementById("picker-section"),
  running: document.getElementById("running-section"),
  runningSyllabus: document.getElementById("running-syllabus"),
  progressFill: document.getElementById("progress-fill"),
  progressLabel: document.getElementById("progress-label"),
  logFeed: document.getElementById("log-feed"),
  errorSection: document.getElementById("error-section"),
  errorMessage: document.getElementById("error-message"),
  errorBack: document.getElementById("error-back"),
  resultSection: document.getElementById("result-section"),
  resultBody: document.getElementById("result-body"),
  resultBack: document.getElementById("result-back"),
  downloadJson: document.getElementById("download-json"),
  backendSection: document.getElementById("backend-section"),
  modelSelect: document.getElementById("model-select"),
  modelHint: document.getElementById("model-hint"),
  // QC
  qcSection: document.getElementById("qc-section"),
  qcWorkflow: document.getElementById("qc-workflow"),
  qcRunning: document.getElementById("qc-running"),
  qcProgressFill: document.getElementById("qc-progress-fill"),
  qcProgressLabel: document.getElementById("qc-progress-label"),
  qcLogFeed: document.getElementById("qc-log-feed"),
  qcReport: document.getElementById("qc-report"),
  qcExisting: document.getElementById("qc-existing"),
  qcExistingStatus: document.getElementById("qc-existing-status"),
  qcExistingMeta: document.getElementById("qc-existing-meta"),
  qcShowExisting: document.getElementById("qc-show-existing"),
  qcRunBtn: document.getElementById("run-qc-btn"),
  qcUseJudge: document.getElementById("qc-use-judge"),
  qcJudgeRow: document.getElementById("qc-judge-row"),
  qcJudgeModel: document.getElementById("qc-judge-model"),
  qcJudgeHint: document.getElementById("qc-judge-row-hint"),
};

let activeSource = null;
let activeQcSource = null;
let currentSyllabus = null;

// ---------------------------------------------------------------------------
// Backend selectors (inference + judge)
//
// We have two selectors on the page that do exactly the same thing — pick a
// backend and a model — but are independent: the main one drives extraction,
// the QC-panel one drives the LLM-as-judge call. They share a model-list
// cache (a model list is a property of a backend, not of the selector) but
// keep separate localStorage state so the user's two choices persist.
// ---------------------------------------------------------------------------

const MODEL_BACKENDS = new Set(["anthropic", "openai", "agai"]);

const MODEL_ENDPOINT = {
  anthropic: "/anthropic/models",
  openai: "/openai/models",
  agai: "/agai/models",
};

// Cache populated lazily from /<backend>/models. Shared across selectors.
const SHARED_MODEL_CACHE = { anthropic: null, openai: null, agai: null };

function complementaryBackend(backend) {
  // First-load default for the judge — opposite of the inference family.
  // AGAI is heavily OpenAI-flavored (gpt_*, llama_*); pair it with anthropic
  // so the judge isn't from the same family by default.
  if (backend === "anthropic") return "openai";
  return "anthropic";
}

function createBackendSelector({
  segBtns,
  modelRow,           // optional element to hide/show — null means "always shown"
  modelSelect,
  modelHint,          // optional
  storagePrefix,
  defaultBackend,
  defaultModelByBackend,
}) {
  const state = {
    backend:
      localStorage.getItem(`${storagePrefix}.backend`) || defaultBackend,
    selectedModel: {
      anthropic: localStorage.getItem(`${storagePrefix}.model.anthropic`) || "",
      openai: localStorage.getItem(`${storagePrefix}.model.openai`) || "",
      agai: localStorage.getItem(`${storagePrefix}.model.agai`) || "",
    },
  };

  function setBackend(backend, { persist = true } = {}) {
    state.backend = backend;
    if (persist) localStorage.setItem(`${storagePrefix}.backend`, backend);

    for (const btn of segBtns) {
      const active = btn.dataset.backend === backend;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-checked", active ? "true" : "false");
    }

    if (modelRow) {
      modelRow.classList.toggle("hidden", !MODEL_BACKENDS.has(backend));
    }
    if (MODEL_BACKENDS.has(backend)) {
      if (SHARED_MODEL_CACHE[backend]) {
        populateModelSelect(backend);
      } else {
        loadModels(backend);
      }
    }
  }

  async function loadModels(backend) {
    if (modelHint) modelHint.textContent = "";
    modelSelect.innerHTML = "";
    const loading = document.createElement("option");
    loading.value = "";
    loading.textContent = "Loading models…";
    modelSelect.appendChild(loading);

    try {
      const res = await fetch(MODEL_ENDPOINT[backend]);
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`${res.status}: ${txt}`);
      }
      const data = await res.json();
      SHARED_MODEL_CACHE[backend] = data.models || [];
      if (state.backend === backend) populateModelSelect(backend);
    } catch (e) {
      modelSelect.innerHTML = "";
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = `(failed to load ${backend} models)`;
      modelSelect.appendChild(opt);
      if (modelHint) modelHint.textContent = String(e.message || e);
    }
  }

  function populateModelSelect(backend) {
    const models = SHARED_MODEL_CACHE[backend] || [];
    modelSelect.innerHTML = "";
    if (!models.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(no models returned)";
      modelSelect.appendChild(opt);
      return;
    }

    const fallback = defaultModelByBackend[backend] || models[0].id;
    const desired = state.selectedModel[backend] || fallback;

    for (const m of models) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent =
        m.display && m.display !== m.id ? `${m.display} (${m.id})` : m.id;
      if (m.id === desired) opt.selected = true;
      modelSelect.appendChild(opt);
    }
    state.selectedModel[backend] = modelSelect.value;
    localStorage.setItem(`${storagePrefix}.model.${backend}`, modelSelect.value);
  }

  modelSelect.addEventListener("change", () => {
    const b = state.backend;
    if (!MODEL_BACKENDS.has(b)) return;
    state.selectedModel[b] = modelSelect.value;
    localStorage.setItem(`${storagePrefix}.model.${b}`, modelSelect.value);
  });
  for (const btn of segBtns) {
    btn.addEventListener("click", () => setBackend(btn.dataset.backend));
  }

  setBackend(state.backend, { persist: false });

  return {
    getBackend: () => state.backend,
    getModel: () => state.selectedModel[state.backend] || "",
    setBackend,
  };
}

const _backendDefaults = {
  anthropic: els.backendSection.dataset.anthropicDefaultModel,
  openai: els.backendSection.dataset.openaiDefaultModel,
  agai: els.backendSection.dataset.agaiDefaultModel,
};

const inferenceSelector = createBackendSelector({
  segBtns: els.backendSection.querySelectorAll(".seg-btn"),
  modelRow: null, // single-row layout — model dropdown lives next to the segmented buttons
  modelSelect: els.modelSelect,
  modelHint: els.modelHint,
  storagePrefix: "ai-pipeline-poc",
  defaultBackend: els.backendSection.dataset.defaultBackend || "anthropic",
  defaultModelByBackend: _backendDefaults,
});

// Judge defaults to a different family from inference on first load — the
// whole point of a separate judge model is to avoid self-preference bias.
// Once the user picks one, we honor their choice and don't auto-sync.
const _judgePersisted = localStorage.getItem("ai-pipeline-poc.judge.backend");
const _judgeDefault =
  _judgePersisted || complementaryBackend(inferenceSelector.getBackend());

const judgeSelector = createBackendSelector({
  segBtns: els.qcJudgeRow.querySelectorAll(".seg-btn"),
  modelRow: null, // judge selector is always shown; "Use LLM judge" toggle controls it instead
  modelSelect: els.qcJudgeModel,
  modelHint: els.qcJudgeHint,
  storagePrefix: "ai-pipeline-poc.judge",
  defaultBackend: _judgeDefault,
  defaultModelByBackend: _backendDefaults,
});

function refreshJudgeRowEnabled() {
  // Visual cue when "Use LLM judge" is off — the row stays visible so the
  // user can still see what would run, but it's dimmed and inert.
  els.qcJudgeRow.classList.toggle("disabled", !els.qcUseJudge.checked);
}
els.qcUseJudge.addEventListener("change", refreshJudgeRowEnabled);
refreshJudgeRowEnabled();

// ---------------------------------------------------------------------------
// View transitions
// ---------------------------------------------------------------------------

function showOnly(section) {
  for (const s of [els.picker, els.running, els.errorSection, els.resultSection]) {
    s.classList.toggle("hidden", s !== section);
  }
}

function resetWorkflow() {
  for (const stage of els.workflow.querySelectorAll(".stage")) {
    stage.classList.remove("active", "done", "failed");
  }
}

function applyStageEvent(stageKey, phase) {
  if (!stageKey) return;
  const idx = STAGE_KEYS.indexOf(stageKey);
  if (idx < 0) return;
  const el = els.workflow.querySelector(`.stage[data-stage="${stageKey}"]`);
  if (!el) return;

  if (phase === "start") {
    // Mark every earlier stage as done — handles the case where we somehow
    // missed a "complete" event.
    for (let i = 0; i < idx; i++) {
      const e = els.workflow.querySelector(`.stage[data-stage="${STAGE_KEYS[i]}"]`);
      if (e) { e.classList.remove("active"); e.classList.add("done"); }
    }
    el.classList.remove("done", "failed");
    el.classList.add("active");
    els.progressFill.style.width = `${(idx / STAGE_KEYS.length) * 100}%`;
    els.progressLabel.textContent = stageLabel(stageKey);
  } else if (phase === "complete") {
    el.classList.remove("active");
    el.classList.add("done");
    els.progressFill.style.width = `${((idx + 1) / STAGE_KEYS.length) * 100}%`;
  } else if (phase === "error") {
    el.classList.remove("active", "done");
    el.classList.add("failed");
  }
}

function markAllDone() {
  for (const stage of els.workflow.querySelectorAll(".stage")) {
    stage.classList.remove("active");
    stage.classList.add("done");
  }
  els.progressFill.style.width = "100%";
}

// ---------------------------------------------------------------------------
// Logging UI
// ---------------------------------------------------------------------------

function appendLog(msg, level) {
  const line = document.createElement("span");
  line.className = "log-line";
  if (level === "WARNING") line.classList.add("warn");
  if (level === "ERROR" || level === "CRITICAL") line.classList.add("err");
  const lvl = document.createElement("span");
  lvl.className = "lvl";
  lvl.textContent = (level || "INFO").padEnd(5);
  line.appendChild(lvl);
  line.appendChild(document.createTextNode(msg));
  els.logFeed.appendChild(line);
  els.logFeed.scrollTop = els.logFeed.scrollHeight;
}

// ---------------------------------------------------------------------------
// Run lifecycle
// ---------------------------------------------------------------------------

async function startRun(syllabusName) {
  resetWorkflow();
  els.logFeed.innerHTML = "";
  els.progressFill.style.width = "0%";
  els.progressLabel.textContent = "Starting…";
  els.runningSyllabus.textContent = syllabusName;
  showOnly(els.running);

  let runId;
  try {
    const body = {
      syllabus: syllabusName,
      backend: inferenceSelector.getBackend(),
    };
    const m = inferenceSelector.getModel();
    if (m) body.model = m;
    const res = await fetch("/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Failed to start run (${res.status}): ${text}`);
    }
    runId = (await res.json()).run_id;
  } catch (e) {
    showError(e.message || String(e));
    return;
  }

  if (activeSource) activeSource.close();
  activeSource = new EventSource(`/runs/${runId}/events`);

  activeSource.onmessage = (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }
    handleEvent(data, runId);
  };
  activeSource.onerror = () => {
    // Browser auto-reconnects; we don't want that. Close on stream end.
    if (activeSource && activeSource.readyState === EventSource.CLOSED) {
      activeSource = null;
    }
  };
}

function handleEvent(event, runId) {
  if (event.type === "log") {
    appendLog(event.message, event.level);
  } else if (event.type === "stage") {
    applyStageEvent(event.stage, event.phase);
  } else if (event.type === "status") {
    if (event.status === "done") {
      markAllDone();
      els.progressLabel.textContent = "Done.";
    } else if (event.status === "error") {
      els.progressLabel.textContent = "Failed.";
    }
  } else if (event.type === "result") {
    renderResult(event.data, runId);
  } else if (event.type === "error") {
    showError(event.message);
  }
}

function stageLabel(key) {
  const el = els.workflow.querySelector(`.stage[data-stage="${key}"] .stage-label`);
  return el ? el.textContent : key;
}

function showError(message) {
  if (activeSource) { activeSource.close(); activeSource = null; }
  els.errorMessage.textContent = message;
  showOnly(els.errorSection);
}

// ---------------------------------------------------------------------------
// Result rendering
// ---------------------------------------------------------------------------

function renderResult(data, runId) {
  if (activeSource) { activeSource.close(); activeSource = null; }
  // The presence of a result is itself proof every stage succeeded — make
  // sure the diagram reflects that, even if the final stage's "complete"
  // event was somehow missed.
  markAllDone();
  resetQcSection();
  currentSyllabus = data.source_filename || null;
  els.resultBody.innerHTML = "";

  els.resultBody.appendChild(renderCourseCard(data.course_info, data.source_filename));

  const modulesHeading = document.createElement("h3");
  modulesHeading.className = "section-heading";
  modulesHeading.textContent = `Modules (${data.modules.length})`;
  els.resultBody.appendChild(modulesHeading);

  for (const mod of data.modules) {
    els.resultBody.appendChild(renderModule(mod));
  }

  if (data.unassigned_items && data.unassigned_items.length) {
    const h = document.createElement("h3");
    h.className = "section-heading";
    h.textContent = `Unassigned items (${data.unassigned_items.length})`;
    els.resultBody.appendChild(h);
    const card = document.createElement("div");
    card.className = "module-card";
    card.appendChild(renderItemsTable(data.unassigned_items));
    els.resultBody.appendChild(card);
  }

  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  els.downloadJson.href = URL.createObjectURL(blob);
  const stem = (data.source_filename || "result").replace(/\.[^.]+$/, "");
  els.downloadJson.download = `${stem}.extracted.json`;

  showOnly(els.resultSection);
  loadExistingQcReport(stem).catch(() => {});
}

function renderCourseCard(info, sourceFilename) {
  const card = document.createElement("div");
  card.className = "course-card";

  const title = document.createElement("h3");
  title.className = "course-title";
  title.textContent = info.title || "(untitled course)";
  card.appendChild(title);

  const subtitleParts = [];
  if (info.code) subtitleParts.push(info.code);
  if (info.department) subtitleParts.push(info.department);
  if (info.institution) subtitleParts.push(info.institution);
  if (subtitleParts.length) {
    const sub = document.createElement("div");
    sub.className = "course-subtitle";
    sub.textContent = subtitleParts.join(" · ");
    card.appendChild(sub);
  }

  const meta = document.createElement("div");
  meta.className = "course-meta";
  if (info.level) meta.appendChild(tag(info.level));
  if (info.term) meta.appendChild(tag(info.term));
  if (info.instructors && info.instructors.length) {
    meta.appendChild(tag(info.instructors.join(", "), "muted"));
  }
  if (sourceFilename) meta.appendChild(tag(sourceFilename, "muted"));
  if (meta.children.length) card.appendChild(meta);

  if (info.description) {
    const d = document.createElement("p");
    d.className = "course-description";
    d.textContent = info.description;
    card.appendChild(d);
  }

  if (info.objectives && info.objectives.length) {
    const h = document.createElement("div");
    h.style.marginTop = "12px";
    h.style.fontWeight = "600";
    h.style.fontSize = "13px";
    h.textContent = "Course-level objectives";
    card.appendChild(h);

    const ul = document.createElement("ul");
    ul.className = "objectives";
    for (const obj of info.objectives) {
      const li = document.createElement("li");
      li.textContent = obj;
      ul.appendChild(li);
    }
    card.appendChild(ul);
  }

  return card;
}

function tag(text, variant) {
  const el = document.createElement("span");
  el.className = `tag${variant ? " " + variant : ""}`;
  el.textContent = text;
  return el;
}

function renderModule(mod) {
  const card = document.createElement("div");
  card.className = "module-card";

  const header = document.createElement("div");
  header.className = "module-header";
  const idx = document.createElement("span");
  idx.className = "module-index";
  idx.textContent = `Module ${mod.order_index}`;
  const title = document.createElement("h4");
  title.className = "module-title";
  title.textContent = mod.title;
  header.appendChild(idx);
  header.appendChild(title);
  card.appendChild(header);

  if (mod.objectives && mod.objectives.length) {
    const ul = document.createElement("ul");
    ul.className = "module-objectives";
    for (const o of mod.objectives) {
      const li = document.createElement("li");
      li.textContent = o;
      ul.appendChild(li);
    }
    card.appendChild(ul);
  }

  card.appendChild(renderItemsTable(mod.items || []));
  return card;
}

function renderItemsTable(items) {
  if (!items || !items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-row";
    empty.textContent = "No items.";
    return empty;
  }
  const table = document.createElement("table");
  table.className = "items-table";
  table.innerHTML = `
    <thead>
      <tr>
        <th style="width: 4%">#</th>
        <th style="width: 12%">Type</th>
        <th>Title</th>
        <th style="width: 14%">Format</th>
        <th style="width: 8%">Points</th>
        <th style="width: 18%">Due</th>
      </tr>
    </thead>
  `;
  const tbody = document.createElement("tbody");
  for (const item of items) {
    const tr = document.createElement("tr");

    const cells = [
      String(item.order_index ?? ""),
      null,  // type — set below
      null,  // title — set below
      item.material_format || item.assignment_format || "",
      item.points != null ? String(item.points) : "",
      item.due || "",
    ];

    cells.forEach((c, i) => {
      const td = document.createElement("td");
      if (i === 1) {
        const span = document.createElement("span");
        span.className = `item-type ${item.item_type}`;
        span.textContent = item.item_type;
        td.appendChild(span);
      } else if (i === 2) {
        const strong = document.createElement("div");
        strong.style.fontWeight = "600";
        strong.textContent = item.title || "(untitled)";
        td.appendChild(strong);
        if (item.description) {
          const desc = document.createElement("div");
          desc.className = "item-format";
          desc.textContent = item.description;
          td.appendChild(desc);
        } else if (item.citation) {
          const cite = document.createElement("div");
          cite.className = "item-format";
          cite.textContent = item.citation;
          td.appendChild(cite);
        }
      } else if (i === 3) {
        td.className = "item-format";
        td.textContent = c;
      } else if (i === 4) {
        td.className = "item-points";
        td.textContent = c;
      } else {
        td.textContent = c;
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  return table;
}

// ---------------------------------------------------------------------------
// QC lifecycle
// ---------------------------------------------------------------------------

function resetQcSection() {
  if (activeQcSource) { activeQcSource.close(); activeQcSource = null; }
  els.qcExisting.classList.add("hidden");
  els.qcRunning.classList.add("hidden");
  els.qcReport.classList.add("hidden");
  els.qcReport.innerHTML = "";
  els.qcLogFeed.innerHTML = "";
  els.qcProgressFill.style.width = "0%";
  els.qcProgressLabel.textContent = "Starting QC…";
  for (const stage of els.qcWorkflow.querySelectorAll(".stage")) {
    stage.classList.remove("active", "done", "failed", "skipped");
  }
}

async function loadExistingQcReport(stem) {
  try {
    const res = await fetch(`/qc-report/${encodeURIComponent(stem)}`);
    if (res.status === 404) return;
    if (!res.ok) return;
    const report = await res.json();
    showExistingQcSummary(report);
  } catch {
    // Silent — absence of a prior report is the common case.
  }
}

function showExistingQcSummary(report) {
  els.qcExistingStatus.textContent = report.overall_status;
  els.qcExistingStatus.className = `qc-status-badge ${report.overall_status}`;
  const detCounts = countByStatus(report.deterministic);
  const judgeStatuses = (report.judge || []).map((j) => j.status).join(", ") || "no judge";
  els.qcExistingMeta.textContent =
    `${detCounts.fail} fail · ${detCounts.warn} warn · ${detCounts.pass} pass · judge: ${judgeStatuses}`;
  els.qcExisting.dataset.report = JSON.stringify(report);
  els.qcExisting.classList.remove("hidden");
}

function countByStatus(checks) {
  const out = { pass: 0, warn: 0, fail: 0 };
  for (const c of checks || []) {
    if (out[c.status] != null) out[c.status]++;
  }
  return out;
}

async function startQc() {
  if (!currentSyllabus) return;
  resetQcSection();
  els.qcRunning.classList.remove("hidden");

  const useJudge = els.qcUseJudge.checked;
  // The judge stage is just dimmed if it'll be skipped — saves the user
  // from wondering why "Judge" never lights up.
  const judgeStageEl = els.qcWorkflow.querySelector('.stage[data-qc-stage="qc_judge"]');
  if (judgeStageEl) judgeStageEl.classList.toggle("skipped", !useJudge);

  let qcId;
  try {
    const body = {
      syllabus: currentSyllabus,
      use_judge: useJudge,
      backend: inferenceSelector.getBackend(),
      judge_backend: judgeSelector.getBackend(),
    };
    const m = inferenceSelector.getModel();
    if (m) body.model = m;
    const jm = judgeSelector.getModel();
    if (jm) body.judge_model = jm;
    const res = await fetch("/qc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Failed to start QC (${res.status}): ${text}`);
    }
    qcId = (await res.json()).qc_id;
  } catch (e) {
    els.qcProgressLabel.textContent = "Failed to start.";
    els.qcReport.classList.remove("hidden");
    els.qcReport.innerHTML = `<div class="qc-error">${escapeHtml(e.message || String(e))}</div>`;
    return;
  }

  if (activeQcSource) activeQcSource.close();
  activeQcSource = new EventSource(`/qc/${qcId}/events`);
  activeQcSource.onmessage = (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }
    handleQcEvent(data, useJudge);
  };
  activeQcSource.onerror = () => {
    if (activeQcSource && activeQcSource.readyState === EventSource.CLOSED) {
      activeQcSource = null;
    }
  };
}

function handleQcEvent(event, useJudge) {
  if (event.type === "log") {
    appendQcLog(event.message, event.level);
  } else if (event.type === "stage") {
    applyQcStageEvent(event.stage, event.phase);
  } else if (event.type === "status") {
    if (event.status === "done") {
      markAllQcDone(useJudge);
      els.qcProgressLabel.textContent = "Done.";
    } else if (event.status === "error") {
      els.qcProgressLabel.textContent = "Failed.";
    }
  } else if (event.type === "result") {
    renderQcReport(event.data);
  } else if (event.type === "error") {
    els.qcReport.classList.remove("hidden");
    els.qcReport.innerHTML = `<div class="qc-error">${escapeHtml(event.message)}</div>`;
  }
}

function applyQcStageEvent(stageKey, phase) {
  if (!stageKey) return;
  const idx = QC_STAGE_KEYS.indexOf(stageKey);
  if (idx < 0) return;
  const el = els.qcWorkflow.querySelector(`.stage[data-qc-stage="${stageKey}"]`);
  if (!el) return;

  if (phase === "start") {
    for (let i = 0; i < idx; i++) {
      const e = els.qcWorkflow.querySelector(`.stage[data-qc-stage="${QC_STAGE_KEYS[i]}"]`);
      if (e && !e.classList.contains("skipped")) {
        e.classList.remove("active");
        e.classList.add("done");
      }
    }
    el.classList.remove("done", "failed", "skipped");
    el.classList.add("active");
    els.qcProgressFill.style.width = `${(idx / QC_STAGE_KEYS.length) * 100}%`;
    els.qcProgressLabel.textContent = qcStageLabel(stageKey);
  } else if (phase === "complete") {
    el.classList.remove("active");
    el.classList.add("done");
    els.qcProgressFill.style.width = `${((idx + 1) / QC_STAGE_KEYS.length) * 100}%`;
  } else if (phase === "error") {
    el.classList.remove("active", "done");
    el.classList.add("failed");
  }
}

function qcStageLabel(key) {
  const el = els.qcWorkflow.querySelector(`.stage[data-qc-stage="${key}"] .stage-label`);
  return el ? el.textContent : key;
}

function markAllQcDone(useJudge) {
  for (const stage of els.qcWorkflow.querySelectorAll(".stage")) {
    if (stage.classList.contains("skipped")) continue;
    if (!useJudge && stage.dataset.qcStage === "qc_judge") continue;
    stage.classList.remove("active");
    stage.classList.add("done");
  }
  els.qcProgressFill.style.width = "100%";
}

function appendQcLog(msg, level) {
  const line = document.createElement("span");
  line.className = "log-line";
  if (level === "WARNING") line.classList.add("warn");
  if (level === "ERROR" || level === "CRITICAL") line.classList.add("err");
  const lvl = document.createElement("span");
  lvl.className = "lvl";
  lvl.textContent = (level || "INFO").padEnd(5);
  line.appendChild(lvl);
  line.appendChild(document.createTextNode(msg));
  els.qcLogFeed.appendChild(line);
  els.qcLogFeed.scrollTop = els.qcLogFeed.scrollHeight;
}

function renderQcReport(report) {
  if (activeQcSource) { activeQcSource.close(); activeQcSource = null; }
  els.qcReport.innerHTML = "";
  els.qcReport.classList.remove("hidden");

  // Header: status badge + summary line
  const header = document.createElement("div");
  header.className = "qc-report-header";
  const badge = document.createElement("span");
  badge.className = `qc-status-badge ${report.overall_status}`;
  badge.textContent = report.overall_status;
  header.appendChild(badge);

  const summary = document.createElement("span");
  summary.className = "qc-report-summary";
  const detCounts = countByStatus(report.deterministic);
  const judgeBits = (report.judge || []).map((j) => `${j.status}${j.score != null ? ` (${j.score.toFixed(2)})` : ""}`);
  summary.textContent =
    `Deterministic: ${detCounts.pass} pass / ${detCounts.warn} warn / ${detCounts.fail} fail` +
    (judgeBits.length ? ` · Judge: ${judgeBits.join(", ")}` : " · Judge: skipped") +
    (report.needs_human_review ? " · needs human review" : "");
  header.appendChild(summary);

  els.qcReport.appendChild(header);

  // Deterministic checks
  const detSection = document.createElement("div");
  detSection.className = "qc-checks";
  const detHeader = document.createElement("h4");
  detHeader.className = "qc-subheading";
  detHeader.textContent = "Deterministic checks";
  detSection.appendChild(detHeader);
  for (const c of report.deterministic || []) {
    detSection.appendChild(renderQcCheckRow(c));
  }
  els.qcReport.appendChild(detSection);

  // Judge results
  if (report.judge && report.judge.length) {
    const jSection = document.createElement("div");
    jSection.className = "qc-judge";
    const jHeader = document.createElement("h4");
    jHeader.className = "qc-subheading";
    jHeader.textContent = "LLM judge";
    jSection.appendChild(jHeader);
    for (const j of report.judge) {
      jSection.appendChild(renderQcJudgeBlock(j));
    }
    els.qcReport.appendChild(jSection);
  }

  // Flagged fields list (deduped union)
  if (report.fields_flagged && report.fields_flagged.length) {
    const ff = document.createElement("div");
    ff.className = "qc-flagged";
    const ffH = document.createElement("h4");
    ffH.className = "qc-subheading";
    ffH.textContent = `Flagged fields (${report.fields_flagged.length})`;
    ff.appendChild(ffH);
    const ul = document.createElement("ul");
    ul.className = "qc-flagged-list";
    for (const f of report.fields_flagged) {
      const li = document.createElement("li");
      li.textContent = f;
      ul.appendChild(li);
    }
    ff.appendChild(ul);
    els.qcReport.appendChild(ff);
  }

  // Downloads
  const dl = document.createElement("div");
  dl.className = "qc-downloads";
  const reportBlob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
  const reportLink = document.createElement("a");
  reportLink.className = "btn ghost";
  reportLink.href = URL.createObjectURL(reportBlob);
  const stem = (report.source_filename || "result").replace(/\.[^.]+$/, "");
  reportLink.download = `${stem}.qc.json`;
  reportLink.textContent = "Download QC JSON";
  dl.appendChild(reportLink);

  if (report.needs_human_review) {
    const note = document.createElement("span");
    note.className = "qc-review-note";
    note.textContent = `HITL review task written to qc_output/${stem}.review.json`;
    dl.appendChild(note);
  }
  els.qcReport.appendChild(dl);
}

function renderQcCheckRow(check) {
  const row = document.createElement("div");
  row.className = `qc-check-row ${check.status}`;
  const status = document.createElement("span");
  status.className = `qc-status-badge ${check.status}`;
  status.textContent = check.status;
  const name = document.createElement("span");
  name.className = "qc-check-name";
  name.textContent = check.name;
  const msg = document.createElement("span");
  msg.className = "qc-check-message";
  msg.textContent = check.message;
  row.appendChild(status);
  row.appendChild(name);
  row.appendChild(msg);
  if (check.flagged_fields && check.flagged_fields.length && check.status !== "pass") {
    const fields = document.createElement("div");
    fields.className = "qc-check-fields";
    fields.textContent = check.flagged_fields.join(" · ");
    row.appendChild(fields);
  }
  return row;
}

function renderQcJudgeBlock(judge) {
  const block = document.createElement("div");
  block.className = `qc-judge-block ${judge.status}`;
  const head = document.createElement("div");
  head.className = "qc-judge-head";
  const status = document.createElement("span");
  status.className = `qc-status-badge ${judge.status}`;
  status.textContent = judge.status;
  head.appendChild(status);
  if (judge.score != null) {
    const score = document.createElement("span");
    score.className = "qc-judge-score";
    score.textContent = `score: ${judge.score.toFixed(2)}`;
    head.appendChild(score);
  }
  if (judge.model) {
    const model = document.createElement("span");
    model.className = "qc-judge-model";
    model.textContent = judge.model;
    head.appendChild(model);
  }
  block.appendChild(head);

  const rationale = document.createElement("p");
  rationale.className = "qc-judge-rationale";
  rationale.textContent = judge.rationale || "(no rationale returned)";
  block.appendChild(rationale);

  if (judge.flagged_fields && judge.flagged_fields.length) {
    const fields = document.createElement("div");
    fields.className = "qc-judge-fields";
    fields.textContent = "Flagged: " + judge.flagged_fields.join(" · ");
    block.appendChild(fields);
  }
  return block;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

// ---------------------------------------------------------------------------
// Wire up
// ---------------------------------------------------------------------------

document.querySelectorAll(".analyze-btn").forEach((btn) => {
  btn.addEventListener("click", () => startRun(btn.dataset.name));
});

els.errorBack.addEventListener("click", () => {
  resetWorkflow();
  showOnly(els.picker);
});
els.resultBack.addEventListener("click", () => {
  resetWorkflow();
  resetQcSection();
  currentSyllabus = null;
  showOnly(els.picker);
});

els.qcRunBtn.addEventListener("click", () => startQc());
els.qcShowExisting.addEventListener("click", () => {
  const raw = els.qcExisting.dataset.report;
  if (!raw) return;
  try {
    renderQcReport(JSON.parse(raw));
  } catch {}
});
