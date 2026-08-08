const state = {
  workspace: null,
  summary: null,
  activeTaskId: null,
  logOffset: 0,
  editingPath: null,
  taskTrigger: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "请求失败，请稍后重试。");
  return data;
}

let toastTimer;
function toast(message, isError = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", isError);
  element.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), 3400);
}

function escapeHtml(value) {
  return value.replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);
}

function renderMarkdown(value) {
  const lines = escapeHtml(value).split("\n");
  let inCode = false;
  let html = "";
  for (const line of lines) {
    if (line.startsWith("```")) { inCode = !inCode; html += inCode ? "<pre><code>" : "</code></pre>"; continue; }
    if (inCode) { html += `${line}\n`; continue; }
    if (/^###\s+/.test(line)) html += `<h3>${line.replace(/^###\s+/, "")}</h3>`;
    else if (/^##\s+/.test(line)) html += `<h2>${line.replace(/^##\s+/, "")}</h2>`;
    else if (/^#\s+/.test(line)) html += `<h1>${line.replace(/^#\s+/, "")}</h1>`;
    else if (/^[-*]\s+/.test(line)) html += `<p>• ${line.replace(/^[-*]\s+/, "")}</p>`;
    else if (!line.trim()) html += "<br>";
    else html += `<p>${line}</p>`;
  }
  return html;
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function countText(label, value) {
  return `<span>${label}<span class="data-value">${value}</span></span>`;
}

function renderSummary(summary) {
  state.summary = summary;
  $("#workspace-name").textContent = summary.name;
  $("#workspace-path").textContent = summary.root;
  $("#next-action").textContent = summary.next_action;
  $("#reference-metric").textContent = summary.reference.has_sample ? `${summary.reference.chapter_count} 章已拆` : "未初始化";
  $("#design-metric").textContent = `${summary.story_design.ready_count}/${summary.story_design.total_count} 设计资产`;
  $("#mechanics-metric").textContent = summary.mechanics.mode;
  $("#writing-metric").textContent = `${summary.writing.chapter_count} 章正文`;
  $("#world-summary").innerHTML = countText("已导入资料 ", summary.world_knowledge.source_count) + countText("最终知识栏 ", summary.world_knowledge.final_section_count);
  $("#design-summary").innerHTML = countText("舞台 ", summary.story_design.stage_count) + countText("书名简介 ", summary.story_design.has_name_synopsis ? "已生成" : "未生成");
  $("#progress-steps").innerHTML = summary.steps.map((item, index) => `
    <div class="progress-step ${item.done ? "done" : ""}"><span class="progress-dot">${item.done ? "✓" : index + 1}</span><span>${item.name}</span></div>
  `).join("");
}

async function refreshWorkspaces(preferredWorkspace = state.workspace) {
  const data = await api("/api/workspaces");
  $("#workspace-root").textContent = data.workspace_root;
  $("#workspace-root").title = data.workspace_root;
  const selected = data.items.some((item) => item.name === preferredWorkspace) ? preferredWorkspace : data.items[0]?.name || null;
  state.workspace = selected;
  $("#workspace-list").innerHTML = data.items.map((item) => `
    <button class="workspace-item ${item.name === selected ? "active" : ""}" data-workspace="${escapeHtml(item.name)}" type="button">
      <div class="workspace-item-name">${escapeHtml(item.name)}</div>
      <div class="workspace-item-meta">${escapeHtml(item.next_action)}</div>
    </button>
  `).join("");
  $$("[data-workspace]").forEach((button) => button.addEventListener("click", () => selectWorkspace(button.dataset.workspace)));
  $("#empty-state").hidden = Boolean(selected);
  $("#workspace-view").hidden = !selected;
  if (selected) await refreshWorkspaceData();
}

async function selectWorkspace(name) {
  if (state.workspace === name) return;
  state.workspace = name;
  state.activeTaskId = null;
  state.logOffset = 0;
  state.editingPath = null;
  $("#file-editor").value = "";
  $("#file-editor").disabled = true;
  $("#save-file").disabled = true;
  $("#editing-path").textContent = "选择一个文本文件";
  await refreshWorkspaces(name);
}

async function refreshWorkspaceData() {
  if (!state.workspace) return;
  try {
    const [summary] = await Promise.all([
      api(`/api/workspaces/${encodeURIComponent(state.workspace)}`),
      refreshTree(),
      refreshTasks(),
    ]);
    renderSummary(summary);
  } catch (error) {
    toast(error.message, true);
  }
}

async function refreshTree() {
  if (!state.workspace) return;
  const data = await api(`/api/workspaces/${encodeURIComponent(state.workspace)}/tree`);
  const tree = $("#file-tree");
  tree.innerHTML = data.items.map((item) => {
    const depth = Math.max(0, item.path.split("/").length - 1);
    const name = item.path.split("/").pop();
    if (item.type === "directory") return `<div class="tree-item directory" style="padding-left:${5 + depth * 11}px">${escapeHtml(name)}</div>`;
    return `<button class="tree-item file ${item.path === state.editingPath ? "active" : ""}" style="padding-left:${5 + depth * 11}px" type="button" data-file-path="${escapeHtml(item.path)}" title="${escapeHtml(item.path)}">${escapeHtml(name)}</button>`;
  }).join("");
  $$("[data-file-path]").forEach((button) => button.addEventListener("click", () => openFile(button.dataset.filePath)));
}

async function openFile(path) {
  try {
    const data = await api(`/api/workspaces/${encodeURIComponent(state.workspace)}/file?path=${encodeURIComponent(path)}`);
    state.editingPath = data.path;
    $("#editing-path").textContent = data.path;
    $("#file-editor").value = data.content;
    $("#file-editor").disabled = false;
    $("#save-file").disabled = false;
    $("#markdown-preview").hidden = true;
    await refreshTree();
  } catch (error) {
    toast(error.message, true);
  }
}

async function saveFile() {
  if (!state.workspace || !state.editingPath) return;
  try {
    await api(`/api/workspaces/${encodeURIComponent(state.workspace)}/file`, {
      method: "PUT",
      body: JSON.stringify({ path: state.editingPath, content: $("#file-editor").value }),
    });
    toast("文件已保存。");
  } catch (error) { toast(error.message, true); }
}

async function uploadFiles(files) {
  const uploads = [];
  for (const file of files) {
    const form = new FormData();
    form.append("file", file);
    uploads.push(await api("/api/uploads", { method: "POST", body: form }));
  }
  return uploads;
}

async function launchTask(type, args = {}) {
  if (!state.workspace) { toast("请先新建工作区。", true); return; }
  try {
    const task = await api("/api/tasks", { method: "POST", body: JSON.stringify({ type, workspace: state.workspace, args }) });
    state.activeTaskId = task.id;
    state.logOffset = 0;
    $("#task-log").textContent = "";
    toast(`${task.label}已开始执行。`);
    await refreshTasks();
  } catch (error) { toast(error.message, true); }
}

async function refreshTasks() {
  if (!state.workspace) return;
  const data = await api(`/api/tasks?workspace=${encodeURIComponent(state.workspace)}`);
  const tasks = data.items;
  if (!state.activeTaskId && tasks[0]) state.activeTaskId = tasks[0].id;
  $("#task-list").innerHTML = tasks.length ? tasks.map((task) => `
    <button class="task-item ${task.id === state.activeTaskId ? "active" : ""}" type="button" data-task-id="${task.id}">
      <span><span class="task-label">${escapeHtml(task.label)}</span><span class="task-meta">${formatDate(task.created_at)}</span></span>
      <span class="status-pill ${task.status}">${task.status === "running" ? "运行中" : task.status === "succeeded" ? "完成" : task.status === "succeeded_with_warnings" ? "需检查" : task.status === "failed" ? "失败" : "等待"}</span>
    </button>
  `).join("") : '<div class="task-meta">还没有运行任务。</div>';
  $$("[data-task-id]").forEach((button) => button.addEventListener("click", () => {
    state.activeTaskId = button.dataset.taskId;
    state.logOffset = 0;
    $("#task-log").textContent = "";
    refreshTasks().then(refreshLogs);
  }));
  const active = tasks.find((task) => task.id === state.activeTaskId);
  const status = $("#active-task-status");
  status.textContent = active ? (active.status === "running" ? "运行中" : active.status === "succeeded" ? "已完成" : active.status === "succeeded_with_warnings" ? "需检查" : active.status === "failed" ? "失败" : "等待") : "空闲";
  status.className = `status-pill ${active?.status || ""}`;
}

async function refreshLogs() {
  if (!state.activeTaskId) return;
  try {
    const data = await api(`/api/tasks/${state.activeTaskId}/logs?offset=${state.logOffset}`);
    if (data.content) {
      const log = $("#task-log");
      log.textContent += data.content;
      log.scrollTop = log.scrollHeight;
      state.logOffset = data.next_offset;
    }
    if (["succeeded", "succeeded_with_warnings", "failed"].includes(data.task.status)) {
      await refreshWorkspaces(state.workspace);
    }
  } catch (error) { /* stale task ids may disappear after a server restart */ }
}

function openDialog(id) { $("#" + id).showModal(); }
function closeDialog(id) { $("#" + id).close(); }

async function loadSettings() {
  const [settings, config] = await Promise.all([api("/api/settings"), api("/api/config")]);
  $("#settings-workspace-root").value = settings.workspace_root;
  $("#model-settings").innerHTML = Object.entries(config.groups).map(([id, group]) => `
    <section class="model-group">
      <h3>${escapeHtml(group.label)}</h3>
      <div class="model-fields">
        <label><span>模型</span><input data-config-key="${id}_MODEL" value="${escapeHtml(group.model)}" /></label>
        <label><span>Base URL</span><input data-config-key="${id}_BASE_URL" value="${escapeHtml(group.base_url)}" /></label>
        <label><span>API Key ${group.api_key_configured ? "（已配置）" : ""}</span><input type="password" data-config-key="${id}_API_KEY" placeholder="${group.api_key_configured ? "留空保留原密钥" : "请输入 API Key"}" /></label>
      </div>
    </section>
  `).join("");
}

function configKeyFromField(key) {
  const prefixes = {
    data_builder: "DATA_BUILDER",
    adaptive_builder: "ADAPTIVE_BUILDER",
    adaptive_builder_lite: "ADAPTIVE_BUILDER_LITE",
  };
  const match = key.match(/^(.*)_(MODEL|BASE_URL|API_KEY)$/);
  return match ? `${prefixes[match[1]]}_${match[2]}` : null;
}

function bindEvents() {
  $("#open-new-workspace").addEventListener("click", () => openDialog("new-workspace-dialog"));
  $("#empty-new-workspace").addEventListener("click", () => openDialog("new-workspace-dialog"));
  $("#open-settings").addEventListener("click", async () => { await loadSettings(); openDialog("settings-dialog"); });
  $$('[data-close-dialog]').forEach((button) => button.addEventListener("click", () => closeDialog(button.dataset.closeDialog)));
  $("#new-workspace-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = $("#new-workspace-name").value.trim();
    const file = $("#reference-file").files[0];
    if (!file) { toast("请选择参考小说 txt 文件。", true); return; }
    try {
      const [uploaded] = await uploadFiles([file]);
      state.workspace = name;
      await launchTask("init", { reference_upload_id: uploaded.id, batch_size: $("#reference-batch-size").value });
      await refreshWorkspaces(name);
      closeDialog("new-workspace-dialog");
      $("#new-workspace-form").reset();
    } catch (error) { toast(error.message, true); }
  });
  $("#world-import-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const files = [...$("#world-files").files];
    if (!files.length) { toast("请先选择目标题材资料。", true); return; }
    try {
      const uploads = await uploadFiles(files);
      await launchTask("world_import", { upload_ids: uploads.map((item) => item.id), force: $("#world-import-force").checked });
      $("#world-files").value = "";
    } catch (error) { toast(error.message, true); }
  });
  $("#world-build-form").addEventListener("submit", (event) => {
    event.preventDefault();
    launchTask("world_build", { primary: $("#world-primary").value, merge_only: $("#world-merge-only").checked, force: $("#world-build-force").checked });
  });
  $("#novel-outline-form").addEventListener("submit", (event) => {
    event.preventDefault();
    launchTask("novel_outline", { direction: $("#creative-direction").value, force: $("#outline-force").checked });
  });
  $("#regenerate-story-design").addEventListener("click", () => launchTask("story_design", { direction: $("#creative-direction").value, force: true }));
  $("#generate-name-synopsis").addEventListener("click", () => launchTask("novel_name_synopsis", { force: true }));
  $("#mechanics-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const file = $("#mechanics-file").files[0];
      const uploads = file ? await uploadFiles([file]) : [];
      await launchTask("mechanics_init", { direction: $("#mechanics-direction").value, mechanics_upload_id: uploads[0]?.id, disable: $("#mechanics-disable").checked, force: $("#mechanics-force").checked });
      $("#mechanics-file").value = "";
    } catch (error) { toast(error.message, true); }
  });
  $("#stage-workflow-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const button = event.submitter;
    const task = button?.dataset.task;
    if (!task) return;
    const common = { volume: $("#stage-volume").value, force: $("#stage-force").checked };
    if (task === "write") Object.assign(common, { start: $("#write-start").value, max: $("#write-max").value, no_humanize: $("#write-no-humanize").checked });
    launchTask(task, common);
  });
  $("#stage-insert-form").addEventListener("submit", (event) => {
    event.preventDefault();
    launchTask("stage_insert", { direction: $("#insert-direction").value, after_stage: $("#insert-after").value });
  });
  $("#refresh-tree").addEventListener("click", refreshTree);
  $("#save-file").addEventListener("click", saveFile);
  $("#file-editor").addEventListener("input", () => { $("#markdown-preview").innerHTML = renderMarkdown($("#file-editor").value); });
  $("#settings-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const root = $("#settings-workspace-root").value.trim();
      await api("/api/settings/workspace-root", { method: "PUT", body: JSON.stringify({ workspace_root: root }) });
      const values = {};
      $$("[data-config-key]").forEach((input) => {
        const key = configKeyFromField(input.dataset.configKey);
        if (key) values[key] = input.value;
      });
      await api("/api/config", { method: "PUT", body: JSON.stringify({ values }) });
      closeDialog("settings-dialog");
      await refreshWorkspaces(null);
      toast("设置已保存。新的任务会使用当前配置。");
    } catch (error) { toast(error.message, true); }
  });
}

async function boot() {
  bindEvents();
  try { await refreshWorkspaces(); }
  catch (error) { toast(error.message, true); }
  setInterval(async () => {
    await refreshLogs();
    if (state.workspace) await refreshTasks();
  }, 1400);
}

boot();
