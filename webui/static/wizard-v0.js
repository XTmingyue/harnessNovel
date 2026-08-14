const WIZARD_STEPS = [
  { id: "reference", title: "参考小说", short: "拆书与结构", optional: false, heading: "参考小说拆解", lead: "全书大纲、卷纲和故事片段已结构化保存。", decision: "检查全书结构、分卷边界和故事片段，再进入新书设计。", reviewPrefixes: ["reference/outlines"], reviewHint: "查看全书大纲、卷纲与故事片段。" },
  { id: "world", title: "目标世界", short: "可选资料库", optional: true, heading: "构建目标世界资料库", lead: "用主资料定义世界，用补充资料完善细节。", decision: "导入资料后指定主资料；不需要可跳过。", reviewPrefixes: ["file_system/world_knowledge/worlds/_final"], reviewHint: "查看世界规则、力量体系与关键角色。" },
  { id: "design", title: "全书设计", short: "世界观与大纲", optional: false, heading: "设计世界观、粗略大纲与阶段粗纲", lead: "输入灵感后，系统会依次生成世界观、粗略大纲和独立阶段粗纲，之后可继续对话调整。", decision: "初版按三步串行生成，减少单次上下文；后续调整会同步维护三份设计。", reviewPrefixes: ["file_system/story_design/worldview.md", "file_system/story_design/rough_outline.md", "file_system/story_design/stage_outline.md", "file_system/story_design/core_gameplay.md"], reviewHint: "分别查看世界规则、核心玩法和阶段推进，可随时继续调整。" },
  { id: "stage", title: "舞台设计", short: "长线与舞台", optional: false, heading: "设计长线主线与舞台路线图", lead: "系统先生成全书长线主线，再按阶段与对应参考卷纲逐个生成舞台；中断后可从已完成舞台继续。", decision: "每次只生成一个舞台，并以上一舞台维持连续性；生成完成后仍可通过对话微调或续写。", reviewPrefixes: ["file_system/story_design/long_mainline.md", "file_system/story_design/stage_roadmap.md", "file_system/novel_name_synopsis.md"], reviewHint: "舞台采用卷纲式结构，可查看三幕推进、人物、伏笔和核心爽点。" },
  { id: "arcs", title: "故事情节", short: "当前舞台", optional: false, heading: "生成故事情节单元", lead: "为当前舞台产出连续推进的情节蓝图。", decision: "选择舞台，抽象参考叙事模式后生成新情节。", reviewPrefixes: ["file_system/story_arcs"], reviewHint: "查看各已生成卷的目标、冲突、情绪与钩子，可随时继续调整。" },
  { id: "chapters", title: "逐章章纲", short: "单章卡片", optional: false, heading: "生成逐章章纲", lead: "串行生成章纲，并同步维护每章的主角系统面板状态。", decision: "选择舞台或情节单元，生成对应章节的单章卡片。", reviewPrefixes: ["file_system/chapter_outlines", "file_system/system_panels"], reviewHint: "查看章纲与独立保存的主角系统面板状态，可随时继续调整。" },
  { id: "draft", title: "正文", short: "写作与精修", optional: false, heading: "生成正文", lead: "按章纲连续写作，并在后台保留原稿备份。", decision: "选择舞台和故事情节，通过对话串行生成正文。", reviewPrefixes: ["file_system/chapters"], reviewHint: "这里只显示精修后的正文，可在对话中继续调整。" },
];

const CONFIG_PREFIXES = {
  data_builder: "DATA_BUILDER",
  adaptive_builder: "ADAPTIVE_BUILDER",
  adaptive_builder_lite: "ADAPTIVE_BUILDER_LITE",
};

const REVIEW_GROUPS = {
  reference: [
    { title: "全书规划", description: "整体节奏、阶段推进与核心冲突。", matches: (path) => path.endsWith("/novel_outline.md") },
  ],
  world: [
    { title: "目标世界设定", description: "后续设计可直接引用的世界公共设定。", matches: (path) => path.includes("/worlds/_final/") },
  ],
  design: [
    { title: "创作设计", description: "决定全书玩法、期待与舞台推进。", matches: (path) => path.includes("/story_design/") },
    { title: "书名建议", description: "根据全书设计生成的书名方向与简介。", matches: (path) => path.endsWith("/novel_name_synopsis.md") },
  ],
  stage: [
    { title: "长线主线与舞台路线图", description: "定义全书长线悬念、阶段目标与舞台推进顺序。", matches: (path) => path.endsWith("/long_mainline.md") || path.endsWith("/stage_roadmap.md") },
    { title: "书名与简介", description: "基于完整全书设计生成的书名方向与平台简介。", matches: (path) => path.endsWith("/novel_name_synopsis.md") },
  ],
  arcs: [
    { title: "舞台故事蓝图", description: "当前舞台中连续推进的故事蓝图。", matches: (path) => path.includes("/story_arcs/") },
  ],
  chapters: [
    { title: "章节设计资料", description: "每章的故事线、情绪节奏与描述性单章简介。", matches: (path) => path.includes("/chapter_outlines/") },
    { title: "系统面板状态", description: "每章结束时以主角为核心的结构化状态快照。", matches: (path) => path.includes("/system_panels/") },
  ],
  draft: [
    { title: "已精修正文", description: "可继续修改和发布的章节正文。", matches: (path) => path.includes("/chapters/") },
  ],
};

const wizardState = {
  workspace: null,
  summary: null,
  activeStep: null,
  confirmed: new Set(),
  activeTaskId: null,
  logOffset: 0,
  selectedFile: null,
  selectedFileContent: "",
  fileEditing: false,
  fileTree: [],
  reviewArtifacts: [],
  directionMode: "text",
  directionFile: null,
  directionFileContent: "",
  chatAttachments: {},
  arcsChatVolume: null,
  chaptersChatVolume: null,
  chaptersChatArc: null,
  draftChatVolume: null,
  draftChatArc: null,
  draftJobCompleted: {},
  draftJobIds: {},
  referenceFile: null,
  referenceScope: "all",
  mechanicsMode: "auto",
  mechanicsFile: null,
  lastSyncedTaskId: null,
  arcsJobCompleted: {},
  chaptersJobCompleted: {},
  designJobCompleted: {},
  systemPanelStatus: null,
  taskView: "log",
  currentPromptText: "",
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...(options.headers || {}) } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || "请求失败，请稍后重试。");
    error.status = response.status;
    throw error;
  }
  return data;
}

function closeSettings() {
  $("#settings-panel").classList.remove("open");
  $("#settings-panel").setAttribute("aria-hidden", "true");
  $("#settings-scrim").classList.remove("open");
}

function modelConfigFields(groupId, group) {
  const prefix = CONFIG_PREFIXES[groupId];
  const configured = group.api_key_configured ? "API Key 已配置" : "未配置 API Key";
  return `<section class="model-config-group">
    <header><h3>${escapeHtml(group.label)}</h3><span class="config-status ${group.api_key_configured ? "ready" : "missing"}">${configured}</span></header>
    <label>模型名称<input name="${prefix}_MODEL" value="${escapeHtml(group.model || "")}" placeholder="例如：deepseek-v4-pro" autocomplete="off" /></label>
    <label>Base URL<input name="${prefix}_BASE_URL" value="${escapeHtml(group.base_url || "")}" placeholder="https://api.example.com" autocomplete="off" /></label>
    <label>API Key<input name="${prefix}_API_KEY" type="password" placeholder="${group.api_key_configured ? "已配置，留空保持不变" : "请输入 API Key"}" autocomplete="new-password" /></label>
  </section>`;
}

async function openSettings() {
  const content = $("#settings-content");
  content.innerHTML = '<p class="settings-loading">正在读取本地配置…</p>';
  $("#settings-panel").classList.add("open");
  $("#settings-panel").setAttribute("aria-hidden", "false");
  $("#settings-scrim").classList.add("open");
  try {
    const config = await api("/api/config");
    const groups = Object.entries(config.groups || {});
    content.innerHTML = `<form id="model-config-form" class="model-config-form">
      <p class="config-path">${escapeHtml(config.config_path || "")}</p>
      ${groups.map(([id, group]) => modelConfigFields(id, group)).join("")}
      <div class="settings-actions"><button id="cancel-settings" class="secondary-button" type="button">取消</button><button class="primary-button" type="submit">保存配置</button></div>
    </form>`;
    $("#cancel-settings").addEventListener("click", closeSettings);
    $("#model-config-form").addEventListener("submit", saveModelConfig);
  } catch (error) {
    content.innerHTML = `<p class="settings-error">${escapeHtml(error.message || "无法读取配置。")}</p>`;
  }
}

async function saveModelConfig(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const values = {};
  [...form.querySelectorAll('input[name]')].forEach((input) => {
    const value = input.value.trim();
    if (value) values[input.name] = value;
  });
  submit.disabled = true;
  try {
    await api("/api/config", { method: "PUT", body: JSON.stringify({ values }) });
    closeSettings();
    showToast("大模型配置已保存。");
  } catch (error) {
    showToast(error.message || "保存配置失败。", true);
  } finally {
    submit.disabled = false;
  }
}

let toastTimer;
function showToast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), 3200);
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[char]);
}

function renderInlineMarkdown(value) {
  const codeTokens = [];
  let rendered = escapeHtml(value).replace(/`([^`]+)`/g, (_, code) => {
    const token = `@@CODE_${codeTokens.length}@@`;
    codeTokens.push(`<code>${code}</code>`);
    return token;
  });
  rendered = rendered.replace(/\[([^\]]+)]\(([^\s)]+)(?:\s+&quot;[^)]*&quot;)?\)/g, (match, label, href) => {
    const normalizedHref = href.replace(/&amp;/g, "&");
    if (!/^(https?:\/\/|mailto:)/i.test(normalizedHref)) return match;
    return `<a href="${href}" target="_blank" rel="noreferrer noopener">${label}</a>`;
  });
  rendered = rendered.replace(/(\*\*|__)(.+?)\1/g, "<strong>$2</strong>");
  rendered = rendered.replace(/~~(.+?)~~/g, "<del>$1</del>");
  rendered = rendered.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  rendered = rendered.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, "$1<em>$2</em>");
  return rendered.replace(/@@CODE_(\d+)@@/g, (_, index) => codeTokens[Number(index)] || "");
}

function tableCells(line) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
}

function isTableDivider(line) {
  const cells = tableCells(line);
  return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function markdownPreview(value) {
  const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
  const output = [];
  let index = 0;
  const isUnordered = (line) => /^\s*(?:[-*+]|—|–)\s+/.test(line);
  const isOrdered = (line) => /^\s*\d+[.)]\s+/.test(line);
  const isBlockStart = (line, next) => /^(#{1,6})\s+/.test(line) || /^\s*```/.test(line) || /^\s*>\s?/.test(line) || /^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line) || isUnordered(line) || isOrdered(line) || (line.includes("|") && isTableDivider(next || ""));

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^\s*```([^\s]*)\s*$/);
    if (fence) {
      const language = fence[1] ? ` data-language="${escapeHtml(fence[1])}"` : "";
      const codeLines = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      output.push(`<pre class="markdown-code"${language}><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      output.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }

    if (/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line)) {
      output.push("<hr />");
      index += 1;
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quoteLines = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      output.push(`<blockquote>${markdownPreview(quoteLines.join("\n"))}</blockquote>`);
      continue;
    }

    if (line.includes("|") && isTableDivider(lines[index + 1] || "")) {
      const headings = tableCells(line);
      index += 2;
      const rows = [];
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(tableCells(lines[index]));
        index += 1;
      }
      output.push(`<div class="markdown-table-wrap"><table><thead><tr>${headings.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headings.map((_, cellIndex) => `<td>${renderInlineMarkdown(row[cellIndex] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }

    if (isUnordered(line) || isOrdered(line)) {
      const ordered = isOrdered(line);
      const items = [];
      const pattern = ordered ? /^\s*\d+[.)]\s+(.+)$/ : /^\s*(?:[-*+]|—|–)\s+(.+)$/;
      while (index < lines.length) {
        const item = lines[index].match(pattern);
        if (!item) break;
        items.push(item[1]);
        index += 1;
      }
      const tag = ordered ? "ol" : "ul";
      output.push(`<${tag}>${items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</${tag}>`);
      continue;
    }

    const paragraph = [line.trim()];
    index += 1;
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index], lines[index + 1])) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    output.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br />")}</p>`);
  }
  return output.join("");
}

function inferredDone(step) {
  const summary = wizardState.summary;
  if (!summary) return false;
  if (wizardState.confirmed.has(step.id)) return true;
  if (step.id === "reference") return summary.reference.has_sample && summary.reference.chapter_count > 0;
  if (step.id === "world") return Boolean(summary.world_knowledge.ready);
  if (step.id === "design") return Boolean(summary.story_design?.concept_ready);
  if (step.id === "stage") return Boolean(summary.story_design?.stage_ready);
  if (step.id === "mechanics") return summary.mechanics.mode !== "未初始化";
  if (step.id === "arcs") return summary.writing.story_arc_count > 0;
  if (step.id === "chapters") return summary.writing.chapter_outline_count > 0;
  if (step.id === "draft") return summary.writing.chapter_count > 0;
  return false;
}

function stepIndex(stepId) { return WIZARD_STEPS.findIndex((step) => step.id === stepId); }

function currentRecommendedStep() {
  const firstIncomplete = WIZARD_STEPS.find((step) => !inferredDone(step));
  return firstIncomplete?.id || "draft";
}

function canOpenStep(step) {
  const index = stepIndex(step.id);
  if (inferredDone(step)) return true;
  if (step.id === currentRecommendedStep()) return true;
  return WIZARD_STEPS.slice(0, index).every((item) => inferredDone(item) || item.optional);
}

function statusForStep(step) {
  if (inferredDone(step)) return "done";
  if (step.id === currentRecommendedStep()) return "active";
  if (canOpenStep(step)) return "ready";
  return "locked";
}

function renderRail() {
  $("#workflow-list").innerHTML = WIZARD_STEPS.map((step, index) => {
    const state = statusForStep(step);
    const active = step.id === wizardState.activeStep;
    const disabled = state === "locked" ? "disabled" : "";
    const meta = state === "done" ? "已有内容" : state === "locked" ? "等待上一步" : step.optional ? "可选" : active ? "当前步骤" : "待处理";
    return `<button class="workflow-step ${state} ${active ? "active" : ""}" data-step="${step.id}" ${disabled} type="button"><span class="workflow-step-number">${state === "done" ? "✓" : index + 1}</span><span><span class="workflow-step-title">${step.title}</span><span class="workflow-step-meta">${meta}</span></span></button>`;
  }).join("");
  $$('[data-step]').forEach((button) => button.addEventListener("click", () => {
    wizardState.activeStep = button.dataset.step;
    renderRail();
    renderActiveStep();
  }));
}

function referenceStatus() {
  const reference = wizardState.summary?.reference || {};
  const processed = Number(reference.processed_chapter_count || 0);
  const stagedChapters = Number(reference.chapter_count || 0);
  const total = Number(reference.total_chapter_count || 0);
  const hasExisting = Boolean(reference.has_sample);
  const isComplete = hasExisting && Boolean(reference.is_complete);
  return { ...reference, processed, stagedChapters, total, hasExisting, isComplete };
}

function referenceScopeControls(defaultTarget, disabled = false) {
  return `<fieldset class="reference-scope" id="reference-scope" ${disabled ? "disabled" : ""}>
    <legend>拆解范围</legend>
    <div class="reference-scope-options">
      <label class="reference-scope-option"><input name="reference-scope" value="all" type="radio" ${wizardState.referenceScope === "all" ? "checked" : ""} /><span>整本书</span></label>
      <label class="reference-scope-option"><input name="reference-scope" value="prefix" type="radio" ${wizardState.referenceScope === "prefix" ? "checked" : ""} /><span>只拆前</span><input id="reference-max-chapters" type="number" min="1" value="${defaultTarget}" ${wizardState.referenceScope === "prefix" && !disabled ? "" : "disabled"} /><span>章</span></label>
    </div>
  </fieldset>`;
}

function designStatus() {
  const design = wizardState.summary?.story_design || {};
  const reference = referenceStatus();
  const ready = Number(design.ready_count || 0) === Number(design.total_count || 5);
  const newReferenceChapters = Number(design.new_reference_chapter_count || 0);
  const baseline = design.reference_baseline_chapters;
  const baselineMissing = baseline === null || baseline === undefined;
  const canUseReference = newReferenceChapters > 0 || (baselineMissing && reference.processed > 0);
  return { ...design, ready, newReferenceChapters, baseline, baselineMissing, referenceProcessed: reference.processed, canUseReference };
}

function isDesignChatStep(step) {
  return step.id === "design" || step.id === "stage" || step.id === "arcs" || step.id === "chapters" || step.id === "draft";
}



function arcsJobMarkup(job) {
  if (!job) return "";
  if (job.status === "idle" && job.can_resume) {
    const completed = Number(job.completed || 0);
    const total = Number(job.total || 0);
    const percent = total > 0 ? Math.round(completed * 100 / total) : 0;
    return `<div class="chat-job-progress is-interrupted" id="arcs-job-progress">
      <div class="chat-job-progress-main">
        <span class="chat-job-status-dot" aria-hidden="true"></span>
        <div class="chat-job-progress-copy">
          <strong>上次生成在情节单元 ${Number(job.next_arc || completed + 1)} 前中断</strong>
          <span>已保留 ${completed} / ${total} 个情节单元</span>
        </div>
        <button id="continue-arcs-job" class="chat-job-action resume continue" type="button"><span aria-hidden="true">▶</span>继续生成</button>
      </div>
      <div class="chat-job-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><i style="width:${percent}%"></i></div>
    </div>`;
  }
  if (["idle", "completed", "failed", "stopped"].includes(job.status)) return "";
  const total = Number(job.total || 0);
  const completed = Number(job.completed || 0);
  const serialRefine = job.progress_kind === "serial_refine";
  const routing = serialRefine && job.phase === "routing";
  const percent = total > 0 ? Math.round(completed * 100 / total) : 4;
  const paused = job.status === "paused";
  const pausing = job.status === "pausing";
  const stopping = job.status === "stopping";
  const pauseAction = paused
    ? '<button id="resume-arcs-job" class="chat-job-action resume" type="button"><span aria-hidden="true">▶</span>继续</button>'
    : `<button id="pause-arcs-job" class="chat-job-action" type="button" ${(pausing || stopping) ? "disabled" : ""}><span aria-hidden="true">${pausing ? "…" : "Ⅱ"}</span>${pausing ? "暂停中" : "暂停"}</button>`;
  const stopAction = `<button id="stop-arcs-job" class="chat-job-action stop" type="button" ${stopping ? "disabled" : ""}><span aria-hidden="true">■</span>${stopping ? "结束中" : "结束"}</button>`;
  const promptAction = Number(job.prompt_count || 0) > 0 ? `<button id="show-arcs-prompt" class="chat-job-action prompt" type="button">Prompt · ${Number(job.prompt_count)}</button>` : "";
  const meta = stopping
    ? (serialRefine ? `正在结束调整 · 已完成 ${completed} 个` : `正在保留已完成的 ${completed} 个情节单元`)
    : paused
    ? (serialRefine ? `串行调整已暂停 · 已完成 ${completed} / ${total || "—"}` : `停在 ${completed} / ${total || "—"} · 已完成内容已保存`)
    : pausing
      ? (serialRefine ? `正在暂停当前调整请求 · ${completed} / ${total || "—"}` : `当前单元保存后暂停 · ${completed} / ${total || "—"}`)
      : routing
        ? "正在判断最早受影响的情节单元"
      : serialRefine
        ? `${completed} / ${total || "—"} 个待调整单元 · ${percent}%`
      : total > 0
        ? `${completed} / ${total} 个情节单元 · ${percent}%`
        : "正在分析生成范围";
  return `<div class="chat-job-progress ${paused ? "is-paused" : pausing ? "is-pausing" : stopping ? "is-stopping" : ""} ${routing ? "is-refining" : ""}" id="arcs-job-progress">
    <div class="chat-job-progress-main">
      <span class="chat-job-status-dot" aria-hidden="true"></span>
      <div class="chat-job-progress-copy">
        <strong>${escapeHtml(job.message || "正在生成")}</strong>
        <span>${meta}</span>
      </div>
      <div class="chat-job-actions">${promptAction}${pauseAction}${stopAction}</div>
    </div>
    <div class="chat-job-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" ${routing ? 'aria-label="正在分析调整范围"' : `aria-valuenow="${percent}"`}><i style="width:${Math.max(2, Math.min(100, percent))}%"></i></div>
  </div>`;
}

function arcsChatPanelMarkup(volume, conversation, job = null) {
  const turns = (conversation && Array.isArray(conversation.turns)) ? conversation.turns : [];
  const sd = wizardState.summary?.story_design || {};
  const stageCount = Math.max(0, Number(sd.stage_count || 0));
  const selector = stageCount
    ? `<select id="arcs-volume-select">${Array.from({ length: stageCount }, (_, i) => `<option value="${i + 1}" ${Number(volume) === i + 1 ? "selected" : ""}>第 ${i + 1} 舞台</option>`).join("")}</select>`
    : `<input id="arcs-volume-select" type="number" min="1" value="${volume}" />`;
  const volumeInfo = (wizardState.summary?.volumes || []).find((item) => Number(item.volume) === Number(volume));
  const arcsExist = Boolean(conversation?.has_arcs) || Boolean(volumeInfo?.arcs?.length);
  const placeholder = "描述对情节单元的调整要求，例如「情节单元1增加一个反转」「主角在情节单元3中实力突破」…";
  const messages = turns.map(chatMessageMarkup).join("");
  const resetBtn = (turns.length || arcsExist) ? '<button id="reset-arcs-chat" class="chat-icon-btn" type="button" title="删除本卷情节单元并重新开始">⟳ 重置</button>' : "";
  const emptyHint = arcsExist ? "选择舞台后在下方输入调整要求。首次进入请先选择舞台并描述需求。" : "选择舞台后，输入关于情节设计的灵感或需求，开始生成故事情节单元。";
  return `<section class="chat-panel" id="arcs-chat" data-volume="${volume}">
    <header class="chat-panel-bar"><span class="chat-panel-bar-label">舞台 / 卷号</span>${selector}</header>
    <div class="chat-scroll" id="chat-message-list">${messages || `<div class="chat-empty"><div class="chat-empty-icon">📖</div><p>${emptyHint}</p></div>`}</div>
    ${arcsJobMarkup(job)}
    <div class="chat-composer">
      <div class="chat-input-row">
        <textarea id="arcs-chat-input" class="chat-input" placeholder="${placeholder}" rows="1"></textarea>
        <button id="send-arcs-chat" class="chat-send-btn" type="button" title="发送（Ctrl/⌘+Enter）"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
      </div>
      <div class="chat-composer-meta">${resetBtn}</div>
    </div>
  </section>`;
}

function renderArcsChat(volume, conversation, job = null) {
  const node = $("#arcs-chat-host");
  if (!node) return;
  node.innerHTML = arcsChatPanelMarkup(volume, conversation, job);
  const list = $("#chat-message-list");
  if (list) list.scrollTop = list.scrollHeight;
  $("#arcs-volume-select")?.addEventListener("change", () => {
    wizardState.arcsChatVolume = Number($("#arcs-volume-select").value) || 1;
    loadArcsChat(wizardState.arcsChatVolume);
  });
  $("#send-arcs-chat")?.addEventListener("click", () => sendArcsMessage(volume));
  const jobActive = job && ["running", "pausing", "paused", "stopping"].includes(job.status);
  if (jobActive) {
    $("#send-arcs-chat").disabled = true;
    $("#arcs-chat-input").disabled = true;
  }
  $("#pause-arcs-job")?.addEventListener("click", () => controlArcsJob(volume, "pause"));
  $("#resume-arcs-job")?.addEventListener("click", () => controlArcsJob(volume, "resume"));
  $("#stop-arcs-job")?.addEventListener("click", () => controlArcsJob(volume, "stop"));
  $("#continue-arcs-job")?.addEventListener("click", () => controlArcsJob(volume, "continue"));
  const chatInput = $("#arcs-chat-input");
  const autoGrow = () => { if (chatInput) { chatInput.style.height = "auto"; chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + "px"; } };
  chatInput?.addEventListener("input", autoGrow);
  chatInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); sendArcsMessage(volume); }
  });
  $$("[data-artifact-path]").forEach((btn) => btn.addEventListener("click", () => openReviewFile(btn.dataset.artifactPath)));
  $("#reset-arcs-chat")?.addEventListener("click", async () => {
    if (!confirm(`将删除第 ${volume} 舞台的所有故事情节单元并清空对话。确认重置？`)) return;
    try {
      await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/arcs/${volume}/reset`, { method: "POST", body: JSON.stringify({}) });
      await refreshWorkspaceArtifacts();
      const data = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/arcs/${volume}/conversation`);
      renderArcsChat(volume, data);
      showToast("已重置，下一条消息将重新生成。");
    } catch (error) { showToast(error.message || "无法重置。", true); }
  });
}

async function loadArcsChat(volume) {
  try {
    const base = `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/arcs/${volume}`;
    const [data, job] = await Promise.all([api(`${base}/conversation`), api(`${base}/job`)]);
    renderArcsChat(volume, data, job);
    if (["running", "pausing", "paused", "stopping"].includes(job.status)) pollArcsJob(volume);
  } catch (_) { /* ignore */ }
}

let arcsJobPollTimer = null;

async function controlArcsJob(volume, action) {
  try {
    const job = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/arcs/${volume}/${action}`, {
      method: "POST", body: JSON.stringify({}),
    });
    const conversation = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/arcs/${volume}/conversation`);
    renderArcsChat(volume, conversation, job);
    pollArcsJob(volume);
  } catch (error) {
    if (action === "stop" && error.status === 404) {
      showToast("后端仍是旧版本，请重启 novel web 后再点击结束。已生成内容不会丢失。", true);
    } else {
      showToast(error.message || "无法控制生成任务。", true);
    }
  }
}

function pollArcsJob(volume) {
  if (arcsJobPollTimer) clearTimeout(arcsJobPollTimer);
  const poll = async () => {
    if (Number(wizardState.arcsChatVolume || volume) !== Number(volume)) return;
    try {
      const base = `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/arcs/${volume}`;
      const job = await api(`${base}/job`);
      const progress = $("#arcs-job-progress");
      if (["running", "pausing", "paused", "stopping"].includes(job.status)) {
        const completed = Number(job.completed || 0);
        const lastCompleted = Number(wizardState.arcsJobCompleted[volume] || 0);
        if (completed > lastCompleted) {
          wizardState.arcsJobCompleted[volume] = completed;
          await refreshReviewArtifactsOnly(job.progress_kind === "serial_refine");
        }
        if (progress) {
          const holder = document.createElement("div");
          holder.innerHTML = arcsJobMarkup(job);
          progress.replaceWith(holder.firstElementChild);
          $("#pause-arcs-job")?.addEventListener("click", () => controlArcsJob(volume, "pause"));
          $("#resume-arcs-job")?.addEventListener("click", () => controlArcsJob(volume, "resume"));
          $("#stop-arcs-job")?.addEventListener("click", () => controlArcsJob(volume, "stop"));
        } else {
          const conversation = await api(`${base}/conversation`);
          renderArcsChat(volume, conversation, job);
        }
        arcsJobPollTimer = setTimeout(poll, 900);
        return;
      }
      const conversation = await api(`${base}/conversation`);
      await refreshWorkspaceArtifacts();
      renderArcsChat(volume, conversation, job);
      if (job.status === "failed") showToast(job.error || "生成失败，请重试。", true);
      else if (job.status === "stopped") showToast("已结束本轮生成，已完成内容均已保留。");
      else if (job.status === "completed") showToast("故事情节生成完成。");
    } catch (error) {
      arcsJobPollTimer = setTimeout(poll, 1500);
    }
  };
  poll();
}

async function sendArcsMessage(volume) {
  const input = $("#arcs-chat-input");
  const message = (input?.value || "").trim();
  if (!message) return;
  const button = $("#send-arcs-chat");
  if (button) button.disabled = true;
  if (input) input.disabled = true;
  const list = $("#chat-message-list");
  const empty = list?.querySelector(".chat-empty");
  if (empty) empty.remove();
  if (list) {
    const li = document.createElement("li");
    li.className = "chat-message user";
    li.innerHTML = `<div class="chat-message-body">${escapeHtml(message)}</div>`;
    list.appendChild(li);
    const typing = document.createElement("li");
    typing.className = "chat-message assistant typing";
    typing.id = "chat-typing";
    typing.innerHTML = `<div class="chat-message-avatar">AI</div><div class="chat-message-content"><div class="chat-typing-dots"><span></span><span></span><span></span></div></div>`;
    list.appendChild(typing);
    list.scrollTop = list.scrollHeight;
  }
  if (input) input.value = "";
  let started = false;
  try {
    const job = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/arcs/${volume}/chat`, {
      method: "POST", body: JSON.stringify({ message }),
    });
    wizardState.arcsJobCompleted[volume] = Number(job.completed || 0);
    $("#chat-typing")?.remove();
    const conversation = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/arcs/${volume}/conversation`);
    renderArcsChat(volume, conversation, job);
    pollArcsJob(volume);
  } catch (error) {
    showToast(error.message || "生成失败，请重试。", true);
    loadArcsChat(volume);
  } finally {}
}


function chaptersVolumeDetails() {
  const volumes = wizardState.summary?.volumes || [];
  return volumes;
}

function chaptersJobMarkup(job) {
  if (!job) return "";
  if (job.status === "idle" && job.can_resume) {
    const completed = Number(job.completed || 0), total = Number(job.total || 0);
    const percent = total ? Math.round(completed * 100 / total) : 0;
    return `<div class="chat-job-progress is-interrupted" id="chapters-job-progress">
      <div class="chat-job-progress-main"><span class="chat-job-status-dot"></span>
        <div class="chat-job-progress-copy"><strong>上次生成在第 ${Number(job.next_chapter || completed + 1)} 章前中断</strong><span>已保留 ${completed} / ${total} 章</span></div>
        <button id="continue-chapters-job" class="chat-job-action resume continue" type="button"><span>▶</span>继续生成</button>
      </div><div class="chat-job-progress-track"><i style="width:${percent}%"></i></div>
    </div>`;
  }
  if (["idle", "completed", "failed", "stopped"].includes(job.status)) return "";
  const total = Number(job.total || 0), completed = Number(job.completed || 0);
  const refining = job.progress_kind === "serial_chapter_refine";
  const routing = refining && job.phase === "routing";
  const percent = total ? Math.round(completed * 100 / total) : 4;
  const paused = job.status === "paused", pausing = job.status === "pausing", stopping = job.status === "stopping";
  const pauseAction = paused
    ? '<button id="resume-chapters-job" class="chat-job-action resume" type="button"><span>▶</span>继续</button>'
    : `<button id="pause-chapters-job" class="chat-job-action" type="button" ${(pausing || stopping) ? "disabled" : ""}><span>${pausing ? "…" : "Ⅱ"}</span>${pausing ? "暂停中" : "暂停"}</button>`;
  const stopAction = `<button id="stop-chapters-job" class="chat-job-action stop" type="button" ${stopping ? "disabled" : ""}><span>■</span>${stopping ? "结束中" : "结束"}</button>`;
  const promptAction = Number(job.prompt_count || 0) > 0 ? `<button id="show-chapters-prompt" class="chat-job-action prompt" type="button">Prompt · ${Number(job.prompt_count)}</button>` : "";
  const meta = stopping ? `正在结束 · 已完成 ${completed} 章`
    : paused ? `已暂停 · ${completed} / ${total || "—"} 章`
    : pausing ? `正在暂停当前请求 · ${completed} / ${total || "—"}`
    : routing ? "正在判断最早受影响章节"
    : refining ? `${completed} / ${total || "—"} 个待调整章节 · ${percent}%`
    : `${completed} / ${total || "—"} 章 · ${percent}%`;
  return `<div class="chat-job-progress ${paused ? "is-paused" : pausing ? "is-pausing" : stopping ? "is-stopping" : ""} ${routing ? "is-refining" : ""}" id="chapters-job-progress">
    <div class="chat-job-progress-main"><span class="chat-job-status-dot"></span>
      <div class="chat-job-progress-copy"><strong>${escapeHtml(job.message || "正在生成章纲")}</strong><span>${meta}</span></div>
      <div class="chat-job-actions">${promptAction}${pauseAction}${stopAction}</div>
    </div><div class="chat-job-progress-track"><i style="width:${Math.max(2, Math.min(100, percent))}%"></i></div>
  </div>`;
}

function chaptersChatPanelMarkup(volume, arcIdx, conversation, job = null) {
  const volumes = chaptersVolumeDetails();
  const volDetail = volumes.find((v) => v.volume === Number(volume)) || { arcs: [] };
  const arcs = volDetail.arcs || [];
  const volumeSelector = volumes.length
    ? `<select id="chapters-volume-select">${volumes.map((v) => `<option value="${v.volume}" ${Number(volume) === v.volume ? "selected" : ""}>第 ${v.volume} 舞台</option>`).join("")}</select>`
    : `<input id="chapters-volume-select" type="number" min="1" value="${volume}" />`;
  const arcSelector = arcs.length
    ? `<select id="chapters-arc-select">${arcs.map((a) => `<option value="${a.idx}" ${Number(arcIdx) === a.idx ? "selected" : ""}>情节单元${a.idx}${a.title ? ` · ${escapeHtml(a.title)}` : ""}（第${a.start_ch}-${a.end_ch}章）</option>`).join("")}</select>`
    : `<select id="chapters-arc-select" disabled><option>该舞台暂无情节单元</option></select>`;
  const turns = (conversation && Array.isArray(conversation.turns)) ? conversation.turns : [];
  const placeholder = "描述对本批章纲的调整要求，例如「第1章情绪基调更压抑」「第3章单章简介加强反转」…";
  const messages = turns.map(chatMessageMarkup).join("");
  const resetBtn = (turns.length || conversation?.has_outlines) ? '<button id="reset-chapters-chat" class="chat-icon-btn" type="button" title="删除本批章纲和系统面板并重新开始">⟳ 重置</button>' : "";
  const emptyHint = arcs.length ? "选择舞台和情节单元后，输入描述开始生成逐章章纲。" : "该舞台还没有故事情节单元，请先在「故事情节」步骤中生成。";
  const panel = wizardState.systemPanelStatus || { selection_mode: "auto", decided: false, enabled: false };
  const panelResult = panel.unavailable
    ? "设置接口尚未加载，重启服务后可用"
    : panel.selection_mode === "auto"
    ? (panel.decided ? `自动判断结果：${panel.enabled ? "需要系统面板" : "不需要系统面板"}` : "首次生成章纲时自动判断")
    : (panel.enabled ? "已手动启用，将逐章更新主角状态" : "已关闭，不生成章节系统面板");
  return `<section class="chat-panel" id="chapters-chat" data-volume="${volume}" data-arc="${arcIdx}">
    <header class="chat-panel-bar">
      <span class="chat-panel-bar-label">舞台 / 卷号</span>${volumeSelector}
      <span class="chat-panel-bar-label">情节单元</span>${arcSelector}
    </header>
    <div class="system-panel-config-bar">
      <div><strong>系统面板</strong><span>${escapeHtml(panelResult)}</span></div>
      <select id="chapter-system-panel-mode" aria-label="系统面板模式" ${panel.unavailable ? "disabled" : ""}>
        <option value="auto" ${panel.selection_mode === "auto" ? "selected" : ""}>自动判断</option>
        <option value="enabled" ${panel.selection_mode === "enabled" ? "selected" : ""}>启用</option>
        <option value="disabled" ${panel.selection_mode === "disabled" ? "selected" : ""}>不使用</option>
      </select>
    </div>
    <div class="chat-scroll" id="chat-message-list">${messages || `<div class="chat-empty"><div class="chat-empty-icon">📝</div><p>${emptyHint}</p></div>`}</div>
    ${chaptersJobMarkup(job)}
    <div class="chat-composer">
      <div class="chat-input-row">
        <textarea id="chapters-chat-input" class="chat-input" placeholder="${placeholder}" rows="1"></textarea>
        <button id="send-chapters-chat" class="chat-send-btn" type="button" title="发送（Ctrl/⌘+Enter）" ${arcs.length ? "" : "disabled"}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
      </div>
      <div class="chat-composer-meta">${resetBtn}</div>
    </div>
  </section>`;
}

function renderChaptersChat(volume, arcIdx, conversation, job = null) {
  const node = $("#chapters-chat-host");
  if (!node) return;
  node.innerHTML = chaptersChatPanelMarkup(volume, arcIdx, conversation, job);
  const list = $("#chat-message-list");
  if (list) list.scrollTop = list.scrollHeight;
  $("#chapters-volume-select")?.addEventListener("change", () => {
    wizardState.chaptersChatVolume = Number($("#chapters-volume-select").value) || 1;
    wizardState.chaptersChatArc = null;
    const volDetail = chaptersVolumeDetails().find((v) => v.volume === wizardState.chaptersChatVolume);
    const firstArc = volDetail?.arcs?.[0]?.idx;
    if (firstArc) {
      wizardState.chaptersChatArc = firstArc;
      loadChaptersChat(wizardState.chaptersChatVolume, firstArc);
    } else {
      renderChaptersChat(wizardState.chaptersChatVolume, 0, { turns: [] });
    }
  });
  $("#chapters-arc-select")?.addEventListener("change", () => {
    wizardState.chaptersChatArc = Number($("#chapters-arc-select").value) || 1;
    loadChaptersChat(wizardState.chaptersChatVolume, wizardState.chaptersChatArc);
  });
  $("#send-chapters-chat")?.addEventListener("click", () => sendChaptersMessage(volume, arcIdx));
  const jobActive = job && ["running", "pausing", "paused", "stopping"].includes(job.status);
  if (jobActive) {
    $("#send-chapters-chat").disabled = true;
    $("#chapters-chat-input").disabled = true;
    $("#chapters-volume-select").disabled = true;
    $("#chapters-arc-select").disabled = true;
    $("#chapter-system-panel-mode").disabled = true;
  }
  $("#chapter-system-panel-mode")?.addEventListener("change", async () => {
    try {
      const mode = $("#chapter-system-panel-mode").value;
      wizardState.systemPanelStatus = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/chapters/system-panel`, {
        method: "POST", body: JSON.stringify({ mode }),
      });
      showToast(mode === "auto" ? "将在首次生成章纲时自动判断。" : mode === "enabled" ? "已启用系统面板。" : "已关闭系统面板，已有状态文件会保留。");
      loadChaptersChat(volume, arcIdx);
    } catch (error) { showToast(error.message || "无法更新系统面板设置。", true); }
  });
  $("#pause-chapters-job")?.addEventListener("click", () => controlChaptersJob(volume, arcIdx, "pause"));
  $("#resume-chapters-job")?.addEventListener("click", () => controlChaptersJob(volume, arcIdx, "resume"));
  $("#stop-chapters-job")?.addEventListener("click", () => controlChaptersJob(volume, arcIdx, "stop"));
  $("#continue-chapters-job")?.addEventListener("click", () => controlChaptersJob(volume, arcIdx, "continue"));
  const chatInput = $("#chapters-chat-input");
  const autoGrow = () => { if (chatInput) { chatInput.style.height = "auto"; chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + "px"; } };
  chatInput?.addEventListener("input", autoGrow);
  chatInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); sendChaptersMessage(volume, arcIdx); }
  });
  $$("[data-artifact-path]").forEach((btn) => btn.addEventListener("click", () => openReviewFile(btn.dataset.artifactPath)));
  $("#reset-chapters-chat")?.addEventListener("click", async () => {
    if (!confirm(`将删除情节单元${arcIdx}（卷${volume}）的所有章纲、对应系统面板并清空对话。确认重置？`)) return;
    try {
      await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/chapters/${volume}/${arcIdx}/reset`, { method: "POST", body: JSON.stringify({}) });
      await refreshWorkspaceArtifacts();
      const data = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/chapters/${volume}/${arcIdx}/conversation`);
      renderChaptersChat(volume, arcIdx, data);
      showToast("已重置，下一条消息将重新生成。");
    } catch (error) { showToast(error.message || "无法重置。", true); }
  });
}

async function loadChaptersChat(volume, arcIdx) {
  if (!arcIdx) { renderChaptersChat(volume, 0, { turns: [] }); return; }
  try {
    const base = `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/chapters/${volume}/${arcIdx}`;
    const [data, job] = await Promise.all([api(`${base}/conversation`), api(`${base}/job`)]);
    try {
      wizardState.systemPanelStatus = await api(
        `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/chapters/system-panel`,
      );
    } catch (_) {
      wizardState.systemPanelStatus = {
        selection_mode: "auto", decided: false, enabled: false, unavailable: true,
      };
    }
    renderChaptersChat(volume, arcIdx, data, job);
    if (["running", "pausing", "paused", "stopping"].includes(job.status)) pollChaptersJob(volume, arcIdx);
  } catch (error) {
    renderChaptersChat(volume, arcIdx, { turns: [] }, { status: "idle" });
    showToast(error.message || "无法加载章纲对话。", true);
  }
}

let chaptersJobPollTimer = null;

async function controlChaptersJob(volume, arcIdx, action) {
  try {
    const base = `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/chapters/${volume}/${arcIdx}`;
    const job = await api(`${base}/${action}`, { method: "POST", body: JSON.stringify({}) });
    const conversation = await api(`${base}/conversation`);
    renderChaptersChat(volume, arcIdx, conversation, job);
    pollChaptersJob(volume, arcIdx);
  } catch (error) { showToast(error.message || "无法控制章纲任务。", true); }
}

function pollChaptersJob(volume, arcIdx) {
  if (chaptersJobPollTimer) clearTimeout(chaptersJobPollTimer);
  const poll = async () => {
    if (Number(wizardState.chaptersChatVolume) !== Number(volume) || Number(wizardState.chaptersChatArc) !== Number(arcIdx)) return;
    try {
      const base = `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/chapters/${volume}/${arcIdx}`;
      const job = await api(`${base}/job`);
      const key = `${volume}:${arcIdx}`;
      if (["running", "pausing", "paused", "stopping"].includes(job.status)) {
        const completed = Number(job.completed || 0);
        if (completed > Number(wizardState.chaptersJobCompleted[key] || 0)) {
          wizardState.chaptersJobCompleted[key] = completed;
          await refreshReviewArtifactsOnly(job.progress_kind === "serial_chapter_refine", "chapters");
        }
        const progress = $("#chapters-job-progress");
        if (progress) {
          const holder = document.createElement("div");
          holder.innerHTML = chaptersJobMarkup(job);
          progress.replaceWith(holder.firstElementChild);
          $("#pause-chapters-job")?.addEventListener("click", () => controlChaptersJob(volume, arcIdx, "pause"));
          $("#resume-chapters-job")?.addEventListener("click", () => controlChaptersJob(volume, arcIdx, "resume"));
          $("#stop-chapters-job")?.addEventListener("click", () => controlChaptersJob(volume, arcIdx, "stop"));
        } else {
          renderChaptersChat(volume, arcIdx, await api(`${base}/conversation`), job);
        }
        chaptersJobPollTimer = setTimeout(poll, 900);
        return;
      }
      await refreshWorkspaceArtifacts();
      renderChaptersChat(volume, arcIdx, await api(`${base}/conversation`), job);
      if (job.status === "failed") showToast(job.error || "章纲生成失败。", true);
      else if (job.status === "stopped") showToast("已结束本轮章纲生成，已完成内容均已保留。");
      else if (job.status === "completed") showToast("章纲生成完成。");
    } catch (_) { chaptersJobPollTimer = setTimeout(poll, 1500); }
  };
  poll();
}

async function sendChaptersMessage(volume, arcIdx) {
  const input = $("#chapters-chat-input");
  const message = (input?.value || "").trim();
  if (!message) return;
  const button = $("#send-chapters-chat");
  if (button) button.disabled = true;
  if (input) input.disabled = true;
  const list = $("#chat-message-list");
  const empty = list?.querySelector(".chat-empty");
  if (empty) empty.remove();
  if (list) {
    const li = document.createElement("li");
    li.className = "chat-message user";
    li.innerHTML = `<div class="chat-message-body">${escapeHtml(message)}</div>`;
    list.appendChild(li);
    const typing = document.createElement("li");
    typing.className = "chat-message assistant typing";
    typing.id = "chat-typing";
    typing.innerHTML = `<div class="chat-message-avatar">AI</div><div class="chat-message-content"><div class="chat-typing-dots"><span></span><span></span><span></span></div></div>`;
    list.appendChild(typing);
    list.scrollTop = list.scrollHeight;
  }
  if (input) input.value = "";
  try {
    const job = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/chapters/${volume}/${arcIdx}/chat`, {
      method: "POST", body: JSON.stringify({ message }),
    });
    wizardState.chaptersJobCompleted[`${volume}:${arcIdx}`] = Number(job.completed || 0);
    $("#chat-typing")?.remove();
    const conversation = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/chapters/${volume}/${arcIdx}/conversation`);
    renderChaptersChat(volume, arcIdx, conversation, job);
    pollChaptersJob(volume, arcIdx);
  } catch (error) {
    showToast(error.message || "生成失败，请重试。", true);
    loadChaptersChat(volume, arcIdx);
  } finally {}
}

function draftJobMarkup(job) {
  if (!job) return "";
  if (job.status === "idle" && job.can_resume) {
    return `<div class="chat-job-progress is-interrupted" id="draft-job-progress"><div class="chat-job-progress-main"><span class="chat-job-status-dot"></span><div class="chat-job-progress-copy"><strong>上次生成在第 ${Number(job.next_chapter)} 章前中断</strong><span>已保留 ${Number(job.completed || 0)} / ${Number(job.total || 0)} 章正文</span></div><button id="continue-draft-job" class="chat-job-action resume continue" type="button">▶ 继续生成</button></div></div>`;
  }
  if (["idle", "completed", "failed", "stopped"].includes(job.status)) return "";
  const total = Number(job.total || 0), completed = Number(job.completed || 0);
  const paused = job.status === "paused", stopping = job.status === "stopping";
  const routing = job.progress_kind === "serial_draft_refine" && job.phase === "routing";
  const pause = paused ? '<button id="resume-draft-job" class="chat-job-action resume" type="button">▶ 继续</button>' : '<button id="pause-draft-job" class="chat-job-action" type="button">Ⅱ 暂停</button>';
  const promptAction = Number(job.prompt_count || 0) > 0 ? `<button id="show-draft-prompt" class="chat-job-action prompt" type="button">Prompt · ${Number(job.prompt_count)}</button>` : "";
  return `<div class="chat-job-progress ${paused ? "is-paused" : ""} ${routing ? "is-refining" : ""}" id="draft-job-progress"><div class="chat-job-progress-main"><span class="chat-job-status-dot"></span><div class="chat-job-progress-copy"><strong>${escapeHtml(job.message || "正在生成正文")}</strong><span>${routing ? "正在判断最早受影响章节" : `${completed} / ${total || "—"} 章`}</span></div><div class="chat-job-actions">${promptAction}${pause}<button id="stop-draft-job" class="chat-job-action stop" type="button" ${stopping ? "disabled" : ""}>■ ${stopping ? "结束中" : "结束"}</button></div></div><div class="chat-job-progress-track"><i style="width:${total ? Math.round(completed * 100 / total) : 3}%"></i></div></div>`;
}

function draftChatPanelMarkup(volume, arcIdx, conversation, job = null) {
  const volumes = wizardState.summary?.volumes || [];
  const detail = volumes.find((item) => Number(item.volume) === Number(volume)) || { arcs: [] };
  const arcs = detail.arcs || [], turns = Array.isArray(conversation?.turns) ? conversation.turns : [];
  const guide = conversation?.writing_guide || {};
  const resetBtn = (turns.length || conversation?.has_drafts)
    ? '<button id="reset-draft-chat" class="chat-icon-btn" type="button" title="删除当前情节单元的全部正文并重新开始">⟳ 重置</button>'
    : "";
  const volumeSelector = `<select id="draft-chat-volume">${volumes.map((item) => `<option value="${item.volume}" ${Number(volume) === Number(item.volume) ? "selected" : ""}>第 ${item.volume} 舞台 / 卷</option>`).join("")}</select>`;
  const arcSelector = arcs.length ? `<select id="draft-chat-arc">${arcs.map((arc) => `<option value="${arc.idx}" ${Number(arcIdx) === Number(arc.idx) ? "selected" : ""}>情节单元${arc.idx}${arc.title ? ` · ${escapeHtml(arc.title)}` : ""}（第${arc.start_ch}-${arc.end_ch}章）</option>`).join("")}</select>` : '<select id="draft-chat-arc" disabled><option>该舞台暂无故事情节</option></select>';
  return `<section class="chat-panel draft-chat-panel"><header class="chat-panel-bar"><span class="chat-panel-bar-label">舞台 / 卷号</span>${volumeSelector}<span class="chat-panel-bar-label">故事情节</span>${arcSelector}</header>
    <div class="writing-guide-bar"><div><strong>生文规范</strong><span>${guide.custom ? "当前使用自定义规范" : "当前使用项目默认 system_prompt.md"}</span></div><div class="writing-guide-actions"><input id="draft-guide-file" type="file" accept=".txt,.md" hidden><button id="upload-draft-guide" class="chat-icon-btn" type="button">上传规范</button>${guide.custom ? '<button id="reset-draft-guide" class="chat-icon-btn" type="button">恢复默认</button>' : ""}</div></div>
    <div class="chat-scroll" id="chat-message-list">${turns.map(chatMessageMarkup).join("") || `<div class="chat-empty"><div class="chat-empty-icon">✍</div><p>${arcs.length ? "输入本情节正文的生成要求，开始逐章串行创作。" : "请先生成故事情节和逐章章纲。"}</p></div>`}</div>${draftJobMarkup(job)}
    <div class="chat-composer"><div class="chat-input-row"><textarea id="draft-chat-input" class="chat-input" rows="1" placeholder="输入正文生成或调整要求"></textarea><button id="send-draft-chat" class="chat-send-btn" type="button" title="发送（Ctrl/⌘+Enter）" aria-label="发送" ${arcs.length ? "" : "disabled"}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button></div><div class="chat-composer-meta draft-chat-options"><label class="draft-humanize-option"><input id="draft-chat-humanize" type="checkbox" ${wizardState.draftChatHumanize === false ? "" : "checked"} /><span>生成后自动去 AI 味精修</span></label>${resetBtn}</div></div></section>`;
}

function renderDraftChat(volume, arcIdx, conversation, job = null) {
  const host = $("#draft-chat-host"); if (!host) return;
  host.innerHTML = draftChatPanelMarkup(volume, arcIdx, conversation, job);
  const active = job && ["running", "pausing", "paused", "stopping"].includes(job.status);
  if (active) ["#draft-chat-volume", "#draft-chat-arc", "#draft-chat-input", "#draft-chat-humanize", "#send-draft-chat"].forEach((s) => { if ($(s)) $(s).disabled = true; });
  $("#draft-chat-volume")?.addEventListener("change", () => { wizardState.draftChatVolume = Number($("#draft-chat-volume").value); const d = (wizardState.summary?.volumes || []).find((v) => Number(v.volume) === wizardState.draftChatVolume); wizardState.draftChatArc = d?.arcs?.[0]?.idx || null; loadDraftChat(wizardState.draftChatVolume, wizardState.draftChatArc); });
  $("#draft-chat-arc")?.addEventListener("change", () => { wizardState.draftChatArc = Number($("#draft-chat-arc").value); loadDraftChat(volume, wizardState.draftChatArc); });
  $("#send-draft-chat")?.addEventListener("click", () => sendDraftMessage(volume, arcIdx));
  $("#draft-chat-humanize")?.addEventListener("change", () => { wizardState.draftChatHumanize = Boolean($("#draft-chat-humanize")?.checked); });
  $("#draft-chat-input")?.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendDraftMessage(volume, arcIdx); } });
  for (const action of ["pause", "resume", "stop", "continue"]) $(`#${action}-draft-job`)?.addEventListener("click", () => controlDraftJob(volume, arcIdx, action));
  $("#upload-draft-guide")?.addEventListener("click", () => $("#draft-guide-file")?.click());
  $("#draft-guide-file")?.addEventListener("change", async () => { const file = $("#draft-guide-file")?.files?.[0]; if (!file) return; try { const upload = await uploadFile(file); await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/drafts/writing-guide`, { method: "POST", body: JSON.stringify({ upload_id: upload.id }) }); showToast("自定义生文规范已保存。"); loadDraftChat(volume, arcIdx); } catch (e) { showToast(e.message || "无法保存生文规范。", true); } });
  $("#reset-draft-guide")?.addEventListener("click", async () => { await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/drafts/writing-guide`, { method: "DELETE" }); showToast("已恢复项目默认 system_prompt.md。"); loadDraftChat(volume, arcIdx); });
  $("#reset-draft-chat")?.addEventListener("click", async () => {
    const volumeDetail = (wizardState.summary?.volumes || []).find(
      (item) => Number(item.volume) === Number(volume),
    );
    const selectedArc = (volumeDetail?.arcs || []).find(
      (item) => Number(item.idx) === Number(arcIdx),
    );
    const chapterRange = selectedArc
      ? `第 ${selectedArc.start_ch}-${selectedArc.end_ch} 章`
      : "当前情节单元";
    if (!confirm(`将删除${chapterRange}的原始正文、精修正文、历史版本和最终版标记。确认重置？`)) return;
    try {
      await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/drafts/${volume}/${arcIdx}/reset`, {
        method: "POST", body: JSON.stringify({}),
      });
      const progressKey = `${volume}:${arcIdx}`;
      wizardState.draftJobCompleted[progressKey] = 0;
      delete wizardState.draftJobIds[progressKey];
      await refreshWorkspaceArtifacts();
      await loadDraftChat(volume, arcIdx);
      showToast("当前故事情节单元的正文已重置。");
    } catch (error) {
      showToast(error.message || "无法重置正文。", true);
    }
  });
  $$("[data-artifact-path]").forEach((button) => button.addEventListener("click", () => openReviewFile(button.dataset.artifactPath)));
}

let draftJobPollTimer = null;
async function loadDraftChat(volume, arcIdx) {
  if (!arcIdx) {
    try {
      const guide = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/drafts/writing-guide`);
      renderDraftChat(volume, 0, { turns: [], writing_guide: guide });
    } catch (_) { renderDraftChat(volume, 0, { turns: [], writing_guide: { custom: false } }); }
    return;
  }
  try { const base = `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/drafts/${volume}/${arcIdx}`; const [conversation, job] = await Promise.all([api(`${base}/conversation`), api(`${base}/job`)]); renderDraftChat(volume, arcIdx, conversation, job); if (["running", "pausing", "paused", "stopping"].includes(job.status)) pollDraftJob(volume, arcIdx); } catch (e) { showToast(e.message || "无法加载正文对话。", true); }
}
async function sendDraftMessage(volume, arcIdx) {
  const message = ($("#draft-chat-input")?.value || "").trim(); if (!message) return;
  try { const base = `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/drafts/${volume}/${arcIdx}`; const humanize = $("#draft-chat-humanize")?.checked !== false; wizardState.draftChatHumanize = humanize; const job = await api(`${base}/chat`, { method: "POST", body: JSON.stringify({ message, humanize }) }); const key = `${volume}:${arcIdx}`; wizardState.draftJobCompleted[key] = 0; wizardState.draftJobIds[key] = job.id || ""; renderDraftChat(volume, arcIdx, await api(`${base}/conversation`), job); pollDraftJob(volume, arcIdx); } catch (e) { showToast(e.message || "无法开始正文生成。", true); }
}
async function controlDraftJob(volume, arcIdx, action) {
  try { const base = `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/drafts/${volume}/${arcIdx}`; const job = await api(`${base}/${action}`, { method: "POST", body: JSON.stringify({}) }); renderDraftChat(volume, arcIdx, await api(`${base}/conversation`), job); pollDraftJob(volume, arcIdx); } catch (e) { showToast(e.message || "无法控制正文任务。", true); }
}
function pollDraftJob(volume, arcIdx) {
  if (draftJobPollTimer) clearTimeout(draftJobPollTimer);
  const poll = async () => { if (Number(wizardState.draftChatVolume) !== Number(volume) || Number(wizardState.draftChatArc) !== Number(arcIdx)) return; const base = `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/drafts/${volume}/${arcIdx}`; try { const job = await api(`${base}/job`); if (["running", "pausing", "paused", "stopping"].includes(job.status)) { const key = `${volume}:${arcIdx}`, jobId = job.id || "", done = Number(job.completed || 0); if (jobId && wizardState.draftJobIds[key] !== jobId) { wizardState.draftJobIds[key] = jobId; wizardState.draftJobCompleted[key] = 0; } if (done > Number(wizardState.draftJobCompleted[key] || 0)) { wizardState.draftJobCompleted[key] = done; const refining = job.progress_kind === "serial_draft_refine"; await refreshReviewArtifactsOnly(refining, "draft", !refining); } const progress = $("#draft-job-progress"); if (progress) { const holder = document.createElement("div"); holder.innerHTML = draftJobMarkup(job); progress.replaceWith(holder.firstElementChild); for (const action of ["pause", "resume", "stop"]) $(`#${action}-draft-job`)?.addEventListener("click", () => controlDraftJob(volume, arcIdx, action)); } else { renderDraftChat(volume, arcIdx, await api(`${base}/conversation`), job); } draftJobPollTimer = setTimeout(poll, 1000); return; } await refreshWorkspaceArtifacts(); renderDraftChat(volume, arcIdx, await api(`${base}/conversation`), job); if (job.status === "failed") showToast(job.error || "正文生成失败。", true); else if (job.status === "stopped") showToast("已结束本轮正文生成。"); else if (job.status === "completed") showToast("正文生成完成。"); } catch (_) { draftJobPollTimer = setTimeout(poll, 1500); } }; poll();
}

function chatArtifactCards(artifacts) {
  if (!Array.isArray(artifacts) || !artifacts.length) return "";
  const cards = artifacts.map((item) => {
    const name = escapeHtml((item.path || "").split("/").pop() || "文件");
    const label = escapeHtml(item.label || name);
    const path = escapeHtml(item.path || "");
    return `<button class="chat-artifact-card" data-artifact-path="${path}" type="button"><span class="chat-artifact-card-icon">📄</span><span class="chat-artifact-card-label">${label}</span><span class="chat-artifact-card-name">${name}</span></button>`;
  }).join("");
  return `<div class="chat-artifacts">${cards}</div>`;
}

function chatMessageMarkup(turn) {
  const isUser = turn.role === "user";
  if (isUser) {
    return `<li class="chat-message user"><div class="chat-message-body">${escapeHtml(turn.content || "")}</div></li>`;
  }
  const artCards = chatArtifactCards(turn.artifacts);
  return `<li class="chat-message assistant"><div class="chat-message-avatar">AI</div><div class="chat-message-content"><div class="chat-message-body">${escapeHtml(turn.content || "")}</div>${artCards}</div></li>`;
}

function designJobMarkup(job) {
  if (job && ["idle", "stopped", "failed"].includes(job.status) && job.can_resume) {
    const completed = Number(job.completed || 0);
    const total = Math.max(1, Number(job.total || 1));
    const percent = Math.max(0, Math.min(100, Math.round(completed * 100 / total)));
    return `<div class="chat-job-progress is-interrupted" id="design-job-progress">
      <div class="chat-job-progress-main">
        <span class="chat-job-status-dot" aria-hidden="true"></span>
        <div class="chat-job-progress-copy">
          <strong>舞台设计尚未完成</strong>
          <span>已保留 ${completed} / ${total} 个舞台</span>
        </div>
        <button id="continue-design-job" class="chat-job-action resume continue" type="button"><span>▶</span>继续生成</button>
      </div>
      <div class="chat-job-progress-track"><i style="width:${percent}%"></i></div>
    </div>`;
  }
  if (!job || !["queued", "running", "pausing", "paused", "stopping"].includes(job.status)) return "";
  const completed = Number(job.completed || 0);
  const total = Math.max(1, Number(job.total || 1));
  const percent = Math.max(3, Math.min(100, Math.round(completed * 100 / total)));
  const paused = job.status === "paused";
  const pausing = job.status === "pausing";
  const stopping = job.status === "stopping";
  const promptAction = Number(job.prompt_count || 0) > 0
    ? `<button id="show-design-prompt" class="chat-job-action prompt" type="button">Prompt · ${Number(job.prompt_count)}</button>`
    : "";
  const stageActions = job.progress_kind === "stage_design"
    ? `<div class="chat-job-actions">${promptAction}${paused
        ? '<button id="resume-design-job" class="chat-job-action resume" type="button"><span>▶</span>继续</button>'
        : `<button id="pause-design-job" class="chat-job-action" type="button" ${(pausing || stopping) ? "disabled" : ""}><span>${pausing ? "…" : "Ⅱ"}</span>${pausing ? "暂停中" : "暂停"}</button>`}
       <button id="stop-design-job" class="chat-job-action stop" type="button" ${stopping ? "disabled" : ""}><span>■</span>${stopping ? "结束中" : "结束"}</button></div>`
    : (promptAction ? `<div class="chat-job-actions">${promptAction}</div>` : "");
  const progressMeta = job.progress_kind === "design_concept"
    ? `${completed} / ${total} 项设计 · ${Math.round(completed * 100 / total)}%`
    : stopping ? `正在结束 · 已完成 ${completed} / ${total} 个舞台`
    : paused ? `已暂停 · ${completed} / ${total} 个舞台`
    : `${completed} / ${total} 个舞台 · ${Math.round(completed * 100 / total)}%`;
  return `<div class="chat-job-progress ${paused ? "is-paused" : pausing ? "is-pausing" : stopping ? "is-stopping" : ""}" id="design-job-progress">
    <div class="chat-job-progress-main">
      <span class="chat-job-status-dot" aria-hidden="true"></span>
      <div class="chat-job-progress-copy">
        <strong>${escapeHtml(job.message || "正在生成全书设计")}</strong>
        <span>${progressMeta}</span>
      </div>
      ${stageActions}
    </div>
    <div class="chat-job-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(completed * 100 / total)}"><i style="width:${percent}%"></i></div>
  </div>`;
}

function designChatPanelMarkup(scope, conversation, job = null) {
  const turns = (conversation && Array.isArray(conversation.turns)) ? conversation.turns : [];
  const busy = Boolean(job && ["queued", "running", "pausing", "paused", "stopping"].includes(job.status));
  const sd = wizardState.summary?.story_design || {};
  const filesExist = scope === "concept" ? Boolean(sd.concept_ready) : Boolean(sd.stage_assets_exist ?? sd.stage_ready);
  const placeholder = filesExist
    ? "描述本轮要调整的内容（在上一版基础上整文件重写，未涉及部分保留）…"
    : (scope === "concept" ? "写下题材、主角、金手指、冲突或任何灵感，开始生成第一版…" : "基于粗略大纲与世界观，生成长线主线与舞台路线图…");
  const messages = turns.map(chatMessageMarkup).join("");
  const resetBtn = filesExist && !busy ? '<button id="reset-design-chat" class="chat-icon-btn" type="button" title="删除当前产物并重新开始">⟳ 重置</button>' : "";
  const emptyHint = filesExist
    ? "已生成初版。继续输入修改要求，例如「主角金手指改为推演能力」「舞台1改为势力对抗」。"
    : (scope === "concept" ? "还没有内容。写下你的灵感，生成第一版粗略大纲与世界观。" : "还没有内容。写下对长线主线与舞台的设想，开始生成。");
  const unusedReference = Number(sd.unused_reference_chapter_count || 0);
  const referenceOption = scope === "concept" && filesExist && unusedReference > 0
    ? `<label class="chat-reference-option">
        <input id="use-new-reference" type="checkbox" />
        <span class="chat-reference-switch" aria-hidden="true"><i></i></span>
        <span class="chat-reference-copy">
          <span><strong>同步新增拆解到阶段粗纲</strong><b>${unusedReference} 章待处理</b></span>
          <small>只调整最后一个阶段，或在参考小说新增分卷时追加阶段</small>
        </span>
      </label>`
    : "";
  const stageSyncOption = scope === "stage" && filesExist && Boolean(sd.stage_sync_pending)
    ? `<label class="chat-reference-option">
        <input id="sync-stage-design" type="checkbox" />
        <span class="chat-reference-switch" aria-hidden="true"><i></i></span>
        <span class="chat-reference-copy">
          <span><strong>同步阶段粗纲变化</strong><b>阶段粗纲已更新</b></span>
          <small>只调整最后一个舞台，或在新增阶段时追加舞台</small>
        </span>
      </label>`
    : "";
  const nameSynopsisAction = scope === "stage" && filesExist && !busy
    ? '<button id="refresh-name-synopsis" class="chat-icon-btn" type="button">重新生成书名与简介</button>'
    : "";
  return `<section class="chat-panel" id="design-chat" data-scope="${scope}">
    <div class="chat-scroll" id="chat-message-list">${messages || `<div class="chat-empty"><div class="chat-empty-icon">💬</div><p>${emptyHint}</p></div>`}</div>
    ${designJobMarkup(job)}
    <div class="chat-composer">
      <div class="chat-attachments" id="chat-attachments"></div>
      <div class="chat-input-row">
        <button class="chat-attach-button" id="chat-attach" type="button" title="加载文件作为参考" aria-label="加载文件" ${busy ? "disabled" : ""}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg></button>
        <textarea id="chat-input" class="chat-input" placeholder="${placeholder}" rows="1" ${busy ? "disabled" : ""}></textarea>
        <button id="send-design-chat" class="chat-send-btn" type="button" title="发送（Ctrl/⌘+Enter）" ${busy ? "disabled" : ""}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
      </div>
      ${referenceOption}
      ${stageSyncOption}
      <div class="chat-composer-meta">${nameSynopsisAction}${resetBtn}</div>
    </div>
    <input id="chat-attach-input" type="file" multiple accept=".txt,.md,.json,.yaml,.yml,.csv" hidden />
  </section>`;
}

function chatAttachments(scope) {
  if (!wizardState.chatAttachments) wizardState.chatAttachments = {};
  if (!wizardState.chatAttachments[scope]) wizardState.chatAttachments[scope] = [];
  return wizardState.chatAttachments[scope];
}

function renderChatAttachments(scope) {
  const host = $("#chat-attachments");
  if (!host) return;
  const items = chatAttachments(scope);
  host.innerHTML = items.map((item, index) => `<span class="chat-attachment-chip">${escapeHtml(item.name)}<button type="button" class="chat-attachment-remove" data-remove-attachment="${index}" aria-label="移除附件">×</button></span>`).join("");
  host.classList.toggle("has-items", items.length > 0);
  $$("[data-remove-attachment]").forEach((btn) => btn.addEventListener("click", () => {
    chatAttachments(scope).splice(Number(btn.dataset.removeAttachment), 1);
    renderChatAttachments(scope);
  }));
}

function bindChatAttach(scope) {
  const picker = $("#chat-attach-input");
  $("#chat-attach")?.addEventListener("click", () => picker?.click());
  picker?.addEventListener("change", () => {
    const files = Array.from(picker.files || []);
    picker.value = "";
    if (!files.length) return;
    let pending = files.length;
    const done = () => { pending -= 1; if (pending === 0) renderChatAttachments(scope); };
    files.forEach((file) => {
      if (file.size > 1024 * 1024 * 2) { showToast(`「${file.name}」超过 2MB，未加载（请精简后重试）。`, true); done(); return; }
      const reader = new FileReader();
      reader.onload = () => { chatAttachments(scope).push({ name: file.name, content: String(reader.result || "") }); done(); };
      reader.onerror = () => { showToast(`无法读取「${file.name}」。`, true); done(); };
      reader.readAsText(file, "utf-8");
    });
  });
}

function renderDesignChat(scope, conversation, job = null) {
  const node = $("#design-chat-host");
  if (!node) return;
  node.innerHTML = designChatPanelMarkup(scope, conversation, job);
  const list = $("#chat-message-list");
  if (list) list.scrollTop = list.scrollHeight;
  renderChatAttachments(scope);
  bindChatAttach(scope);
  $$("[data-artifact-path]").forEach((btn) => btn.addEventListener("click", () => openReviewFile(btn.dataset.artifactPath)));
  $("#send-design-chat")?.addEventListener("click", () => sendDesignMessage(scope));
  bindDesignJobControls(scope);
  $("#refresh-name-synopsis")?.addEventListener("click", async () => {
    try { await refreshNameSynopsis(); } catch (error) { showToast(error.message || "无法生成书名与简介。", true); }
  });
  const chatInput = $("#chat-input");
  const autoGrow = () => { if (chatInput) { chatInput.style.height = "auto"; chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + "px"; } };
  chatInput?.addEventListener("input", autoGrow);
  chatInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); sendDesignMessage(scope); }
  });
  $("#reset-design-chat")?.addEventListener("click", async () => {
    const msg = scope === "concept" ? "将删除当前粗略大纲与世界观并清空对话，下一条消息会重新生成初版。确认重置？" : "将删除当前长线主线、舞台路线图、书名与简介，并清空对话。下一条消息会重新生成初版，确认重置？";
    if (!confirm(msg)) return;
    try {
      await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/design/${scope}/reset`, { method: "POST", body: JSON.stringify({}) });
      wizardState.chatAttachments[scope] = [];
      await refreshWorkspaceArtifacts();
      const data = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/design/${scope}/conversation`);
      renderDesignChat(scope, data);
      showToast("已重置，下一条消息将重新生成初版。");
    } catch (error) { showToast(error.message || "无法重置。", true); }
  });
}

async function loadDesignChat(scope) {
  try {
    const base = `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/design/${scope}`;
    const [data, job] = await Promise.all([api(`${base}/conversation`), api(`${base}/job`)]);
    renderDesignChat(scope, data, job);
    if (["queued", "running", "pausing", "paused", "stopping"].includes(job.status)) pollDesignJob(scope);
  } catch (_) { /* ignore */ }
}

let designJobPollTimer = null;

function bindDesignJobControls(scope) {
  $("#pause-design-job")?.addEventListener("click", () => controlDesignJob(scope, "pause"));
  $("#resume-design-job")?.addEventListener("click", () => controlDesignJob(scope, "resume"));
  $("#stop-design-job")?.addEventListener("click", () => controlDesignJob(scope, "stop"));
  $("#continue-design-job")?.addEventListener("click", () => controlDesignJob(scope, "continue"));
  $("#show-design-prompt")?.addEventListener("click", () => showJobPrompts(
    `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/design/${scope}/prompts`,
    scope === "concept" ? "全书设计 · 模型 Prompt" : "舞台设计 · 模型 Prompt",
  ));
}

async function controlDesignJob(scope, action) {
  try {
    const job = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/design/${scope}/${action}`, {
      method: "POST", body: JSON.stringify({}),
    });
    const progress = $("#design-job-progress");
    if (progress) {
      const holder = document.createElement("div");
      holder.innerHTML = designJobMarkup(job);
      progress.replaceWith(holder.firstElementChild);
      bindDesignJobControls(scope);
    }
    pollDesignJob(scope);
  } catch (error) {
    showToast(error.message || "无法控制舞台设计任务。", true);
  }
}

function pollDesignJob(scope) {
  if (designJobPollTimer) clearTimeout(designJobPollTimer);
  const expectedStep = scope === "concept" ? "design" : "stage";
  const poll = async () => {
    if (wizardState.activeStep !== expectedStep) return;
    const base = `/api/workspaces/${encodeURIComponent(wizardState.workspace)}/design/${scope}`;
    try {
      const job = await api(`${base}/job`);
      if (["queued", "running", "pausing", "paused", "stopping"].includes(job.status)) {
        const completed = Number(job.completed || 0);
        const previous = Number(wizardState.designJobCompleted[scope] || 0);
        if (completed > previous) {
          wizardState.designJobCompleted[scope] = completed;
          await refreshReviewArtifactsOnly(false, expectedStep, true);
        }
        const progress = $("#design-job-progress");
        if (progress) {
          const holder = document.createElement("div");
          holder.innerHTML = designJobMarkup(job);
          progress.replaceWith(holder.firstElementChild);
          bindDesignJobControls(scope);
        } else {
          const conversation = await api(`${base}/conversation`);
          renderDesignChat(scope, conversation, job);
        }
        designJobPollTimer = setTimeout(poll, 900);
        return;
      }
      await refreshWorkspaceArtifacts();
      const conversation = await api(`${base}/conversation`);
      renderDesignChat(scope, conversation, job);
      if (job.status === "failed") showToast(job.error || "全书设计生成失败，请重试。", true);
      else if (job.status === "stopped") showToast("已结束本轮舞台设计，已完成内容均已保留。");
      else if (job.status === "completed") showToast(scope === "concept" ? "全书设计生成完成。" : "舞台设计生成完成。");
    } catch (_) {
      designJobPollTimer = setTimeout(poll, 1500);
    }
  };
  poll();
}

async function sendDesignMessage(scope) {
  const input = $("#chat-input");
  const message = (input?.value || "").trim();
  const attachments = chatAttachments(scope).map((item) => ({ name: item.name, content: item.content }));
  const useNewReference = Boolean($("#use-new-reference")?.checked);
  const syncUpdatedDesign = Boolean($("#sync-stage-design")?.checked);
  if (!message && !attachments.length && !useNewReference && !syncUpdatedDesign) return;
  const button = $("#send-design-chat");
  const attachButton = $("#chat-attach");
  if (button) button.disabled = true;
  if (attachButton) attachButton.disabled = true;
  if (input) input.disabled = true;
  const list = $("#chat-message-list");
  const empty = list?.querySelector(".chat-empty");
  if (empty) empty.remove();
  if (list) {
    const li = document.createElement("li");
    li.className = "chat-message user";
    const preview = attachments.length ? `${message}\n（附件：${attachments.map((a) => a.name).join("、")}）` : message;
    li.innerHTML = `<div class="chat-message-body">${escapeHtml(preview)}</div>`;
    list.appendChild(li);
    const typing = document.createElement("li");
    typing.className = "chat-message assistant typing";
    typing.id = "chat-typing";
    typing.innerHTML = `<div class="chat-message-avatar">AI</div><div class="chat-message-content"><div class="chat-typing-dots"><span></span><span></span><span></span></div></div>`;
    list.appendChild(typing);
    list.scrollTop = list.scrollHeight;
  }
  if (input) input.value = "";
  try {
    const job = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/design/${scope}/chat`, {
      method: "POST", body: JSON.stringify({
        message,
        attachments,
        use_new_reference: useNewReference,
        sync_updated_design: syncUpdatedDesign,
      }),
    });
    wizardState.chatAttachments[scope] = [];
    $("#chat-typing")?.remove();
    wizardState.designJobCompleted[scope] = 0;
    const composer = $("#design-chat .chat-composer");
    composer?.insertAdjacentHTML("beforebegin", designJobMarkup(job));
    bindDesignJobControls(scope);
    started = true;
    pollDesignJob(scope);
  } catch (error) {
    const message = error.message || "生成失败，请重试。";
    const typing = $("#chat-typing");
    if (typing) {
      typing.classList.remove("typing");
      typing.classList.add("error");
      typing.innerHTML = `<div class="chat-message-avatar">!</div><div class="chat-message-content"><div class="chat-message-body">生成失败：${escapeHtml(message)}</div></div>`;
    }
    showToast(message, true);
  } finally {
    if (!started) {
      if (button) button.disabled = false;
      if (attachButton) attachButton.disabled = false;
      if (input) input.disabled = false;
    }
  }
}








function stageOptions(selected = 1, includeEnd = false) {
  const stageCount = Math.max(0, Number(wizardState.summary?.story_design?.stage_count || 0));
  if (!stageCount) return `<input id="stage-volume" type="number" min="1" value="${selected}" />`;
  const options = Array.from({ length: stageCount }, (_, index) => {
    const value = index + 1;
    return `<option value="${value}" ${value === Number(selected) ? "selected" : ""}>第 ${value} 舞台 / 卷</option>`;
  });
  if (includeEnd) options.unshift('<option value="">追加到最后</option>');
  return `<select id="stage-volume">${options.join("")}</select>`;
}

function worldSources() {
  return wizardState.summary?.world_knowledge?.sources || [];
}

function worldForm() {
  const sources = worldSources();
  const worldReady = Boolean(wizardState.summary?.world_knowledge?.ready);
  const sourceList = sources.length
    ? `<div class="world-uploaded">
        <div class="world-uploaded-heading"><span>已上传</span><strong>${sources.length} 份资料</strong></div>
        <ul class="source-list">${sources.map((source) => `<li><strong>${escapeHtml(source.file_name)}</strong><span>${source.size ? `${Math.ceil(source.size / 1024).toLocaleString()} KB` : "已导入"}</span></li>`).join("")}</ul>
      </div>`
    : '<p class="reference-file-status">尚未上传目标世界资料</p>';
  return `
    <div class="reference-source world-source-flat" id="world-source">
      ${sourceList}
      <label class="reference-file-picker" id="world-file-picker" for="world-file-input"><span id="world-file-label">${sources.length ? "继续添加资料" : "选择资料文件"}</span><input id="world-file-input" type="file" multiple accept=".txt,.md,.json,.yaml,.yml,.csv,.tsv" /><small id="world-file-help">支持多选，最大文件自动作为主资料，其他文件用于补充设定。</small></label>
      <p id="world-file-status" class="reference-file-status">尚未选择新文件</p>
      <ul id="world-new-file-list" class="source-list world-new-file-list" hidden></ul>
    </div>
    ${sources.length ? `<div class="world-enable-row">
      <label class="world-toggle"><input id="world-enabled" type="checkbox" ${wizardState.summary?.world_knowledge?.enabled === false ? "" : "checked"} /><span class="world-toggle-text">启用目标世界资料库</span></label>
      <small>${worldReady ? "资料库 7 个栏目已完整构建。关闭后后续设计不再注入资料；再次打开即恢复使用。" : "导入后会自动构建；若任务中断，可不上传新文件，直接点击下方按钮重试。"}</small>
    </div>` : ""}`;
}

function mechanicsForm() {
  const configured = wizardState.summary?.mechanics?.mode && wizardState.summary.mechanics.mode !== "未初始化";
  const mode = wizardState.mechanicsMode === "none" ? "auto" : wizardState.mechanicsMode;
  wizardState.mechanicsMode = mode;
  return `<fieldset class="mechanics-source" id="mechanics-source"><legend>系统面板设定</legend>
    <div class="direction-source-switch" role="radiogroup" aria-label="系统面板设定方式">
      <label class="direction-source-option ${mode === "auto" ? "active" : ""}"><input name="mechanics-mode" value="auto" type="radio" ${mode === "auto" ? "checked" : ""} />自动判断</label>
      <label class="direction-source-option ${mode === "text" ? "active" : ""}"><input name="mechanics-mode" value="text" type="radio" ${mode === "text" ? "checked" : ""} />直接输入</label>
      <label class="direction-source-option ${mode === "file" ? "active" : ""}"><input name="mechanics-mode" value="file" type="radio" ${mode === "file" ? "checked" : ""} />读取文件</label>
    </div>
    <p class="decision-note" data-mechanics-panel="auto" ${mode === "auto" ? "" : "hidden"}>根据核心玩法判断是否需要系统面板、数值追踪或轻量状态约束。</p>
    <label data-mechanics-panel="text" ${mode === "text" ? "" : "hidden"}>系统面板设定<textarea id="mechanics-direction" placeholder="例如：功德值可兑换推演次数，升级需要消耗命格碎片。"></textarea></label>
    <div class="direction-file-panel" data-mechanics-panel="file" ${mode === "file" ? "" : "hidden"}><label class="direction-file-picker" for="mechanics-file-input"><span>选择系统面板设定文件</span><input id="mechanics-file-input" type="file" accept=".txt,.md,.json,.yaml,.yml" /><small>系统面板、数值公式和资源规则等会作为初始设定。</small></label><p id="mechanics-file-status" class="direction-file-status">${wizardState.mechanicsFile ? `已选择：${escapeHtml(wizardState.mechanicsFile.name)}` : "尚未选择文件"}</p></div>
    ${configured ? '<label class="check-label"><input id="mechanics-force" type="checkbox" />覆盖已有系统面板设定</label>' : ""}
  </fieldset>`;
}

function volumeForm(kind) {
  const stageCount = Number(wizardState.summary?.story_design?.stage_count || 0);
  const fieldId = `${kind}-volume`;
  const options = stageCount
    ? `<select id="${fieldId}">${Array.from({ length: stageCount }, (_, index) => `<option value="${index + 1}">第 ${index + 1} 舞台 / 卷</option>`).join("")}</select>`
    : `<input id="${fieldId}" type="number" min="1" value="1" />`;
  return `<fieldset class="generation-options"><legend>生成范围</legend><label>舞台 / 卷号${options}</label><label class="check-label"><input id="${kind}-force" type="checkbox" />覆盖该卷已有内容</label></fieldset>`;
}

function draftForm() {
  const stageCount = Number(wizardState.summary?.story_design?.stage_count || 0);
  const volumeDetails = wizardState.summary?.volumes || [];
  const volumes = stageCount
    ? `<select id="draft-volume">${Array.from({ length: stageCount }, (_, index) => `<option value="${index + 1}">第 ${index + 1} 舞台 / 卷</option>`).join("")}</select>`
    : '<input id="draft-volume" type="number" min="1" value="1" />';
  const firstVolume = volumeDetails.find((item) => Number(item.volume) === 1) || volumeDetails[0];
  const firstArcs = firstVolume?.arcs || [];
  const arcOptions = firstArcs.length
    ? firstArcs.map((arc) => `<option value="${arc.idx}" data-start="${arc.start_ch}" data-end="${arc.end_ch}">情节单元${arc.idx}${arc.title ? ` · ${escapeHtml(arc.title)}` : ""}（第${arc.start_ch}-${arc.end_ch}章）</option>`).join("")
    : '<option value="">该舞台暂无故事情节</option>';
  const firstArc = firstArcs[0];
  const firstCount = firstArc ? firstArc.end_ch - firstArc.start_ch + 1 : "";
  return `<fieldset class="generation-options"><legend>生成范围</legend>
    <div class="inline-number-fields">
      <label>舞台 / 卷号${volumes}</label>
      <label>故事情节<select id="draft-arc" ${firstArcs.length ? "" : "disabled"}>${arcOptions}</select></label>
    </div>
    <div class="draft-range-row">
      <p id="draft-range-hint" class="decision-note">${firstArc ? `本次范围：第 ${firstArc.start_ch}-${firstArc.end_ch} 章，共 ${firstCount} 章。` : "请先在「故事情节」步骤生成该舞台的故事情节。"}</p>
      <label>本次生成章节数<input id="draft-max" type="number" min="1" ${firstCount ? `max="${firstCount}" value="${firstCount}"` : "disabled"} /></label>
    </div>
    <label class="check-label"><input id="draft-humanize" type="checkbox" checked />生成后自动去 AI 味精修</label>
    <label class="check-label"><input id="draft-humanize-existing" type="checkbox" />只精修所选范围内的已有正文（不新写章节）</label>
  </fieldset>`;
}

function bindDraftRange() {
  const volumeInput = $("#draft-volume");
  const arcSelect = $("#draft-arc");
  const maxInput = $("#draft-max");
  const hint = $("#draft-range-hint");
  if (!volumeInput || !arcSelect || !maxInput || !hint) return;

  const updateRange = () => {
    const option = arcSelect.selectedOptions?.[0];
    const start = Number(option?.dataset.start || 0);
    const end = Number(option?.dataset.end || 0);
    const count = start && end >= start ? end - start + 1 : 0;
    maxInput.disabled = !count;
    if (count) {
      maxInput.max = String(count);
      maxInput.value = String(count);
      hint.textContent = `本次范围：第 ${start}-${end} 章，共 ${count} 章。`;
    } else {
      maxInput.removeAttribute("max");
      maxInput.value = "";
      hint.textContent = "请先在「故事情节」步骤生成该舞台的故事情节。";
    }
  };

  const updateArcs = () => {
    const volume = Number(volumeInput.value || 0);
    const detail = (wizardState.summary?.volumes || []).find((item) => Number(item.volume) === volume);
    const arcs = detail?.arcs || [];
    arcSelect.innerHTML = arcs.length
      ? arcs.map((arc) => `<option value="${arc.idx}" data-start="${arc.start_ch}" data-end="${arc.end_ch}">情节单元${arc.idx}${arc.title ? ` · ${escapeHtml(arc.title)}` : ""}（第${arc.start_ch}-${arc.end_ch}章）</option>`).join("")
      : '<option value="">该舞台暂无故事情节</option>';
    arcSelect.disabled = !arcs.length;
    updateRange();
  };

  volumeInput.addEventListener("change", updateArcs);
  arcSelect.addEventListener("change", updateRange);
  updateArcs();
}

function formForStep(step) {
  if (step.id === "reference") {
    const reference = referenceStatus();
    if (reference.hasExisting) {
      const coverage = reference.total
        ? `${reference.processed} / ${reference.total} 章`
        : `${reference.processed || reference.stagedChapters} 章`;
      const defaultTarget = reference.total || Math.max(reference.processed, reference.stagedChapters, 200);
      const currentFile = escapeHtml((reference.source_name || "sample_novel.txt").replace(/^[0-9a-f]{16}_/i, ""));
      const selectedFile = wizardState.referenceFile;
      return `
        <div class="reference-source reference-existing" id="reference-source">
          <div class="reference-current-file">
            <span>已上传</span>
            <strong>${currentFile}</strong>
            <small>已拆解 ${coverage}</small>
          </div>
          <label class="reference-file-picker" id="reference-file-picker" for="reference-file-input">
            <span id="reference-file-label">${selectedFile ? "已选择新版整本小说" : "选择更新后的整本小说"}</span>
            <input id="reference-file-input" type="file" accept=".txt,text/plain" />
            <small id="reference-file-help">${selectedFile ? "系统会匹配已拆章节，只拆解新增部分。" : "系统会自动跳过已拆章节，并重新检查末尾故事片段。"}</small>
          </label>
          <p id="reference-file-status" class="reference-file-status">${selectedFile ? `新文件：${escapeHtml(selectedFile.name)}（${Math.ceil(selectedFile.size / 1024).toLocaleString()} KB）` : (reference.isComplete ? "尚未选择新文件" : "无需重新上传，可直接重试尚未完成的拆解步骤")}</p>
          ${referenceScopeControls(defaultTarget, reference.isComplete && !selectedFile)}
        </div>`;
    }
    const selectedFile = wizardState.referenceFile;
    return `
    <fieldset class="reference-source" id="reference-source">
      <legend>参考小说</legend>
      <label class="reference-file-picker ${selectedFile ? "selected" : ""}" id="reference-file-picker" for="reference-file-input"><span id="reference-file-label">${selectedFile ? "已选择参考小说" : "导入小说内容"}</span><input id="reference-file-input" type="file" accept=".txt,text/plain" /><small id="reference-file-help">支持 TXT 文件。后台会检测编码，非 UTF-8 文本会自动转换后再拆解。</small></label>
      <p id="reference-file-status" class="reference-file-status">${selectedFile ? `已选择：${escapeHtml(selectedFile.name)}（${Math.ceil(selectedFile.size / 1024).toLocaleString()} KB），请设置拆解范围。` : "先选择小说文件，再设置拆解范围。"}</p>
      ${referenceScopeControls(200, !selectedFile)}
    </fieldset>`;
  }
  if (step.id === "world") return worldForm();
  if (step.id === "design") {
    return '<div id="design-chat-host"></div>';
  }
  if (step.id === "stage") {
    const conceptReady = Boolean(wizardState.summary?.story_design?.concept_ready);
    if (!conceptReady) {
      return '<fieldset class="generation-options"><legend>生成范围</legend><p class="decision-note">请先完成上一步「全书设计」，再生成舞台路线图。</p></fieldset>';
    }
    return '<div id="design-chat-host"></div>';
  }
  if (step.id === "mechanics") return mechanicsForm();
  if (step.id === "arcs") return "";
  if (step.id === "chapters") return "";
  if (step.id === "draft") return draftForm();
  return "";
}

function renderDirectionMode(mode) {
  wizardState.directionMode = mode;
  const source = $("#direction-source");
  if (!source) return;
  source.dataset.mode = mode;
  $$('[data-direction-mode]').forEach((button) => {
    const active = button.dataset.directionMode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $$('[data-direction-panel]').forEach((panel) => { panel.hidden = panel.dataset.directionPanel !== mode; });
}

function bindDirectionSource() {
  $$('[data-direction-mode]').forEach((button) => button.addEventListener("click", () => renderDirectionMode(button.dataset.directionMode)));
  const input = $("#direction-file-input");
  input?.addEventListener("change", () => {
    const file = input.files?.[0] || null;
    wizardState.directionFile = file;
    wizardState.directionFileContent = "";
    const status = $("#direction-file-status");
    const preview = $("#direction-file-preview");
    const previewBody = preview?.querySelector("pre");
    if (!file) {
      status.textContent = "尚未选择文件";
      preview.hidden = true;
      return;
    }
    status.textContent = `正在读取：${file.name}`;
    const reader = new FileReader();
    reader.onload = () => {
      wizardState.directionFileContent = String(reader.result || "");
      status.textContent = `已读取：${file.name}（${wizardState.directionFileContent.length.toLocaleString()} 字符）`;
      if (previewBody) previewBody.textContent = wizardState.directionFileContent.slice(0, 1800) || "（文件为空）";
      preview.hidden = false;
    };
    reader.onerror = () => {
      wizardState.directionFile = null;
      status.textContent = "文件读取失败，请重新选择。";
      preview.hidden = true;
      showToast("无法读取该文件。", true);
    };
    reader.readAsText(file, "utf-8");
  });
}



function bindReferenceSource() {
  const hasExisting = referenceStatus().hasExisting;
  const fileInput = $("#reference-file-input");
  fileInput?.addEventListener("change", () => {
    wizardState.referenceFile = fileInput.files?.[0] || null;
    const status = $("#reference-file-status");
    const file = wizardState.referenceFile;
    const scope = $("#reference-scope");
    const picker = $("#reference-file-picker");
    const label = $("#reference-file-label");
    const help = $("#reference-file-help");
    const action = $("#v0-step-form .primary-button");
    if (scope) {
      scope.hidden = false;
      scope.disabled = !file && referenceStatus().isComplete;
    }
    if (picker) picker.classList.toggle("selected", Boolean(file));
    if (label) label.textContent = file ? "已选择新版整本小说" : (hasExisting ? "上传作者更新后的整本小说" : "导入小说内容");
    if (help) help.textContent = file
      ? "系统会匹配已拆章节，只拆解新增部分；可重新选择文件。"
      : (hasExisting ? "上传重新下载的完整 TXT，并重新检查末尾故事片段。" : "支持 TXT 文件。后台会检测编码，非 UTF-8 文本会自动转换后再拆解。");
    if (status) status.textContent = file
      ? `已选择：${file.name}（${Math.ceil(file.size / 1024).toLocaleString()} KB），请设置本次拆解范围。`
      : (hasExisting
        ? (referenceStatus().isComplete ? "尚未选择新文件。" : "无需重新上传，可直接重试尚未完成的拆解步骤。")
        : "先选择小说文件，再设置拆解范围。");
    if (action) {
      action.disabled = !file && referenceStatus().isComplete;
      action.textContent = !file && hasExisting && !referenceStatus().isComplete
        ? "重试未完成步骤"
        : "导入并开始拆解";
    }
    const maxInput = $("#reference-max-chapters");
    if (maxInput) maxInput.disabled = !file || wizardState.referenceScope !== "prefix";
  });
  $$('input[name="reference-scope"]').forEach((input) => input.addEventListener("change", () => {
    if (!input.checked) return;
    wizardState.referenceScope = input.value;
    const maxInput = $("#reference-max-chapters");
    maxInput.disabled = input.value !== "prefix";
    if (input.value === "prefix") maxInput.focus();
  }));
}

function bindWorldSource() {
  const input = $("#world-file-input");
  input?.addEventListener("change", () => {
    const files = [...(input.files || [])];
    const status = $("#world-file-status");
    const picker = $("#world-file-picker");
    const label = $("#world-file-label");
    const list = $("#world-new-file-list");
    if (picker) picker.classList.toggle("selected", files.length > 0);
    if (label) label.textContent = files.length ? `已选择 ${files.length} 份新资料` : (worldSources().length ? "继续添加资料" : "选择资料文件");
    if (status) status.textContent = files.length ? "本次新增" : "尚未选择新文件";
    if (list) {
      list.replaceChildren();
      files.forEach((file) => {
        const item = document.createElement("li");
        const name = document.createElement("strong");
        const size = document.createElement("span");
        name.textContent = file.name;
        size.textContent = `${Math.ceil(file.size / 1024).toLocaleString()} KB`;
        item.append(name, size);
        list.appendChild(item);
      });
      list.hidden = !files.length;
    }
  });
  $("#world-enabled")?.addEventListener("change", async (event) => {
    const enabled = Boolean(event.target.checked);
    const toggle = $("#world-enabled");
    if (toggle) toggle.disabled = true;
    try {
      await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/world-knowledge/enabled`, {
        method: "POST", body: JSON.stringify({ enabled }),
      });
      await refreshWorkspaceArtifacts();
      showToast(enabled ? "已启用目标世界资料库。" : "已关闭目标世界资料库，后续设计不再注入资料。");
    } catch (error) {
      showToast(error.message || "切换失败。", true);
      await refreshWorkspaceArtifacts();
    } finally {
      if (toggle) toggle.disabled = false;
    }
  });
}

function renderMechanicsMode(mode) {
  wizardState.mechanicsMode = mode;
  $$('input[name="mechanics-mode"]').forEach((input) => {
    const active = input.value === mode;
    input.checked = active;
    input.closest(".direction-source-option")?.classList.toggle("active", active);
  });
  $$('[data-mechanics-panel]').forEach((panel) => { panel.hidden = panel.dataset.mechanicsPanel !== mode; });
}

function bindMechanicsSource() {
  $$('input[name="mechanics-mode"]').forEach((input) => input.addEventListener("change", () => {
    if (input.checked) renderMechanicsMode(input.value);
  }));
  const fileInput = $("#mechanics-file-input");
  fileInput?.addEventListener("change", () => {
    wizardState.mechanicsFile = fileInput.files?.[0] || null;
    const status = $("#mechanics-file-status");
    if (status) status.textContent = wizardState.mechanicsFile ? `已选择：${wizardState.mechanicsFile.name}` : "尚未选择文件";
  });
}

async function uploadFile(file) {
  const body = new FormData();
  body.append("file", file);
  return api("/api/uploads", { method: "POST", body });
}

async function activateTask(task, message) {
  wizardState.activeTaskId = task.id;
  wizardState.logOffset = 0;
  const log = $("#drawer-log");
  if (log) log.textContent = "";
  $("#drawer-prompts").innerHTML = '<p class="drawer-prompt-empty">等待模型调用…</p>';
  $("#drawer-prompt-count").textContent = "0";
  setTaskView("log");
  $("#task-drawer").classList.add("open");
  $("#drawer-scrim").classList.add("open");
  await refreshTasks();
  if (message) showToast(message);
  return task;
}

async function startTask(type, args, message) {
  if (!wizardState.workspace) throw new Error("请先创建或选择工作区。");
  const task = await api("/api/tasks", {
    method: "POST",
    body: JSON.stringify({ type, workspace: wizardState.workspace, args }),
  });
  return activateTask(task, message);
}

async function submitWorldStep() {
  const files = [...($("#world-file-input")?.files || [])];
  if (files.length) {
    const uploads = await Promise.all(files.map(uploadFile));
    await startTask("world_import", { upload_ids: uploads.map((upload) => upload.id) }, "已开始导入并构建目标世界资料库（以最大文件为主资料）。");
    return;
  }
  const sources = worldSources();
  if (!sources.length) throw new Error("请先选择至少一份目标世界资料。");
  await startTask("world_build", { force: true }, "已开始构建目标世界资料库，可在任务日志中查看进度。");
}

async function submitMechanicsStep() {
  const mode = $('input[name="mechanics-mode"]:checked')?.value || "auto";
  const args = { force: Boolean($("#mechanics-force")?.checked) };
  if (mode === "none") args.disable = true;
  if (mode === "text") {
    const direction = $("#mechanics-direction")?.value.trim() || "";
    if (!direction) throw new Error("请填写系统面板设定，或改为自动判断。");
    args.direction = direction;
  }
  if (mode === "file") {
    if (!wizardState.mechanicsFile) throw new Error("请先选择系统面板设定文件。");
    args.mechanics_upload_id = (await uploadFile(wizardState.mechanicsFile)).id;
  }
  await startTask("mechanics_init", args, "已开始初始化系统面板。");
}

function selectedVolume(id) {
  const value = Number($(id)?.value || 0);
  if (!Number.isInteger(value) || value < 1) throw new Error("请选择有效的舞台 / 卷号。");
  return value;
}

async function submitArcsStep() {
  // 故事情节单元已由统一对话框驱动，保留空实现以兼容表单提交路由。
}

async function submitChaptersStep() {
  // 逐章章纲已由统一对话框驱动，保留空实现以兼容表单提交路由。
}

async function submitDraftStep() {
  const volume = selectedVolume("#draft-volume");
  const selectedArc = $("#draft-arc")?.selectedOptions?.[0];
  const arcIdx = Number(selectedArc?.value || 0);
  const start = Number(selectedArc?.dataset.start || 0);
  const end = Number(selectedArc?.dataset.end || 0);
  if (!arcIdx || !start || end < start) throw new Error("请先选择一个已经生成的故事情节。");
  const max = Number($("#draft-max")?.value || 0);
  const arcChapterCount = end - start + 1;
  if (!Number.isInteger(max) || max < 1 || max > arcChapterCount) {
    throw new Error(`本次章节数应为 1-${arcChapterCount} 章。`);
  }
  const humanizeExisting = Boolean($("#draft-humanize-existing")?.checked);
  await startTask("write", {
    volume,
    start,
    max,
    no_humanize: !Boolean($("#draft-humanize")?.checked),
    humanize_existing: humanizeExisting,
  }, humanizeExisting
    ? `已开始精修第 ${volume} 舞台情节单元${arcIdx}范围内的已有正文。`
    : `已开始生成第 ${volume} 舞台情节单元${arcIdx}的正文（第 ${start} 章起，共 ${max} 章）。`);
}



async function refreshNameSynopsis() {
  await startTask("novel_name_synopsis", { force: true }, "已开始重新生成书名建议与简介。");
}

async function _gatherDirectionArgs() {
  const args = {};
  if (wizardState.directionMode === "file") {
    if (!wizardState.directionFile || !wizardState.directionFileContent) throw new Error("请先选择并读取创作方向文件。");
    const upload = await uploadFile(wizardState.directionFile);
    args.direction_upload_id = upload.id;
  } else {
    const direction = $("#direction-input")?.value.trim() || "";
    if (!direction) throw new Error("请填写创作方向，或切换为读取文件。");
    args.direction = direction;
  }
  return args;
}

async function submitDesignStep() {
  // 全书设计已由统一对话框驱动，保留空实现以兼容表单提交路由。
}

async function submitStageStep() {
  // 舞台设计已由统一对话框驱动，保留空实现以兼容表单提交路由。
}
async function submitReferenceStep() {
  if (!wizardState.workspace) throw new Error("请先选择工作区。");
  const reference = referenceStatus();
  if (reference.isComplete && !wizardState.referenceFile) return;
  const scope = $('input[name="reference-scope"]:checked')?.value || "all";
  const args = {};
  if (scope === "prefix") {
    const maxChapters = Number($("#reference-max-chapters")?.value);
    if (!Number.isInteger(maxChapters) || maxChapters < 1) throw new Error("请输入有效的拆解章节数。");
    if (reference.hasExisting && maxChapters < reference.processed) throw new Error(`当前已拆解至第 ${reference.processed} 章，目标章节数不能更小。`);
    args.max_chapters = maxChapters;
  }
  let taskType = "reference_resume";
  if (!reference.hasExisting) {
    if (!wizardState.referenceFile) throw new Error("请选择需要拆解的参考小说 TXT 文件。");
    args.reference_upload_id = (await uploadFile(wizardState.referenceFile)).id;
    taskType = "init";
  } else if (wizardState.referenceFile) {
    args.reference_upload_id = (await uploadFile(wizardState.referenceFile)).id;
  }
  await startTask(taskType, args, reference.hasExisting ? "已开始继续拆解参考小说，可在任务日志中查看进度。" : "已开始导入并拆解参考小说，可在任务日志中查看编码识别与进度。");
  wizardState.referenceFile = null;
}

function displayVolume(path) {
  const matched = path.match(/vol_(\d+)/i);
  return matched ? `卷 ${Number(matched[1])}` : "当前文件";
}

function chapterNumberFromPath(path) {
  const filename = path.split("/").pop() || "";
  const matched = filename.match(/^chapter_0*(\d+)/i)
    || filename.match(/^0*(\d+)(?:[_\-.]|$)/)
    || filename.match(/第\s*(\d+)\s*章/);
  return matched ? Number(matched[1]) : null;
}

function chapterFinalizationTarget(path) {
  const chapter = chapterNumberFromPath(path);
  const volumeMatch = path.match(/\/vol_(\d+)\//i);
  if (chapter === null || !volumeMatch || !path.includes("/chapters/")) return null;
  return { kind: "drafts", volume: Number(volumeMatch[1]), chapter };
}

function chapterFinalizationRecord(path) {
  const chapter = chapterNumberFromPath(path);
  const volumeMatch = path.match(/\/vol_(\d+)\//i);
  if (chapter === null || !volumeMatch) return null;
  const volumeKey = `vol_${String(Number(volumeMatch[1])).padStart(2, "0")}`;
  return wizardState.summary?.finalized_chapters?.drafts?.[volumeKey]?.[String(chapter)] || null;
}

function artifactDescriptor(step, path) {
  const filename = path.split("/").pop();
  const arcMatch = filename.match(/^arc_(\d+)_ch(\d+)_(\d+)/i);
  const chapterNumber = chapterNumberFromPath(path);
  const worldDescriptions = {
    "世界观.md": ["世界观", "天地规则、时代背景与核心矛盾。"],
    "力量体系.md": ["力量体系", "境界、力量来源与晋升限制。"],
    "关键人物.md": ["关键人物", "角色身份、关系、能力与作用。"],
    "势力描述.md": ["势力描述", "组织、利益关系与冲突格局。"],
    "故事主线.md": ["故事主线", "主资料优先的事件因果链。"],
    "关键物品.md": ["关键物品", "法宝、资源和剧情作用。"],
    "技能体系.md": ["技能体系", "法术、神通、功法与使用规则。"],
  };
  const designDescriptions = {
    "core_gameplay.md": ["核心玩法", "读者持续追读的升级与反馈循环。"],
    "worldview.md": ["世界观", "新小说的底层规则、力量体系与地图层级。"],
    "rough_outline.md": ["粗略大纲", "核心故事、玩法循环、主要角色与运营风险。"],
    "stage_outline.md": ["阶段粗纲", "独立记录全书各阶段的目标、变化与衔接。"],
    "long_mainline.md": ["长线主线", "贯穿多个舞台的期待与悬念。"],
    "stage_roadmap.md": ["舞台路线图", "每个舞台的目标、资源和阶段推进。"],
    "character_arcs.md": ["角色成长线", "主要角色的关键节点与关系变化。"],
    "design_state.json": ["设计进度", "记录全书设计已吸收的参考拆解范围。"],
    "novel_name_synopsis.md": ["书名建议", "基于创作骨架生成的书名方向与简介。"],
  };
  const mechanicsDescriptions = {
    "profile.json": ["系统面板档案", "系统面板是否启用及其工作模式。"],
    "design.md": ["机制设计", "系统或状态追踪的整体说明。"],
    "rules.json": ["系统面板规则", "可计算事件和不可突破的约束。"],
    "state.json": ["初始状态", "资源、技能、任务等初始数据。"],
  };

  if (step.id === "reference") {
    if (filename === "novel_outline.md") return { label: "全书大纲", description: "参考小说的整体故事结构与节奏。" };
    if (filename === "volume_outline.md") return { label: "本卷卷纲", description: "本卷的目标、冲突与阶段转折。" };
    if (arcMatch) return { label: `故事片段 ${Number(arcMatch[1])}`, description: `参考第 ${Number(arcMatch[2])}-${Number(arcMatch[3])} 章的叙事结构。` };
  }
  if (step.id === "world" && worldDescriptions[filename]) return { label: worldDescriptions[filename][0], description: worldDescriptions[filename][1] };
  if ((step.id === "design" || step.id === "stage") && designDescriptions[filename]) return { label: designDescriptions[filename][0], description: designDescriptions[filename][1] };
  if (step.id === "stage" && filename === "novel_name_synopsis.md") return { label: "书名与简介", description: "基于粗略大纲、世界观、长线主线与舞台路线图生成。" };
  if (step.id === "mechanics" && mechanicsDescriptions[filename]) return { label: mechanicsDescriptions[filename][0], description: mechanicsDescriptions[filename][1] };
  if (step.id === "arcs" && arcMatch) return { label: `故事情节单元 ${Number(arcMatch[1])}`, description: `覆盖新书第 ${Number(arcMatch[2])}-${Number(arcMatch[3])} 章。` };
  if (step.id === "chapters" && chapterNumber !== null && path.includes("/system_panels/")) return { label: `第 ${chapterNumber} 章系统面板`, description: "本章结束时以主角为核心的结构化状态快照。" };
  if (step.id === "chapters" && chapterNumber !== null) return { label: `第 ${chapterNumber} 章`, description: "本章故事线、情绪节奏与描述性简介。" };
  if (step.id === "draft" && chapterNumber !== null) return { label: `第 ${chapterNumber} 章`, description: path.includes("/drafts/") ? "精修前保留的原始正文。" : "去 AI 味精修后的正式正文。" };
  return { label: filename, description: "本步骤生成的相关文件。" };
}

function referenceVolumeInfo(directory) {
  const matched = directory.match(/^vol_(\d+)(?:_(.+))?$/i);
  const number = matched ? Number(matched[1]) : Number.MAX_SAFE_INTEGER;
  const name = matched?.[2]?.replace(/_/g, " ") || "未命名分卷";
  return { number, title: matched ? `第 ${number} 卷 · ${name}` : directory };
}

function referenceReviewGroups(scopedFiles) {
  const volumes = new Map();

  scopedFiles.forEach((item) => {
    const matched = item.path.match(/^reference\/outlines\/([^/]+)\/(?:volume_outline\.md|story_arcs\/[^/]+)$/);
    if (!matched) return;
    const [_, directory] = matched;
    if (!volumes.has(directory)) volumes.set(directory, []);
    volumes.get(directory).push(item);
  });

  const volumeGroups = [...volumes.entries()]
    .map(([directory, files]) => {
      const info = referenceVolumeInfo(directory);
      const orderedFiles = [...files].sort((left, right) => {
        const leftOutline = left.path.endsWith("/volume_outline.md");
        const rightOutline = right.path.endsWith("/volume_outline.md");
        if (leftOutline !== rightOutline) return leftOutline ? -1 : 1;
        return left.path.localeCompare(right.path, "zh-CN", { numeric: true });
      });
      const arcCount = orderedFiles.filter((file) => file.path.includes("/story_arcs/")).length;
      return {
        ...info,
        files: orderedFiles,
        description: `${orderedFiles.some((file) => file.path.endsWith("/volume_outline.md")) ? "含本卷卷纲" : "未找到卷纲"} · ${arcCount} 个故事片段`,
      };
    })
    .sort((left, right) => left.number - right.number);

  const volumeArtifacts = volumeGroups.flatMap((volume) => volume.files.map((file) => ({ path: file.path, ...artifactDescriptor({ id: "reference" }, file.path), groupTitle: volume.title })));

  const overviewFile = scopedFiles.find((item) => item.path === "reference/outlines/novel_outline.md");
  const overviewArtifacts = overviewFile
    ? [{ path: overviewFile.path, ...artifactDescriptor({ id: "reference" }, overviewFile.path), groupTitle: "全书大纲" }]
    : [];

  return [
    ...(overviewArtifacts.length ? [{ kind: "reference-overview", title: "全书大纲", description: "参考小说的整体故事结构与节奏，由各卷结构汇总而来。", artifacts: overviewArtifacts }] : []),
    { kind: "reference-volumes", title: "分卷拆解", description: `按卷查看卷纲与故事片段，共 ${volumeGroups.length} 卷。`, volumes: volumeGroups.map((volume) => ({ ...volume, artifacts: volume.files.map((file) => ({ path: file.path, ...artifactDescriptor({ id: "reference" }, file.path), groupTitle: volume.title })) })), artifacts: volumeArtifacts },
  ].filter((group) => (group.artifacts || []).length);
}

function storyArcVolumeInfo(directory) {
  const matched = directory.match(/^vol_(\d+)$/i);
  const number = matched ? Number(matched[1]) : Number.MAX_SAFE_INTEGER;
  return { number, title: matched ? `第 ${number} 卷` : directory };
}

function storyArcsReviewGroups(scopedFiles) {
  const volumes = new Map();
  scopedFiles.forEach((item) => {
    const matched = item.path.match(/^file_system\/story_arcs\/(vol_\d+)\/(arc_\d+_ch\d+_\d+\.md)$/i);
    if (!matched) return;
    const [_, directory] = matched;
    if (!volumes.has(directory)) volumes.set(directory, []);
    volumes.get(directory).push(item);
  });

  const volumeGroups = [...volumes.entries()]
    .map(([directory, files]) => {
      const info = storyArcVolumeInfo(directory);
      const orderedFiles = [...files].sort((left, right) => left.path.localeCompare(right.path, "zh-CN", { numeric: true }));
      return { ...info, files: orderedFiles, description: `已生成 ${orderedFiles.length} 个故事情节单元` };
    })
    .sort((left, right) => left.number - right.number);

  const artifacts = volumeGroups.flatMap((volume) => volume.files.map((file) => ({ path: file.path, ...artifactDescriptor({ id: "arcs" }, file.path), groupTitle: volume.title })));
  return artifacts.length ? [{
    kind: "story-arc-volumes",
    title: "已生成故事情节",
    description: `按卷汇总已生成内容，共 ${volumeGroups.length} 卷。`,
    volumes: volumeGroups.map((volume) => ({ ...volume, artifacts: volume.files.map((file) => ({ path: file.path, ...artifactDescriptor({ id: "arcs" }, file.path), groupTitle: volume.title })) })),
    artifacts,
  }] : [];
}

function chapterArcReviewGroups(step, scopedFiles) {
  function buildGroup(files, title, contentKind) {
    const volumeNumbers = new Set();
    files.forEach((item) => {
      const matched = item.path.match(/\/vol_(\d+)\//i);
      if (matched) volumeNumbers.add(Number(matched[1]));
    });
    const volumes = [...volumeNumbers].sort((a, b) => a - b).map((volumeNumber) => {
      const volumeInfo = (wizardState.summary?.volumes || []).find((item) => Number(item.volume) === volumeNumber);
      const knownArcs = [...(volumeInfo?.arcs || [])].sort((a, b) => Number(a.idx) - Number(b.idx));
      const volumeFiles = files.filter((item) => Number(item.path.match(/\/vol_(\d+)\//i)?.[1]) === volumeNumber);
      const buckets = knownArcs.map((arc) => ({
        idx: Number(arc.idx), start_ch: Number(arc.start_ch), end_ch: Number(arc.end_ch),
        name: String(arc.title || "").trim(), files: [],
      }));
      const unmatched = [];
      volumeFiles.forEach((file) => {
        const chapter = chapterNumberFromPath(file.path);
        const bucket = buckets.find((arc) => chapter !== null && chapter >= arc.start_ch && chapter <= arc.end_ch);
        (bucket ? bucket.files : unmatched).push(file);
      });
      if (unmatched.length) buckets.push({ idx: null, start_ch: null, end_ch: null, name: "", files: unmatched });
      const arcs = buckets.filter((arc) => arc.files.length).map((arc) => {
        const orderedFiles = [...arc.files].sort((left, right) => left.path.localeCompare(right.path, "zh-CN", { numeric: true }));
        const arcTitle = arc.idx === null ? "未归属故事片段" : `故事片段 ${arc.idx}${arc.name ? ` · ${arc.name}` : ""}`;
        const groupTitle = `第 ${volumeNumber} 卷 · ${arcTitle}`;
        return {
          ...arc,
          title: arcTitle,
          description: arc.idx === null ? `${orderedFiles.length} 份章节内容` : `第 ${arc.start_ch}-${arc.end_ch} 章 · ${orderedFiles.length} 份内容`,
          artifacts: orderedFiles.map((file) => ({ path: file.path, ...artifactDescriptor(step, file.path), groupTitle })),
        };
      });
      return { number: volumeNumber, title: `第 ${volumeNumber} 卷`, description: `${arcs.length} 个故事片段`, arcs };
    }).filter((volume) => volume.arcs.length);
    const artifacts = volumes.flatMap((volume) => volume.arcs.flatMap((arc) => arc.artifacts));
    return artifacts.length ? {
      kind: "chapter-arc-volumes", contentKind, title,
      description: `按卷和故事片段查看，共 ${volumes.length} 卷。`,
      volumes, artifacts,
    } : null;
  }

  if (step.id === "chapters") {
    return [
      buildGroup(scopedFiles.filter((file) => file.path.includes("/chapter_outlines/")), "逐章章纲", "outlines"),
      buildGroup(scopedFiles.filter((file) => file.path.includes("/system_panels/")), "系统面板", "panels"),
    ].filter(Boolean);
  }
  const drafts = buildGroup(scopedFiles, "已生成正文", "drafts");
  return drafts ? [drafts] : [];
}

function isHiddenSupportFile(path) {
  return path.includes("/versions/")
    || path.includes("/conversation")
    || path.endsWith("conversation.json")
    || /\conversation_arc_\d+\.json$/.test(path)
    || path.endsWith("conversation/concept.json")
    || path.endsWith("conversation/stage.json")
    || /_compact\.md$/.test(path)
    || path.endsWith("design_state.json")
    || path.endsWith("arc_usage_state.json")
    || path.endsWith("direction_history.json")
    || path.endsWith("finalized_chapters.json")
    || path.endsWith("manifest.json")
    || path.endsWith("arcs_index.json")
    || path.endsWith("chapter_cards_index.json");
}

function reviewGroupsFor(step) {
  const scopedFiles = wizardState.fileTree.filter((item) => item.type === "file" && step.reviewPrefixes.some((prefix) => item.path.startsWith(prefix)) && !isHiddenSupportFile(item.path));
  if (step.id === "reference") return referenceReviewGroups(scopedFiles);
  if (step.id === "arcs") return storyArcsReviewGroups(scopedFiles);
  if (step.id === "chapters" || step.id === "draft") return chapterArcReviewGroups(step, scopedFiles);
  const groups = (REVIEW_GROUPS[step.id] || []).map((group) => ({ ...group, files: scopedFiles.filter((item) => group.matches(item.path)) }));
  const matched = new Set(groups.flatMap((group) => group.files.map((file) => file.path)));
  const remaining = scopedFiles.filter((file) => !matched.has(file.path));
  if (remaining.length) groups.push({ title: "其他相关文件", description: "本步骤生成的辅助资料。", files: remaining });
  return groups.filter((group) => group.files.length).map((group) => ({
    ...group,
    artifacts: group.files.map((file) => ({ path: file.path, ...artifactDescriptor(step, file.path), groupTitle: group.title })),
  }));
}

function artifactButton(artifact, activePath) {
  const chapterNumber = chapterNumberFromPath(artifact.path);
  const compactChapter = chapterNumber !== null && (
    artifact.path.includes("/chapter_outlines/")
    || artifact.path.includes("/system_panels/")
    || artifact.path.includes("/chapters/")
  );
  if (compactChapter) {
    const record = chapterFinalizationRecord(artifact.path);
    const isDraft = artifact.path.includes("/chapters/");
    const synchronized = record?.status === "synced";
    const badge = record
      ? (isDraft
        ? (synchronized ? "✓ 最终版" : "最终版 · 待同步")
        : (synchronized ? "✓ 正文已同步" : "正文待同步"))
      : "";
    return `<button class="artifact-item artifact-chapter-row ${artifact.path === activePath ? "active" : ""} ${record ? "is-finalized" : ""}" data-review-path="${escapeHtml(artifact.path)}" type="button"><span>第 ${chapterNumber} 章</span>${badge ? `<small>${escapeHtml(badge)}</small>` : ""}</button>`;
  }
  return `<button class="artifact-item ${artifact.path === activePath ? "active" : ""}" data-review-path="${escapeHtml(artifact.path)}" type="button"><span class="artifact-file-icon" aria-hidden="true"></span><span class="artifact-item-copy"><span class="artifact-item-type">生成内容</span><span class="artifact-item-label">${escapeHtml(artifact.label)}</span><span class="artifact-item-description">${escapeHtml(artifact.description)}</span><span class="artifact-item-filename">${escapeHtml(artifact.path.split("/").pop())}</span></span></button>`;
}

function reviewOutlineMarkup(step, groups, artifacts) {
  const activePath = artifacts[0]?.path;
  if (step.id === "reference") {
    const overview = groups.find((group) => group.kind === "reference-overview");
    const volumes = groups.find((group) => group.kind === "reference-volumes");
    return `<aside class="artifact-outline reference-outline" id="artifact-outline">
      ${overview ? `<section class="artifact-group"><div class="artifact-group-heading"><span class="artifact-group-kicker">全书结构 · 1 份资料</span><h3>${escapeHtml(overview.title)}</h3><p>${escapeHtml(overview.description)}</p></div><div class="artifact-list">${overview.artifacts.map((artifact) => artifactButton(artifact, activePath)).join("")}</div></section>` : ""}
      ${volumes ? `<section class="reference-section reference-volume-section"><header class="reference-section-heading"><span>分卷拆解</span><p>${escapeHtml(volumes.description)}</p></header><div class="volume-accordion">${volumes.volumes.map((volume, index) => `<details class="volume-node" ${index === 0 ? "open" : ""}><summary><span class="volume-node-marker" aria-hidden="true"></span><span class="volume-node-copy"><strong>${escapeHtml(volume.title)}</strong><small>${escapeHtml(volume.description)}</small></span></summary><div class="volume-node-files">${volume.artifacts.map((artifact) => artifactButton(artifact, activePath)).join("")}</div></details>`).join("")}</div></section>` : ""}
    </aside>`;
  }
  if (step.id === "arcs") {
    const volumes = groups.find((group) => group.kind === "story-arc-volumes");
    return `<aside class="artifact-outline story-arcs-outline" id="artifact-outline">
      ${volumes ? `<section class="reference-section reference-volume-section"><header class="reference-section-heading"><span>已生成故事情节</span><p>${escapeHtml(volumes.description)}</p></header><div class="volume-accordion">${volumes.volumes.map((volume) => `<details class="volume-node" open><summary><span class="volume-node-marker" aria-hidden="true"></span><span class="volume-node-copy"><strong>${escapeHtml(volume.title)}</strong><small>${escapeHtml(volume.description)}</small></span></summary><div class="volume-node-files">${volume.artifacts.map((artifact) => artifactButton(artifact, activePath)).join("")}</div></details>`).join("")}</div></section>` : ""}
    </aside>`;
  }
  if (step.id === "chapters" || step.id === "draft") {
    return `<aside class="artifact-outline chapter-arc-outline" id="artifact-outline">
      ${groups.filter((group) => group.kind === "chapter-arc-volumes").map((content, groupIndex) => `<section class="reference-section reference-volume-section"><header class="reference-section-heading"><span>${escapeHtml(content.title)}</span><p>${escapeHtml(content.description)}</p></header><div class="volume-accordion">${content.volumes.map((volume, volumeIndex) => `<details class="volume-node" ${groupIndex === 0 && volumeIndex === 0 ? "open" : ""}><summary><span class="volume-node-marker" aria-hidden="true"></span><span class="volume-node-copy"><strong>${escapeHtml(volume.title)}</strong><small>${escapeHtml(volume.description)}</small></span></summary><div class="arc-node-list">${volume.arcs.map((arc, arcIndex) => `<details class="arc-node" ${groupIndex === 0 && volumeIndex === 0 && arcIndex === 0 ? "open" : ""}><summary><span class="arc-node-marker" aria-hidden="true"></span><span class="volume-node-copy"><strong>${escapeHtml(arc.title)}</strong><small>${escapeHtml(arc.description)}</small></span></summary><div class="arc-node-files">${arc.artifacts.map((artifact) => artifactButton(artifact, activePath)).join("")}</div></details>`).join("")}</div></details>`).join("")}</div></section>`).join("")}
    </aside>`;
  }
  return `<aside class="artifact-outline" id="artifact-outline">${groups.map((group) => `<section class="artifact-group"><div class="artifact-group-heading"><span class="artifact-group-kicker">内容分类 · ${group.artifacts.length} 份资料</span><h3>${escapeHtml(group.title)}</h3><p>${escapeHtml(group.description)}</p></div><div class="artifact-list">${group.artifacts.map((artifact) => artifactButton(artifact, activePath)).join("")}</div></section>`).join("")}</aside>`;
}

function renderActiveStep() {
  const step = WIZARD_STEPS.find((item) => item.id === wizardState.activeStep) || WIZARD_STEPS[0];
  const status = statusForStep(step);
  const groups = reviewGroupsFor(step);
  const artifacts = groups.flatMap((group) => group.artifacts);
  wizardState.reviewArtifacts = artifacts;
  const isDone = status === "done";
  const reference = step.id === "reference" ? referenceStatus() : null;
  const referenceActionDisabled = Boolean(
    reference && (
      (reference.isComplete && !wizardState.referenceFile)
      || (!reference.hasExisting && !wizardState.referenceFile)
    ),
  );
  const design = (step.id === "design" || step.id === "stage") ? designStatus() : null;
  const hidePrimaryAction = step.id === "design" || step.id === "arcs" || step.id === "chapters" || (step.id === "stage" && !Boolean(wizardState.summary?.story_design?.stage_ready));
  const actionLabel = step.id === "reference"
    ? (reference?.hasExisting && !reference?.isComplete && !wizardState.referenceFile
      ? "重试未完成步骤"
      : "导入并开始拆解")
    : step.id === "design"
      ? (design?.concept_ready ? "重新生成粗略大纲与世界观" : "生成粗略大纲与世界观")
      : step.id === "stage"
        ? (design?.stage_ready ? "续写后续舞台" : "生成长线主线与舞台路线图")
      : step.id === "world"
        ? "导入并开始构建"
        : step.id === "mechanics"
          ? "初始化系统面板"
          : step.id === "arcs"
            ? "生成故事情节单元"
            : step.id === "chapters"
              ? "生成逐章章纲"
              : step.id === "draft"
                ? "开始生成正文"
                : "开始生成";
  const heading = step.heading;
  const lead = step.lead;
  const decision = step.decision;
  $("#step-count").textContent = `STEP ${String(stepIndex(step.id) + 1).padStart(2, "0")} / ${String(WIZARD_STEPS.length).padStart(2, "0")}`;
  const chatStep = isDesignChatStep(step);
  $("#step-canvas").innerHTML = chatStep ? `
    <article class="step-view step-view-chat">
      <header class="chat-step-header">
        <div>
          <p class="step-eyebrow">${step.optional ? "可选步骤" : "创作流程"}</p>
          <h1 class="step-title">${heading}</h1>
          <p class="step-lead">${lead}</p>
        </div>
      </header>
      <section class="chat-band" id="chat-band">
        <div id="${step.id === "arcs" ? "arcs-chat-host" : step.id === "chapters" ? "chapters-chat-host" : step.id === "draft" ? "draft-chat-host" : "design-chat-host"}"></div>
      </section>
      <section class="review-band">
        <div class="band-heading"><h2>生成内容</h2><p>${step.reviewHint}</p></div>
        <div class="review-empty" id="review-empty" ${artifacts.length ? "hidden" : ""}>生成后在右侧查看，或点击对话中的文件链接。</div>
        <div id="review-layout" class="review-layout" ${artifacts.length ? "" : "hidden"}>
          ${reviewOutlineMarkup(step, groups, artifacts)}
          <section class="review-preview"><div id="review-document" class="review-document"></div></section>
        </div>
        <div class="review-actions">
          <button class="primary-button" id="confirm-step" type="button" ${artifacts.length ? "" : "disabled"}>继续</button>
        </div>
      </section>
    </article>` : `
    <article class="step-view">
      <p class="step-eyebrow">${step.optional ? "可选步骤" : "创作流程"}</p>
      <div class="step-status ${status}">${isDone ? "已有生成内容，可随时返回调整" : status === "locked" ? "等待前序步骤" : step.optional ? "可选择执行或跳过" : "等待生成内容"}</div>
      <h1 class="step-title">${heading}</h1>
      <p class="step-lead">${lead}</p>
      <section class="decision-band">
        <div class="band-heading"><h2>本步决定</h2><p>${step.short}</p></div>
        <div class="decision-layout">
          <form class="decision-form" id="v0-step-form">
            ${formForStep(step)}
            ${hidePrimaryAction ? "" : `<div class="decision-actions">
              <button class="primary-button" type="submit" ${referenceActionDisabled ? "disabled" : ""}>${actionLabel}</button>
              ${step.optional ? '<button class="text-button" id="skip-step" type="button">本书跳过此步</button>' : ""}
            </div>`}
          </form>
          <aside class="context-note"><strong>设计说明</strong>${decision}</aside>
        </div>
      </section>
      <section class="review-band">
        <div class="band-heading"><h2>生成内容</h2><p>${step.reviewHint}</p></div>
        <div class="review-empty" id="review-empty" ${artifacts.length ? "hidden" : ""}>本步骤尚未发现产物。运行生成后，会按用途归类显示在这里。</div>
        <div id="review-layout" class="review-layout" ${artifacts.length ? "" : "hidden"}>
          ${reviewOutlineMarkup(step, groups, artifacts)}
          <section class="review-preview"><div id="review-document" class="review-document"></div></section>
        </div>
        <div class="review-actions">
          <button class="primary-button" id="confirm-step" type="button" ${artifacts.length ? "" : "disabled"}>继续</button>
        </div>
      </section>
    </article>`;
  $("#v0-step-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = event.submitter;
    if (submit) submit.disabled = true;
    try {
      if (step.id === "reference") await submitReferenceStep();
      else if (step.id === "world") await submitWorldStep();
      else if (step.id === "design") await submitDesignStep();
      else if (step.id === "stage") await submitStageStep();
      else if (step.id === "mechanics") await submitMechanicsStep();
      else if (step.id === "arcs") await submitArcsStep();
      else if (step.id === "chapters") await submitChaptersStep();
      else if (step.id === "draft") await submitDraftStep();
    } catch (error) {
      showToast(error.message || "无法启动生成任务。", true);
    } finally {
      if (submit) submit.disabled = false;
    }
  });
  if (step.id === "reference") bindReferenceSource();
  if (step.id === "world") bindWorldSource();
  if (step.id === "design") {
    loadDesignChat("concept");
  }
  if (step.id === "stage") {
    loadDesignChat("stage");
  }
  if (step.id === "arcs") {
    wizardState.arcsChatVolume = wizardState.arcsChatVolume || 1;
    loadArcsChat(wizardState.arcsChatVolume);
  }
  if (step.id === "chapters") {
    const volumes = wizardState.summary?.volumes || [];
    wizardState.chaptersChatVolume = wizardState.chaptersChatVolume || (volumes[0]?.volume || 1);
    if (!wizardState.chaptersChatArc) {
      const vol = volumes.find((v) => v.volume === wizardState.chaptersChatVolume);
      wizardState.chaptersChatArc = vol?.arcs?.[0]?.idx || null;
    }
    loadChaptersChat(wizardState.chaptersChatVolume, wizardState.chaptersChatArc);
  }
  if (step.id === "draft") {
    const volumes = wizardState.summary?.volumes || [];
    wizardState.draftChatVolume = wizardState.draftChatVolume || (volumes[0]?.volume || 1);
    if (!wizardState.draftChatArc) {
      const volume = volumes.find((item) => Number(item.volume) === Number(wizardState.draftChatVolume));
      wizardState.draftChatArc = volume?.arcs?.[0]?.idx || null;
    }
    loadDraftChat(wizardState.draftChatVolume, wizardState.draftChatArc);
  }
  if (step.id === "mechanics") bindMechanicsSource();
  if (step.id === "draft") bindDraftRange();
  $("#skip-step")?.addEventListener("click", () => confirmStep(step, true));
  $("#confirm-step").addEventListener("click", () => confirmStep(step, false));
  $$('[data-review-path]').forEach((button) => button.addEventListener("click", () => openReviewFile(button.dataset.reviewPath)));
  const selectedArtifact = artifacts.find((artifact) => artifact.path === wizardState.selectedFile) || artifacts[0];
  if (selectedArtifact) openReviewFile(selectedArtifact.path);
}

function confirmStep(step, skipped) {
  wizardState.confirmed.add(step.id);
  const next = WIZARD_STEPS[stepIndex(step.id) + 1];
  wizardState.activeStep = next?.id || step.id;
  renderRail();
  renderActiveStep();
  showToast(skipped ? "已跳过此可选步骤。" : "已进入下一步，当前内容仍可随时返回调整。");
}

function isReferenceAsset(path) {
  return path.startsWith("reference/");
}

function isReferenceStoryArc(path) {
  return /^reference\/outlines\/[^/]+\/story_arcs\/arc_\d+_ch\d+_\d+\.md$/i.test(path);
}

const CARD_SECTION_LABELS = [
  ["chapter_outline_600", "单章简介"],
  ["story_line", "故事线"],
];
const CARD_RHYTHM_LABELS = [
  ["core_content", "核心内容"],
  ["emotion_tone", "情绪基调"],
  ["beat_detail", "节奏拆解"],
];
const CARD_ENTITY_LABELS = [
  ["characters", "角色"],
  ["factions", "势力"],
  ["locations", "地点"],
  ["items", "物品"],
  ["skills", "技能"],
];

function renderChapterCardSections(chapter) {
  const sections = CARD_SECTION_LABELS
    .map(([key, label]) => {
      const value = (chapter[key] || "").trim();
      return value ? `<section class="card-section"><h5>${label}</h5><p>${escapeHtml(value)}</p></section>` : "";
    })
    .join("");
  const rhythm = chapter.chapter_rhythm || {};
  const rhythmSections = CARD_RHYTHM_LABELS
    .map(([key, label]) => {
      const value = (rhythm[key] || "").trim();
      return value ? `<section class="card-section"><h5>${label}</h5><p>${escapeHtml(value)}</p></section>` : "";
    })
    .join("");
  const highlights = Array.isArray(chapter.highlights) ? chapter.highlights : [];
  const highlightText = highlights.map((item) => escapeHtml(String(item || "").trim())).filter(Boolean).join("\n");
  const highlightSection = highlightText ? `<section class="card-section"><h5>亮点</h5><p>${highlightText.replace(/\n/g, "<br>")}</p></section>` : "";
  const rhythmWrap = rhythmSections ? `<section class="card-section card-section-rhythm"><h5>单章节奏</h5><div class="card-grid card-grid-inner">${rhythmSections}</div></section>` : "";
  if (!sections && !rhythmSections && !highlightText) {
    return '<p class="card-empty">该章节尚未拆解出事实卡内容。</p>';
  }
  return `<div class="card-grid">${sections}${rhythmWrap}${highlightSection}</div>`;
}

function renderReferenceArcChapters(artifact, data) {
  const documentNode = $("#review-document");
  if (!documentNode) return;
  const chapters = Array.isArray(data.chapters) ? data.chapters : [];
  let activeIndex = 0;
  const renderActiveChapter = () => {
    const chapter = chapters[activeIndex];
    const content = $("#reference-arc-chapter-content");
    if (!chapter || !content) return;
    const sourceTag = chapter.source === "raw" ? '<span class="card-source-tag">原文回退</span>' : "";
    content.innerHTML = `<header><p>第 ${chapter.number} 章</p><h4>${escapeHtml(chapter.title)}</h4>${sourceTag}</header>${renderChapterCardSections(chapter)}`;
    $$('[data-reference-chapter-index]').forEach((button) => button.classList.toggle("active", Number(button.dataset.referenceChapterIndex) === activeIndex));
  };

  documentNode.innerHTML = `<header class="preview-meta"><div><p>单章事实卡</p><h3>${escapeHtml(artifact.label)} · 覆盖章节</h3><span>选择左侧章节查看拆解后的事实卡；参考拆解资产仅供阅读，不可在工作台中编辑。</span><code>${escapeHtml(data.path)}</code></div><div class="preview-tools"><button id="back-to-reference-arc" class="secondary-button" type="button">返回故事片段</button></div></header><div class="reference-arc-browser"><nav class="reference-arc-chapter-list" aria-label="故事片段章节">${chapters.map((chapter, index) => `<button class="reference-arc-chapter ${index === 0 ? "active" : ""}" data-reference-chapter-index="${index}" type="button"><strong>第 ${chapter.number} 章</strong><span>${escapeHtml(chapter.title)}</span></button>`).join("")}</nav><article id="reference-arc-chapter-content" class="reference-arc-chapter-content"></article></div>`;
  $("#back-to-reference-arc")?.addEventListener("click", () => renderReviewDocument(artifact));
  $$('[data-reference-chapter-index]').forEach((button) => button.addEventListener("click", () => {
    activeIndex = Number(button.dataset.referenceChapterIndex);
    renderActiveChapter();
  }));
  renderActiveChapter();
}

async function openReferenceArcChapters(path, artifact) {
  try {
    const data = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/reference-arc-chapters?path=${encodeURIComponent(path)}`);
    renderReferenceArcChapters(artifact, data);
  } catch (error) {
    showToast(error.message || "无法读取该故事片段的章节原文。", true);
  }
}

function isSystemPanelSnapshot(path) {
  return path.includes("/system_panels/") && path.toLowerCase().endsWith(".json");
}

function systemPanelValueMarkup(value) {
  if (value === null || value === undefined || value === "") return '<span class="panel-empty-value">未记录</span>';
  if (Array.isArray(value)) {
    if (!value.length) return '<span class="panel-empty-value">无</span>';
    if (value.some((item) => item && typeof item === "object")) {
      return `<div class="panel-item-list">${value.map((item) => `<div>${systemPanelValueMarkup(item)}</div>`).join("")}</div>`;
    }
    return `<div class="panel-tag-list">${value.map((item) => `<span>${escapeHtml(String(item))}</span>`).join("")}</div>`;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value);
    if (!entries.length) return '<span class="panel-empty-value">无</span>';
    return `<dl class="panel-kv-list">${entries.map(([key, item]) => `<div><dt>${escapeHtml(key)}</dt><dd>${systemPanelValueMarkup(item)}</dd></div>`).join("")}</dl>`;
  }
  if (typeof value === "boolean") return `<span class="panel-boolean ${value ? "yes" : "no"}">${value ? "是" : "否"}</span>`;
  return `<span class="panel-scalar">${escapeHtml(String(value))}</span>`;
}

function systemPanelPreview(content) {
  let panel;
  try { panel = JSON.parse(content); } catch (_) { return null; }
  if (!panel || typeof panel !== "object" || Array.isArray(panel)) return null;
  const state = panel.panel && typeof panel.panel === "object"
    ? panel.panel
    : panel.protagonist_state && typeof panel.protagonist_state === "object"
      ? panel.protagonist_state
      : {};
  const labels = {
    values: "核心数值", resources: "资源", inventory: "物品数量",
    skills: "技能等级", task_progress: "任务进度",
    identity: "身份", attributes: "属性", equipment: "装备", tasks: "任务", relationships: "关系",
    injuries_and_status: "伤势与状态", flags: "关键标记",
  };
  const orderedState = {};
  Object.entries(labels).forEach(([key, label]) => {
    const value = state[key];
    const hasContent = Array.isArray(value) ? value.length : value && typeof value === "object" ? Object.keys(value).length : value !== undefined && value !== "";
    if (hasContent) orderedState[label] = value;
  });
  Object.entries(state).filter(([key]) => !labels[key]).forEach(([key, value]) => { orderedState[key] = value; });
  const stateSections = `<section class="system-panel-wide panel-current-state"><h4>当前面板</h4>${systemPanelValueMarkup(orderedState)}</section>`;
  const changes = Array.isArray(panel.changes) ? panel.changes : [];
  const changeMarkup = changes.length
    ? `<section class="system-panel-wide"><h4>本章变化</h4><div class="panel-change-list">${changes.map((item) => `<article><strong>${escapeHtml(String(item.field || [item.category, item.key].filter(Boolean).join(".") || "状态变化"))}</strong><div><span>${escapeHtml(String(item.before ?? "未记录"))}</span><b>→</b><span>${escapeHtml(String(item.after ?? "未记录"))}</span></div>${item.reason ? `<p>${escapeHtml(String(item.reason))}</p>` : ""}</article>`).join("")}</div></section>`
    : '<section class="system-panel-wide panel-no-change"><h4>本章变化</h4><p>本章没有需要记录的主角状态变化。</p></section>';
  const displays = Array.isArray(panel.panel_display) ? panel.panel_display : [];
  const notes = Array.isArray(panel.continuity_notes) ? panel.continuity_notes : [];
  const supporting = [
    displays.length ? `<section class="system-panel-wide"><h4>正文可展示面板</h4>${systemPanelValueMarkup(displays)}</section>` : "",
    notes.length ? `<section class="system-panel-wide"><h4>下一章连续性提醒</h4>${systemPanelValueMarkup(notes)}</section>` : "",
  ].join("");
  return `<div class="system-panel-overview"><div><span>章节</span><strong>第 ${Number(panel.chapter || 0)} 章</strong></div><div><span>状态变化</span><strong>${changes.length} 项</strong></div>${displays.length ? `<div><span>正文展示</span><strong>${displays.length} 项</strong></div>` : ""}</div><div class="system-panel-grid">${stateSections}${changeMarkup}${supporting}</div>`;
}

async function copyPreviewText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("浏览器未允许复制");
}

function renderReviewDocument(artifact) {
  const documentNode = $("#review-document");
  if (!documentNode || !wizardState.selectedFile) return;
  const path = wizardState.selectedFile;
  const readonlyReference = isReferenceAsset(path);
  const copyDraftButton = (
    wizardState.activeStep === "draft"
    && path.includes("/chapters/")
    && !wizardState.fileEditing
  ) ? '<button id="copy-draft-preview" class="secondary-button copy-preview-button" type="button">一键复制</button>' : "";
  const finalizationTarget = chapterFinalizationTarget(path);
  const finalizationRecord = chapterFinalizationRecord(path);
  const finalized = Boolean(finalizationRecord?.finalized);
  const finalizationButton = finalizationTarget && !wizardState.fileEditing
    ? `<button id="toggle-chapter-finalized" class="secondary-button ${finalized ? "is-finalized" : ""}" type="button">${finalized ? "取消最终版" : "标记为最终版"}</button>`
    : "";
  const controls = isReferenceStoryArc(path)
    ? '<div class="preview-tools"><button id="view-reference-arc-chapters" class="secondary-button" type="button">查看本片段章节</button></div>'
    : readonlyReference
      ? ""
      : wizardState.fileEditing
        ? '<div class="preview-tools"><button id="cancel-file-edit" class="secondary-button" type="button">取消</button><button id="save-file-edit" class="primary-button" type="button">保存修改</button></div>'
        : `<div class="preview-tools">${copyDraftButton}${finalizationButton}<button id="edit-review-file" class="secondary-button" type="button">编辑此文件</button></div>`;
  const panelPreview = !wizardState.fileEditing && isSystemPanelSnapshot(path)
    ? systemPanelPreview(wizardState.selectedFileContent)
    : null;
  const body = wizardState.fileEditing
    ? `<textarea id="review-editor" class="review-editor" spellcheck="false">${escapeHtml(wizardState.selectedFileContent)}</textarea>`
    : panelPreview || markdownPreview(wizardState.selectedFileContent);
  documentNode.innerHTML = `<header class="preview-meta"><div><p>${escapeHtml(artifact.groupTitle)}</p><h3>${escapeHtml(artifact.label)}</h3><span>${escapeHtml(artifact.description)}</span><code>${escapeHtml(path)}</code></div>${controls}</header>${body}`;
  $("#view-reference-arc-chapters")?.addEventListener("click", () => openReferenceArcChapters(path, artifact));
  $("#toggle-chapter-finalized")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const result = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/finalized-chapters`, {
        method: "POST",
        body: JSON.stringify({ ...finalizationTarget, finalized: !finalized }),
      });
      wizardState.summary.finalized_chapters = result.finalized_chapters;
      renderActiveStep();
      await openReviewFile(path);
      showToast(finalized ? "已取消最终版标记。" : "已标记为最终版，后续对话调整将跳过本章。");
    } catch (error) {
      button.disabled = false;
      showToast(error.message || "无法更新最终版标记。", true);
    }
  });
  $("#copy-draft-preview")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await copyPreviewText(wizardState.selectedFileContent);
      button.textContent = "已复制";
      showToast("正文已复制到剪贴板。");
      setTimeout(() => {
        if (button.isConnected) {
          button.textContent = "一键复制";
          button.disabled = false;
        }
      }, 1200);
    } catch (error) {
      button.disabled = false;
      showToast(error.message || "复制失败，请手动选择正文复制。", true);
    }
  });
  $("#edit-review-file")?.addEventListener("click", () => {
    wizardState.fileEditing = true;
    renderReviewDocument(artifact);
  });
  $("#cancel-file-edit")?.addEventListener("click", () => {
    wizardState.fileEditing = false;
    renderReviewDocument(artifact);
  });
  $("#save-file-edit")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const content = $("#review-editor")?.value;
    if (typeof content !== "string") return;
    button.disabled = true;
    try {
      await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/file`, {
        method: "PUT",
        body: JSON.stringify({ path, content }),
      });
      wizardState.selectedFileContent = content;
      wizardState.fileEditing = false;
      await refreshWorkspaceArtifacts();
      await openReviewFile(path);
      showToast("文件已保存。");
    } catch (error) {
      showToast(error.message || "保存文件失败。", true);
    } finally {
      button.disabled = false;
    }
  });
}

async function openReviewFile(path) {
  try {
    if (!wizardState.workspace) throw new Error("请先选择工作区。");
    const data = await api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/file?path=${encodeURIComponent(path)}`);
    const artifact = wizardState.reviewArtifacts.find((item) => item.path === path) || { label: path.split("/").pop(), description: "工作区中的可编辑文件。", groupTitle: "工作区文件" };
    wizardState.selectedFile = path;
    wizardState.selectedFileContent = data.content;
    wizardState.fileEditing = false;
    $("#review-empty").hidden = true;
    $("#review-layout").hidden = false;
    renderReviewDocument(artifact);
    $$('[data-review-path]').forEach((button) => button.classList.toggle("active", button.dataset.reviewPath === path));
  } catch (error) { showToast(error.message, true); }
}

function isPreviewableFile(path) {
  return /\.(?:md|txt|json|yaml|yml|csv|tsv)$/i.test(path);
}

function isHiddenReferenceSupportFile(path) {
  return path === "reference/sample_novel.txt"
    || path === "reference/analysis_state.json"
    || path === "reference/chapter_cards_index.json"
    || path === "reference/outlines/volume_outline.md"
    || path.startsWith("reference/chapters/")
    || path.startsWith("reference/chapter_cards/")
    || /\/meta\.json$/i.test(path)
    || /\/arcs_index\.json$/i.test(path);
}

function renderFileBrowser() {
  const query = ($("#file-search")?.value || "").trim().toLowerCase();
  const items = wizardState.fileTree.filter((item) => item.type === "file" && isPreviewableFile(item.path) && !isHiddenReferenceSupportFile(item.path) && item.path.toLowerCase().includes(query));
  $("#file-browser-list").innerHTML = items.length
    ? items.map((item) => `<button class="file-browser-item" data-open-file="${escapeHtml(item.path)}" type="button"><strong>${escapeHtml(item.path.split("/").pop())}</strong><span>${escapeHtml(item.path)}</span></button>`).join("")
    : '<p class="review-empty">未找到可预览的文本文件。</p>';
  $$('[data-open-file]').forEach((button) => button.addEventListener("click", async () => {
    closeFileBrowser();
    await openReviewFile(button.dataset.openFile);
  }));
}

function openFileBrowser() {
  if (!wizardState.workspace) {
    showToast("请先创建或选择工作区。", true);
    return;
  }
  $("#file-browser").classList.add("open");
  $("#file-scrim").classList.add("open");
  $("#file-search").value = "";
  renderFileBrowser();
}

function closeFileBrowser() {
  $("#file-browser").classList.remove("open");
  $("#file-scrim").classList.remove("open");
}

function taskLabel(task) {
  if (task.status === "running") return "运行中";
  if (task.status === "succeeded") return "完成";
  if (task.status === "succeeded_with_warnings") return "需检查";
  if (task.status === "failed") return "失败";
  return "等待";
}

function promptCardsMarkup(items, openLatest = false) {
  if (!items?.length) return '<p class="drawer-prompt-empty">该任务尚未调用大模型。</p>';
  return items.map((item, index) => {
    const call = `第 ${index + 1} 次调用${item.model ? ` · ${escapeHtml(item.model)}` : ""}`;
    const open = openLatest && index === items.length - 1 ? " open" : "";
    return `<details class="drawer-prompt-card"${open}>
      <summary><strong>${call}</strong><span>${escapeHtml(item.created_at || "")}</span></summary>
      <pre>${escapeHtml(item.prompt || "")}</pre>
    </details>`;
  }).join("");
}

function setTaskView(view) {
  wizardState.taskView = view === "prompt" ? "prompt" : "log";
  $$('[data-task-view]').forEach((button) => button.classList.toggle("active", button.dataset.taskView === wizardState.taskView));
  const promptView = wizardState.taskView === "prompt";
  $("#drawer-log").hidden = promptView;
  $("#drawer-prompts").hidden = !promptView;
  if (promptView) refreshTaskPrompts();
}

async function refreshTaskPrompts() {
  if (!wizardState.activeTaskId) return;
  try {
    const data = await api(`/api/tasks/${wizardState.activeTaskId}/prompts`);
    const items = data.items || [];
    $("#drawer-prompt-count").textContent = String(Number(data.task?.prompt_count ?? items.length));
    $("#drawer-prompts").innerHTML = promptCardsMarkup(items, true);
  } catch (_) { /* task may have been removed */ }
}

function openPromptDialog(items, meta = "模型调用") {
  const dialog = $("#prompt-dialog");
  const list = Array.isArray(items) ? items : [];
  $("#prompt-dialog-meta").textContent = meta;
  $("#prompt-dialog-list").innerHTML = promptCardsMarkup(list, true);
  wizardState.currentPromptText = list.length ? String(list[list.length - 1].prompt || "") : "";
  if (typeof dialog.showModal === "function") dialog.showModal();
}

async function showJobPrompts(url, meta) {
  try {
    const data = await api(url);
    openPromptDialog(data.items || [], meta);
  } catch (error) {
    showToast(error.message || "无法读取模型 Prompt。", true);
  }
}

async function refreshTasks() {
  if (!wizardState.workspace) return;
  const tasks = (await api(`/api/tasks?workspace=${encodeURIComponent(wizardState.workspace)}`)).items;
  wizardState._tasks = tasks;
  if (!wizardState.activeTaskId && tasks[0]) wizardState.activeTaskId = tasks[0].id;
  const activeTask = tasks.find((task) => task.id === wizardState.activeTaskId);
  $("#drawer-prompt-count").textContent = String(Number(activeTask?.prompt_count || 0));
  $("#delete-current-task").disabled = !activeTask || ["queued", "running"].includes(activeTask.status);
  $("#drawer-tasks").innerHTML = tasks.length ? tasks.map((task) => `<button class="drawer-task ${task.id === wizardState.activeTaskId ? "active" : ""}" data-task="${task.id}" type="button"><span><span class="drawer-task-title">${escapeHtml(task.label)}</span><span class="drawer-task-meta">${escapeHtml(task.created_at || "")}</span></span><span class="task-state ${task.status}">${taskLabel(task)}</span></button>`).join("") : '<p class="review-empty">当前工作区还没有任务记录。</p>';
  $$('[data-task]').forEach((button) => button.addEventListener("click", () => {
    wizardState.activeTaskId = button.dataset.task;
    wizardState.logOffset = 0;
    $("#drawer-log").textContent = "";
    refreshTasks().then(() => Promise.all([refreshLog(), refreshTaskPrompts()]));
  }));
}

async function refreshLog() {
  if (!wizardState.activeTaskId) return;
  try {
    const data = await api(`/api/tasks/${wizardState.activeTaskId}/logs?offset=${wizardState.logOffset}`);
    if (data.content) {
      const log = $("#drawer-log");
      log.textContent += data.content;
      log.scrollTop = log.scrollHeight;
      wizardState.logOffset = data.next_offset;
    }
    wizardState._tasks = wizardState._tasks?.map((item) => item.id === data.task.id ? data.task : item);
    $("#drawer-prompt-count").textContent = String(Number(data.task.prompt_count || 0));
    if (["succeeded", "succeeded_with_warnings", "failed"].includes(data.task.status) && wizardState.lastSyncedTaskId !== data.task.id) {
      wizardState.lastSyncedTaskId = data.task.id;
      await refreshTasks();
      await refreshWorkspaceArtifacts();
      showToast(data.task.status === "failed" ? "任务结束但未成功，请检查日志。" : "任务完成，生成内容已刷新。", data.task.status === "failed");
    }
  } catch (_) { /* A server restart clears in-memory task metadata. */ }
}

async function refreshWorkspaceArtifacts() {
  if (!wizardState.workspace) return;
  const [summary, tree] = await Promise.all([
    api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}`),
    api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/tree`),
  ]);
  wizardState.summary = summary;
  wizardState.fileTree = tree.items;
  renderRail();
  renderActiveStep();
}

async function refreshReviewArtifactsOnly(reloadSelected = false, expectedStep = "arcs", followLatest = false) {
  if (!wizardState.workspace || wizardState.activeStep !== expectedStep) return;
  const [summary, tree] = await Promise.all([
    api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}`),
    api(`/api/workspaces/${encodeURIComponent(wizardState.workspace)}/tree`),
  ]);
  wizardState.summary = summary;
  wizardState.fileTree = tree.items;
  renderRail();

  const step = WIZARD_STEPS.find((item) => item.id === expectedStep);
  const groups = reviewGroupsFor(step);
  const artifacts = groups.flatMap((group) => group.artifacts);
  wizardState.reviewArtifacts = artifacts;

  const empty = $("#review-empty");
  const layout = $("#review-layout");
  if (empty) empty.hidden = artifacts.length > 0;
  if (layout) layout.hidden = artifacts.length === 0;
  const continueButton = $("#confirm-step");
  if (continueButton) continueButton.disabled = artifacts.length === 0;
  if (!layout || !artifacts.length) return;

  const previousPath = wizardState.selectedFile;
  const outline = $("#artifact-outline");
  const nextOutline = reviewOutlineMarkup(step, groups, artifacts);
  if (outline) outline.outerHTML = nextOutline;
  else layout.insertAdjacentHTML("afterbegin", nextOutline);
  $$('[data-review-path]').forEach((button) => button.addEventListener("click", () => openReviewFile(button.dataset.reviewPath)));

  const selected = artifacts.find((artifact) => artifact.path === previousPath);
  if (followLatest) {
    await openReviewFile(artifacts[artifacts.length - 1].path);
  } else if (selected) {
    $$('[data-review-path]').forEach((button) => button.classList.toggle("active", button.dataset.reviewPath === previousPath));
    if (reloadSelected) await openReviewFile(previousPath);
  } else {
    await openReviewFile(artifacts[artifacts.length - 1].path);
  }
}

async function refreshWorkspaceOptions(selectedName = "") {
  const data = await api("/api/workspaces");
  const select = $("#workspace-select");
  select.innerHTML = data.items.length
    ? data.items.map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`).join("")
    : '<option value="">还没有工作区</option>';
  if (selectedName && data.items.some((item) => item.name === selectedName)) select.value = selectedName;
  const deleteButton = $("#delete-workspace");
  if (deleteButton) deleteButton.disabled = !data.items.length;
  return data;
}

function openWorkspacePanel() {
  $("#workspace-panel").classList.add("open");
  $("#workspace-panel").setAttribute("aria-hidden", "false");
  $("#workspace-scrim").classList.add("open");
  $("#new-workspace-name").focus();
}

function closeWorkspacePanel() {
  $("#workspace-panel").classList.remove("open");
  $("#workspace-panel").setAttribute("aria-hidden", "true");
  $("#workspace-scrim").classList.remove("open");
}

async function createWorkspace(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const name = $("#new-workspace-name").value.trim();
  if (!name) throw new Error("请填写作品名称。");
  if ([...$("#workspace-select").options].some((option) => option.value === name)) throw new Error("该工作区已存在，请使用其他名称。");
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    const task = await api("/api/tasks", { method: "POST", body: JSON.stringify({ type: "workspace_init", workspace: name, args: {} }) });
    await refreshWorkspaceOptions(name);
    await selectWorkspace(name);
    closeWorkspacePanel();
    form.reset();
    await activateTask(task, "工作区已创建，请在第一步导入参考小说。 ");
  } finally {
    submit.disabled = false;
  }
}

async function deleteCurrentWorkspace() {
  const name = wizardState.workspace || $("#workspace-select")?.value || "";
  if (!name) throw new Error("当前没有可删除的工作区。");
  const confirmed = window.confirm(
    `确认删除当前工作区“${name}”？\n\n对应的本地文件、生成内容、任务日志和 Prompt 都会被永久删除，此操作无法恢复。`,
  );
  if (!confirmed) return;

  const button = $("#delete-workspace");
  button.disabled = true;
  try {
    await api(`/api/workspaces/${encodeURIComponent(name)}`, { method: "DELETE" });
    const data = await refreshWorkspaceOptions();
    const nextName = data.items[0]?.name || "";
    $("#workspace-select").value = nextName;
    await selectWorkspace(nextName);
    showToast(`工作区“${name}”已删除。`);
  } finally {
    button.disabled = !$("#workspace-select")?.value;
  }
}

async function selectWorkspace(name) {
  wizardState.workspace = name || null;
  wizardState.confirmed = new Set();
  wizardState.activeTaskId = null;
  wizardState.logOffset = 0;
  wizardState.directionMode = "text";
  wizardState.directionFile = null;
  wizardState.directionFileContent = "";
  wizardState.referenceFile = null;
  wizardState.referenceScope = "all";
  wizardState.mechanicsMode = "auto";
  wizardState.mechanicsFile = null;
  wizardState.selectedFile = null;
  wizardState.selectedFileContent = "";
  wizardState.fileEditing = false;
  wizardState.designExtensionSource = "existing";
  wizardState.lastSyncedTaskId = null;
  if (!name) {
    wizardState.summary = null;
    wizardState.fileTree = [];
    wizardState.activeStep = "reference";
  } else {
    const [summary, tree] = await Promise.all([api(`/api/workspaces/${encodeURIComponent(name)}`), api(`/api/workspaces/${encodeURIComponent(name)}/tree`)]);
    wizardState.summary = summary;
    wizardState.fileTree = tree.items;
    wizardState.activeStep = currentRecommendedStep();
  }
  renderRail();
  renderActiveStep();
  refreshTasks();
}

async function boot() {
  try {
    const data = await refreshWorkspaceOptions();
    const select = $("#workspace-select");
    select.addEventListener("change", () => selectWorkspace(select.value));
    $("#new-workspace").addEventListener("click", openWorkspacePanel);
    $("#delete-workspace").addEventListener("click", async () => {
      try { await deleteCurrentWorkspace(); } catch (error) { showToast(error.message || "无法删除工作区。", true); }
    });
    $("#new-workspace-form").addEventListener("submit", async (event) => {
      try { await createWorkspace(event); } catch (error) { showToast(error.message || "无法创建工作区。", true); }
    });
    $("#cancel-workspace").addEventListener("click", closeWorkspacePanel);
    $("#close-workspace-panel").addEventListener("click", closeWorkspacePanel);
    $("#workspace-scrim").addEventListener("click", closeWorkspacePanel);
    $("#open-task-drawer").addEventListener("click", () => { $("#task-drawer").classList.add("open"); $("#drawer-scrim").classList.add("open"); refreshTasks(); });
    $("#close-task-drawer").addEventListener("click", closeDrawer);
    $("#drawer-scrim").addEventListener("click", closeDrawer);
    $("#close-file-browser").addEventListener("click", closeFileBrowser);
    $("#file-scrim").addEventListener("click", closeFileBrowser);
    $("#file-search").addEventListener("input", renderFileBrowser);
    $("#open-settings").addEventListener("click", openSettings);
    $("#close-settings").addEventListener("click", closeSettings);
    $("#settings-scrim").addEventListener("click", closeSettings);
    $$('[data-task-view]').forEach((button) => button.addEventListener("click", () => setTaskView(button.dataset.taskView)));
    $("#close-prompt-dialog").addEventListener("click", () => $("#prompt-dialog").close());
    $("#copy-current-prompt").addEventListener("click", async () => {
      if (!wizardState.currentPromptText) return;
      await navigator.clipboard.writeText(wizardState.currentPromptText);
      showToast("Prompt 已复制。");
    });
    $("#clear-workspace-prompts").addEventListener("click", async () => {
      if (!wizardState.workspace || !confirm("清空当前工作区所有已结束任务的 Prompt 记录？任务日志和生成产物不会删除。")) return;
      try {
        const result = await api(`/api/task-prompts?workspace=${encodeURIComponent(wizardState.workspace)}`, { method: "DELETE" });
        $("#drawer-prompts").innerHTML = '<p class="drawer-prompt-empty">当前工作区的历史 Prompt 已清空。</p>';
        $("#drawer-prompt-count").textContent = "0";
        await refreshTasks();
        const skipped = Number(result.skipped_active_count || 0);
        showToast(skipped ? `已清理历史 Prompt；${skipped} 个运行中任务已跳过。` : "当前工作区的历史 Prompt 已清空。");
      } catch (error) { showToast(error.message || "无法清空 Prompt。", true); }
    });
    $("#delete-current-task").addEventListener("click", async () => {
      if (!wizardState.activeTaskId || !confirm("删除当前任务记录？对应执行日志和 Prompt 也会一并删除，此操作不可恢复。")) return;
      try {
        await api(`/api/tasks/${wizardState.activeTaskId}`, { method: "DELETE" });
        wizardState.activeTaskId = null;
        wizardState.logOffset = 0;
        $("#drawer-log").textContent = "";
        $("#drawer-prompts").innerHTML = '<p class="drawer-prompt-empty">请选择任务。</p>';
        await refreshTasks();
        showToast("任务记录、日志和 Prompt 已删除。");
      } catch (error) { showToast(error.message || "无法删除任务记录。", true); }
    });
    document.addEventListener("click", (event) => {
      const id = event.target.closest("button")?.id;
      const workspace = encodeURIComponent(wizardState.workspace || "");
      if (id === "show-arcs-prompt") {
        showJobPrompts(`/api/workspaces/${workspace}/arcs/${Number(wizardState.arcsChatVolume || 1)}/prompts`, "故事情节 · 模型 Prompt");
      } else if (id === "show-chapters-prompt") {
        showJobPrompts(`/api/workspaces/${workspace}/chapters/${Number(wizardState.chaptersChatVolume || 1)}/${Number(wizardState.chaptersChatArc || 1)}/prompts`, "逐章章纲 · 模型 Prompt");
      } else if (id === "show-draft-prompt") {
        showJobPrompts(`/api/workspaces/${workspace}/drafts/${Number(wizardState.draftChatVolume || 1)}/${Number(wizardState.draftChatArc || 1)}/prompts`, "正文生成 · 模型 Prompt");
      }
    });
    await selectWorkspace(data.items[0]?.name || "");
    setInterval(async () => {
      await refreshLog();
      if (wizardState.taskView === "prompt" && $("#task-drawer").classList.contains("open")) await refreshTaskPrompts();
    }, 1400);
  } catch (error) { showToast(error.message, true); }
}

function closeDrawer() { $("#task-drawer").classList.remove("open"); $("#drawer-scrim").classList.remove("open"); }
boot();
