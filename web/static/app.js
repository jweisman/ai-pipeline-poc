"use strict";

const STAGE_KEYS = ["course_info", "modules", "items", "assemble", "write"];

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
  modelRow: document.getElementById("model-row"),
  modelSelect: document.getElementById("model-select"),
  modelHint: document.getElementById("model-hint"),
};

let activeSource = null;

// ---------------------------------------------------------------------------
// Backend selector
// ---------------------------------------------------------------------------

const BACKEND_KEY = "ai-pipeline-poc.backend";
const modelKey = (backend) => `ai-pipeline-poc.model.${backend}`;

// All three backends now use a per-run model selector. UI selection wins
// over each backend's *_DEFAULT_MODEL env var and (for anthropic) the YAML.
const MODEL_BACKENDS = new Set(["anthropic", "openai", "agai"]);

const MODEL_ENDPOINT = {
  anthropic: "/anthropic/models",
  openai: "/openai/models",
  agai: "/agai/models",
};

const DEFAULT_MODEL_ATTR = {
  anthropic: "anthropicDefaultModel",
  openai: "openaiDefaultModel",
  agai: "agaiDefaultModel",
};

const backendState = {
  backend: localStorage.getItem(BACKEND_KEY)
    || els.backendSection.dataset.defaultBackend
    || "anthropic",
  // Per-backend cache of which model the user picked, plus whether we've
  // already fetched the model list this session.
  selectedModel: {
    anthropic: localStorage.getItem(modelKey("anthropic")) || "",
    openai: localStorage.getItem(modelKey("openai")) || "",
    agai: localStorage.getItem(modelKey("agai")) || "",
  },
  modelsLoaded: { anthropic: false, openai: false, agai: false },
};

function setBackend(backend, { persist = true } = {}) {
  backendState.backend = backend;
  if (persist) localStorage.setItem(BACKEND_KEY, backend);

  for (const btn of document.querySelectorAll(".seg-btn")) {
    const active = btn.dataset.backend === backend;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-checked", active ? "true" : "false");
  }

  const usesSelector = MODEL_BACKENDS.has(backend);
  els.modelRow.classList.toggle("hidden", !usesSelector);
  if (usesSelector) {
    if (!backendState.modelsLoaded[backend]) {
      loadModels(backend);
    } else {
      // Re-render so the dropdown reflects the per-backend selection.
      // (No-op if already rendered for this backend; cheap enough to redo.)
      renderCurrentBackendModels();
    }
  }
}

let lastRendered = { backend: null, models: null };

async function loadModels(backend) {
  els.modelHint.textContent = "";
  els.modelSelect.innerHTML = "";
  const loading = document.createElement("option");
  loading.value = "";
  loading.textContent = "Loading models…";
  els.modelSelect.appendChild(loading);

  try {
    const res = await fetch(MODEL_ENDPOINT[backend]);
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`${res.status}: ${txt}`);
    }
    const data = await res.json();
    const models = data.models || [];
    backendState.modelsLoaded[backend] = true;
    lastRendered = { backend, models };
    populateModelSelect(backend, models);
  } catch (e) {
    els.modelSelect.innerHTML = "";
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = `(failed to load ${backend} models)`;
    els.modelSelect.appendChild(opt);
    els.modelHint.textContent = String(e.message || e);
  }
}

function renderCurrentBackendModels() {
  if (lastRendered.backend === backendState.backend && lastRendered.models) {
    populateModelSelect(lastRendered.backend, lastRendered.models);
  }
}

function populateModelSelect(backend, models) {
  els.modelSelect.innerHTML = "";
  if (!models.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "(no models returned)";
    els.modelSelect.appendChild(opt);
    return;
  }

  const fallback =
    els.backendSection.dataset[DEFAULT_MODEL_ATTR[backend]] || models[0].id;
  const desired = backendState.selectedModel[backend] || fallback;

  for (const m of models) {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent =
      m.display && m.display !== m.id ? `${m.display} (${m.id})` : m.id;
    if (m.id === desired) opt.selected = true;
    els.modelSelect.appendChild(opt);
  }
  // If `desired` wasn't in the list, the browser auto-selects index 0; sync
  // state back so the persisted value reflects what's actually shown.
  backendState.selectedModel[backend] = els.modelSelect.value;
  localStorage.setItem(modelKey(backend), els.modelSelect.value);
}

els.modelSelect.addEventListener("change", () => {
  const b = backendState.backend;
  if (!MODEL_BACKENDS.has(b)) return;
  backendState.selectedModel[b] = els.modelSelect.value;
  localStorage.setItem(modelKey(b), els.modelSelect.value);
});

for (const btn of document.querySelectorAll(".seg-btn")) {
  btn.addEventListener("click", () => setBackend(btn.dataset.backend));
}

setBackend(backendState.backend, { persist: false });

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
    const body = { syllabus: syllabusName, backend: backendState.backend };
    if (MODEL_BACKENDS.has(backendState.backend)) {
      const m = backendState.selectedModel[backendState.backend];
      if (m) body.model = m;
    }
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
  showOnly(els.picker);
});
