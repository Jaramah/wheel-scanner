"use strict";

const API = "";
let PROVIDERS = [];
let AGENTS = [];
let PROJECTS = [];
let activeProjectId = null;
const pollers = {}; // runId -> interval

// ---- helpers ---------------------------------------------------------------
async function api(path, opts) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
const el = (id) => document.getElementById(id);
function esc(s) {
  return (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

// ---- tabs ------------------------------------------------------------------
document.querySelectorAll(".tab").forEach((t) => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".view").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    el("view-" + t.dataset.view).classList.add("active");
  });
});

// ---- providers + agent form ------------------------------------------------
async function loadProviders() {
  PROVIDERS = await api("/api/providers");
  const sel = el("provider-select");
  sel.innerHTML = PROVIDERS.map((p) => `<option value="${p.id}">${esc(p.label)}</option>`).join("");
  syncProviderFields();
}
function currentProvider() {
  const id = el("provider-select").value;
  return PROVIDERS.find((p) => p.id === id) || {};
}
function syncProviderFields() {
  const p = currentProvider();
  el("provider-help").textContent = p.help || "";
  el("model-input").value = p.default_model || "";
  el("model-input").placeholder = p.default_model || "model id";
  el("baseurl-row").classList.toggle("hidden", p.id !== "openai_compatible");
  const credRow = el("cred-row");
  credRow.querySelector("span, label");
  credRow.childNodes[0].nodeValue =
    p.cred_kind === "subscription" ? "Subscription key" :
    p.cred_kind === "none" ? "Credential (not required)" : "API key";
}
el("provider-select").addEventListener("change", syncProviderFields);

el("agent-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const msg = el("agent-msg");
  msg.className = "form-msg";
  msg.textContent = "Saving…";
  try {
    await api("/api/agents", {
      method: "POST",
      body: JSON.stringify({
        name: f.name.value,
        provider: f.provider.value,
        model: f.model.value,
        base_url: f.base_url.value,
        credential: f.credential.value,
      }),
    });
    f.reset();
    syncProviderFields();
    msg.className = "form-msg ok";
    msg.textContent = "Agent added.";
    await loadAgents();
  } catch (err) {
    msg.className = "form-msg err";
    msg.textContent = err.message;
  }
});

async function loadAgents() {
  AGENTS = await api("/api/agents");
  el("agent-count").textContent = AGENTS.length;
  const list = el("agent-list");
  if (!AGENTS.length) {
    list.innerHTML = `<li class="empty">No agents yet. Add one on the left.</li>`;
    return;
  }
  list.innerHTML = AGENTS.map((a) => {
    const prov = PROVIDERS.find((p) => p.id === a.provider) || {};
    const badge = prov.api
      ? `<span class="badge api">live API</span>`
      : `<span class="badge demo">demo</span>`;
    const cred = a.has_credential ? `key ${esc(a.credential_hint)}` : "no key";
    return `<li class="agent-item">
      <div class="meta">
        <span class="nm">${esc(a.name)} ${badge}</span>
        <span class="sub">${esc(a.provider_label)} · ${esc(a.model || "")} · ${cred}</span>
      </div>
      <button class="ghost danger" onclick="deleteAgent(${a.id})">Remove</button>
    </li>`;
  }).join("");
}
window.deleteAgent = async (id) => {
  await api(`/api/agents/${id}`, { method: "DELETE" });
  loadAgents();
};

// ---- projects --------------------------------------------------------------
el("project-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  await api("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name: f.name.value, description: f.description.value }),
  });
  f.reset();
  await loadProjects();
});

async function loadProjects() {
  PROJECTS = await api("/api/projects");
  const list = el("project-list");
  if (!PROJECTS.length) {
    list.innerHTML = `<li class="empty">No projects yet.</li>`;
  } else {
    list.innerHTML = PROJECTS.map((p) => `
      <li class="project-item ${p.id === activeProjectId ? "active" : ""}" onclick="selectProject(${p.id})">
        <div class="meta">
          <span class="nm">${esc(p.name)}</span>
          <span class="sub">${p.tasks.length} task(s)</span>
        </div>
        <button class="ghost danger" onclick="event.stopPropagation(); deleteProject(${p.id})">Delete</button>
      </li>`).join("");
  }
  if (activeProjectId && PROJECTS.some((p) => p.id === activeProjectId)) {
    renderProjectDetail();
  }
}
window.deleteProject = async (id) => {
  await api(`/api/projects/${id}`, { method: "DELETE" });
  if (activeProjectId === id) activeProjectId = null;
  el("project-detail").innerHTML = `<span class="muted">Select or create a project to begin.</span>`;
  loadProjects();
};
window.selectProject = (id) => {
  activeProjectId = id;
  loadProjects();
  renderProjectDetail();
};

function renderProjectDetail() {
  const p = PROJECTS.find((x) => x.id === activeProjectId);
  if (!p) return;
  const detail = el("project-detail");
  detail.innerHTML = `
    <h2>${esc(p.name)}</h2>
    <p class="muted">${esc(p.description || "")}</p>
    <form id="task-form" class="stack" style="margin-top:10px">
      <label>Task title <input name="title" placeholder="e.g. Write a rate limiter" required /></label>
      <label>Prompt / spec <textarea name="prompt" rows="3" placeholder="Describe what the agents should build…" required></textarea></label>
      <button type="submit" class="primary">Add task</button>
    </form>
    <div id="tasks"></div>`;
  el("task-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    await api(`/api/projects/${p.id}/tasks`, {
      method: "POST",
      body: JSON.stringify({ title: f.title.value, prompt: f.prompt.value }),
    });
    f.reset();
    await loadProjects();
  });
  renderTasks(p);
}

function renderTasks(project) {
  const wrap = el("tasks");
  if (!project.tasks.length) {
    wrap.innerHTML = `<p class="empty">No tasks yet.</p>`;
    return;
  }
  wrap.innerHTML = project.tasks.map((t) => taskBlock(t)).join("");
  project.tasks.forEach((t) => wireTask(t));
}

function taskBlock(t) {
  const checks = AGENTS.map((a) => `
    <label class="agent-check">
      <input type="checkbox" value="${a.id}" data-task="${t.id}" />
      ${esc(a.name)}
    </label>`).join("") || `<span class="empty">Add agents first (Agents tab).</span>`;
  return `
    <div class="task-block" id="task-${t.id}">
      <h3>${esc(t.title)}</h3>
      <p class="task-prompt">${esc(t.prompt)}</p>
      <div class="assemble">
        <div>
          <div class="muted" style="font-size:12px;margin-bottom:5px">Assemble the team</div>
          <div class="agent-checks">${checks}</div>
        </div>
      </div>
      <div class="run-controls" style="margin-top:12px">
        <label>Mode
          <select id="mode-${t.id}">
            <option value="cross_review">Build + cross-review</option>
            <option value="ensemble">Independent + synthesize</option>
          </select>
        </label>
        <label>Max rounds
          <input id="rounds-${t.id}" type="number" min="1" max="6" value="2" style="width:64px" />
        </label>
        <button class="primary" onclick="startRun(${t.id})">Run collaboration</button>
      </div>
      <div id="runs-${t.id}"></div>
    </div>`;
}

function wireTask(t) {
  // load latest run if any
  api(`/api/tasks/${t.id}/runs`).then((runs) => {
    if (runs.length) renderRun(t.id, runs[0].id);
  });
}

window.startRun = async (taskId) => {
  const agentIds = [...document.querySelectorAll(`input[data-task="${taskId}"]:checked`)].map(
    (c) => Number(c.value)
  );
  if (!agentIds.length) {
    alert("Select at least one agent for this task.");
    return;
  }
  const mode = el(`mode-${taskId}`).value;
  const rounds = Number(el(`rounds-${taskId}`).value) || 2;
  const run = await api(`/api/tasks/${taskId}/runs`, {
    method: "POST",
    body: JSON.stringify({ mode, rounds, agent_ids: agentIds }),
  });
  renderRun(taskId, run.id);
};

async function renderRun(taskId, runId) {
  const wrap = el(`runs-${taskId}`);
  if (!wrap) return;
  const run = await api(`/api/runs/${runId}`);
  wrap.innerHTML = runHtml(run);

  if (run.status === "queued" || run.status === "running") {
    if (!pollers[runId]) {
      pollers[runId] = setInterval(() => renderRun(taskId, runId), 1200);
    }
  } else if (pollers[runId]) {
    clearInterval(pollers[runId]);
    delete pollers[runId];
  }
}

function runHtml(run) {
  const steps = (run.steps || []).map(stepHtml).join("");
  const final =
    run.status === "done" && run.result
      ? `<div class="final"><h4>✓ Final consolidated result</h4><div class="content">${esc(run.result)}</div></div>`
      : run.status === "error"
      ? `<div class="final" style="border-color:#4d1f1f;background:#1d0f0f"><h4 style="color:var(--red)">Run failed</h4><div class="content">${esc(run.error || "")}</div></div>`
      : "";
  return `
    <div class="run">
      <div class="run-head">
        <span class="status ${run.status}">${run.status}</span>
        <span class="muted">${run.mode === "ensemble" ? "Independent + synthesize" : "Build + cross-review"} · up to ${run.rounds} round(s)</span>
      </div>
      ${steps || '<p class="empty">Starting…</p>'}
      ${final}
    </div>`;
}

function stepHtml(s) {
  const role = s.role || "system";
  const initial = (s.agent_name || "S").trim().charAt(0).toUpperCase();
  let verdict = "";
  if (s.kind === "review") {
    verdict =
      s.approved === 1
        ? ` <span class="verdict-approve">✓ approved</span>`
        : ` <span class="verdict-changes">⟳ requested changes</span>`;
  }
  const roundTag = s.round ? `round ${s.round}` : "";
  return `
    <div class="step role-${role}">
      <div class="avatar">${esc(initial)}</div>
      <div class="body">
        <div class="who"><b>${esc(s.agent_name)}</b>
          <span class="kind-tag">${esc(s.kind)} · ${roundTag}</span>${verdict}
        </div>
        <div class="content">${esc(s.content)}</div>
      </div>
    </div>`;
}

// ---- boot ------------------------------------------------------------------
(async function boot() {
  await loadProviders();
  await loadAgents();
  await loadProjects();
})();
