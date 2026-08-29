"use strict";

// ---------- 전역 상태 ----------
let FLOW = { steps: [] };
let ENGINES = { roles: {} };
let EXAMPLES = [];
let PID = null;        // 현재 프로젝트 id
let STATE = null;      // 현재 프로젝트 state.json
let SELECTED = null;   // 중앙에 표시 중인 step id
let sse = null;
let DIAG = null;       // 마지막 진단 결과
let DIAG_DONE = false;  // 이번 프로젝트에서 진단을 한 번이라도 돌렸는가

const $ = (id) => document.getElementById(id);
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(url + " → " + r.status);
  return r.json();
};
const postJSON = (url, body) =>
  api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

// ---------- 초기화 ----------
async function init() {
  [FLOW, ENGINES] = await Promise.all([api("/api/flow"), api("/api/engines")]);
  try { EXAMPLES = (await api("/api/examples")).examples || []; } catch (e) { EXAMPLES = []; }

  $("newProjectBtn").onclick = onNewProject;
  $("editFlowBtn").onclick = openFlowEditor;
  $("projectSelect").onchange = (e) => selectProject(e.target.value);
  $("flowCancel").onclick = () => $("flowOverlay").classList.remove("open");
  $("flowSave").onclick = saveFlow;

  await loadProjects();
}

async function loadProjects() {
  const { projects } = await api("/api/projects");
  const sel = $("projectSelect");
  sel.innerHTML = "";
  if (!projects.length) {
    const o = document.createElement("option");
    o.textContent = "(프로젝트 없음)";
    o.value = "";
    sel.appendChild(o);
    return;
  }
  for (const p of projects) {
    const o = document.createElement("option");
    o.value = p.id;
    o.textContent = p.name + "  ·  " + p.id;
    sel.appendChild(o);
  }
  const target = PID && projects.some((p) => p.id === PID) ? PID : projects[projects.length - 1].id;
  sel.value = target;
  await selectProject(target);
}

async function onNewProject() {
  const name = prompt("새 프로젝트 이름 (비워도 됨):", "") || "";
  const st = await postJSON("/api/projects", { name });
  PID = st.project_id;
  await loadProjects();
}

// ---------- 프로젝트 선택 + SSE ----------
async function selectProject(id) {
  if (!id) return;
  PID = id;
  STATE = await api(`/api/projects/${id}/state`);
  SELECTED = STATE.current_step;
  DIAG = null; DIAG_DONE = false;   // 프로젝트 바뀌면 진단 초기화
  connectSSE(id);
  renderAll();
}

function connectSSE(id) {
  if (sse) { sse.close(); sse = null; }
  sse = new EventSource(`/sse/projects/${id}`);
  sse.addEventListener("update", async () => {
    try {
      STATE = await api(`/api/projects/${id}/state`);
      renderAll();
    } catch (e) {}
  });
}

// ---------- 렌더 ----------
function stepDef(id) { return FLOW.steps.find((s) => s.id === id); }

function renderAll() {
  renderFlowList();
  renderCenter();
  renderAudit();
}

function renderFlowList() {
  const box = $("flowList");
  box.innerHTML = "";
  FLOW.steps.forEach((s, i) => {
    const st = (STATE && STATE.steps[s.id]) || { status: "locked", gate: s.gate };
    const div = document.createElement("div");
    div.className = "step-item " + st.status +
      (s.id === SELECTED ? " on" : "") +
      (s.gate ? " gate" : "") +
      (st.status === "done" ? " done" : "") +
      (st.status === "locked" ? " locked" : "");
    const gateBadge = s.gate ? `<span class="badge gate">GATE</span>` : "";
    const stBadge =
      st.status === "done" ? `<span class="badge done">완료</span>` :
      st.status === "locked" ? `<span class="badge lock">🔒</span>` :
      st.status === "awaiting_user" ? `<span class="badge gate">확정대기</span>` : "";
    div.innerHTML =
      `<div class="num">${i + 1}</div>
       <div><div class="t">${escapeHtml(s.title)} ${gateBadge}${stBadge}</div>
       <div class="meta">${s.id}${s.engines && s.engines.length ? " · ⚙엔진" : ""}</div></div>`;
    div.onclick = () => { SELECTED = s.id; renderCenter(); renderFlowList(); };
    box.appendChild(div);
  });
}

function renderCenter() {
  const empty = $("centerEmpty"), detail = $("stepDetail");
  if (!STATE) { empty.style.display = ""; detail.style.display = "none"; return; }
  empty.style.display = "none"; detail.style.display = "";
  const s = stepDef(SELECTED) || FLOW.steps[0];
  const st = STATE.steps[s.id] || {};
  const locked = st.status === "locked";

  let html = `<div class="card"><h3>${escapeHtml(s.title)}</h3>
    <p class="desc">${escapeHtml(s.desc || "")}</p>`;

  if (locked) {
    html += `<div class="locknote">🔒 이전 게이트가 통과되지 않아 잠겨 있습니다. 앞 단계를 먼저 확정하세요.</div>`;
  }

  // 진단 단계 (환경·도구 체크)
  if (s.diagnostic && !locked) {
    html += renderDiagnosticBlock();
  }

  // 입력 필드
  const inputs = s.inputs || [];
  if (inputs.length) {
    html += `<div style="margin-top:8px">`;
    for (const f of inputs) {
      const val = (STATE.inputs && STATE.inputs[f] != null) ? STATE.inputs[f] : "";
      if (f === "asset_list") {
        html += renderAssetList(val, locked);
      } else {
        const isLong = f === "background";
        html += `<div class="field"><label>${labelFor(f)}</label>` +
          (isLong
            ? `<textarea data-field="${f}" ${locked ? "disabled" : ""} placeholder="여기에 직접 입력…">${escapeHtml(String(val))}</textarea>`
            : `<input data-field="${f}" ${locked ? "disabled" : ""} placeholder="여기에 직접 입력…" value="${escapeAttr(String(val))}">`) +
          `</div>`;
      }
    }
    html += `</div>`;
  }

  // 엔진 선택
  if (s.engines && s.engines.length) {
    html += `<div style="margin-top:10px">`;
    for (const eng of s.engines) {
      const role = ENGINES.roles[eng.role] || { label: eng.role, choices: [], default: "" };
      const key = eng.key || (s.id + "." + eng.role);
      const cur = (STATE.engine_choices && STATE.engine_choices[key]) || role.default;
      html += `<div class="engine-row"><span class="lbl">⚙ ${escapeHtml(role.label)}</span>
        <select data-engine="${key}" ${locked ? "disabled" : ""}>` +
        role.choices.map((c) => `<option ${c === cur ? "selected" : ""}>${escapeHtml(c)}</option>`).join("") +
        `</select></div>`;
    }
    html += `</div>`;
  }

  // 게이트 버튼
  if (s.gate) {
    const passed = st.gate_passed;
    const canPass = !locked && stepReady(s);
    html += `<div class="gatebox">
      <div class="g-title">GATE — 사용자 확정 지점 ${passed ? "✅ 통과됨 (" + (st.passed_by || "") + ")" : ""}</div>`;
    if (!passed) {
      html += `<button class="btn gate" ${canPass ? "" : "disabled"} onclick="passGate('${s.id}')">이 단계 확정 → 다음 잠금 해제</button>`;
      if (!canPass && !locked) html += `<div class="locknote">${s.diagnostic ? "먼저 '진단 시작'을 눌러 환경을 진단하세요." : "필수 입력을 먼저 채워야 확정할 수 있습니다."}</div>`;
    } else {
      html += `<button class="btn undo" onclick="undoGate('${s.id}')">확정 취소</button>`;
    }
    html += `</div>`;
  }

  html += `</div>`;

  // 예시 참고 (회색) — 첫 입력 단계에만
  if (s.inputs && s.inputs.length && EXAMPLES.length) {
    html += renderExampleRef();
  }

  $("stepDetail").innerHTML = html;
  wireInputs(s, locked);
  loadDoc(s.doc_ref);
}

function renderAssetList(val, locked) {
  const arr = Array.isArray(val) ? val : [];
  let h = `<div class="field"><label>${labelFor("asset_list")}</label>
    <div style="display:flex;gap:6px">
      <input id="assetInput" ${locked ? "disabled" : ""} placeholder="에셋 추가 후 Enter" style="flex:1">
      <button class="btn small" ${locked ? "disabled" : ""} onclick="addAsset()">추가</button>
    </div>
    <div class="tag-list">`;
  arr.forEach((a, i) => {
    h += `<span class="chip">${escapeHtml(a)} <b onclick="removeAsset(${i})">✕</b></span>`;
  });
  h += `</div></div>`;
  return h;
}

function renderExampleRef() {
  const name = EXAMPLES[0];
  return `<div class="example-ref">
    <div class="h">참고 예시 (회색 · 현재 값 아님)</div>
    <div class="val" id="exampleBody">불러오는 중…</div>
    <button class="btn small" style="margin-top:8px" onclick="fillFromExample('${name}')">이 예시 값으로 채우기 (명시적)</button>
    <div class="hint" style="margin-top:4px">※ 누르지 않으면 예시는 절대 프로젝트 값으로 들어오지 않습니다.</div>
  </div>`;
}

async function loadExampleBody() {
  if (!EXAMPLES.length) return;
  const el = $("exampleBody");
  if (!el) return;
  try {
    const ex = await api("/api/examples/" + encodeURIComponent(EXAMPLES[0]));
    const inp = ex.inputs || {};
    el.innerHTML = Object.keys(inp).map((k) =>
      `<div><b>${labelFor(k)}:</b> ${escapeHtml(Array.isArray(inp[k]) ? inp[k].join(", ") : String(inp[k]))}</div>`
    ).join("");
  } catch (e) { el.textContent = "(예시 불러오기 실패)"; }
}

// ---------- 진단 (환경·도구 체크) ----------
function renderDiagnosticBlock() {
  let h = `<div style="margin-top:6px">
    <div class="hint" style="margin-bottom:8px">아래는 <b>필요 환경/도구 체크리스트</b>입니다. <b style="color:var(--gate)">★</b> = 핵심 필수(OpenAI 키·Hunyuan 모델·UnrealClaude MCP). <b>진단 시작</b>을 누르면 각 항목을 실제로 점검합니다.</div>
    <button class="btn small" id="diagBtn" onclick="runDiagnose()">진단 시작</button>
    <span id="diagStatus" class="hint" style="margin-left:8px"></span>
    <div id="diagResult" style="margin-top:10px"></div>
  </div>`;
  // 진입 즉시: 이미 진단했으면 결과, 아니면 체크리스트(미확인)를 먼저 리스트업
  setTimeout(() => { if (DIAG) paintDiag(DIAG); else loadDiagSpec(); }, 0);
  return h;
}

async function loadDiagSpec() {
  const res = $("diagResult");
  if (!res) return;
  res.innerHTML = `<div class="hint">체크리스트 불러오는 중…</div>`;
  try {
    const s = await api("/api/diagnose/spec");
    res.innerHTML = renderDiagSpec(s);
  } catch (e) {
    res.innerHTML = `<div class="hint" style="color:var(--bad)">체크리스트 로드 실패: ${e.message}</div>`;
  }
}

function renderDiagSpec(data) {
  return specSummary(data.items || []) + buildDiagStages(data, true);
}

function paintDiag(d) {
  const stat = $("diagStatus"), res = $("diagResult");
  if (!stat || !res) return;
  const miss = d.required_missing || [];
  stat.innerHTML = miss.length
    ? `<span style="color:var(--warn)">핵심 확인필요: ${escapeHtml(miss.join(", "))}</span>`
    : `<span style="color:var(--good)">핵심 준비됨 ✅ — 확정 가능</span>`;
  res.innerHTML = diagSummary(d) + buildDiagStages(d, false);
}

function specSummary(items) {
  const req = items.filter((i) => i.required).length;
  return `<div class="diag-summary">
    <div class="cell"><div class="lb">핵심 ★</div><div class="big" style="color:var(--gate)">${req}</div></div>
    <div class="cell"><div class="lb">전체</div><div class="big">${items.length}</div></div>
    <div class="diag-bar"><span style="width:0%"></span></div>
    <div class="diag-note">미진단 — '진단 시작'을 누르세요</div>
  </div>`;
}

function diagSummary(d) {
  const items = d.items || [];
  const req = items.filter((i) => i.required);
  const reqOk = req.filter((i) => i.ok).length;
  const allOk = items.filter((i) => i.ok).length;
  const pct = items.length ? Math.round(allOk / items.length * 100) : 0;
  const reqDone = reqOk === req.length;
  return `<div class="diag-summary">
    <div class="cell"><div class="lb">핵심 ★ 준비</div><div class="big" style="color:${reqDone ? 'var(--good)' : 'var(--bad)'}">${reqOk}/${req.length}</div></div>
    <div class="cell"><div class="lb">전체 준비</div><div class="big">${allOk}/${items.length}</div></div>
    <div class="diag-bar"><span style="width:${pct}%"></span></div>
    <div class="diag-note">${reqDone ? '<span style="color:var(--good)">핵심 준비 완료 — 확정 가능</span>' : '핵심 항목을 채우세요'}</div>
  </div>`;
}

function buildDiagStages(data, pending) {
  const stages = data.stages || [];
  const items = data.items || [];
  const byStage = {};
  items.forEach((i) => { (byStage[i.stage] = byStage[i.stage] || []).push(i); });
  let h = "";
  stages.forEach((s, idx) => {
    const list = byStage[s.key] || [];
    if (!list.length) return;
    let badge = "";
    if (!pending) {
      const ok = list.filter((i) => i.ok).length;
      const reqMiss = list.some((i) => i.required && !i.ok);
      const cls = reqMiss ? "bad" : (ok === list.length ? "good" : "");
      badge = `<span class="stage-count ${cls}">${ok}/${list.length}</span>`;
    }
    // 단계 사이 화살표 (순서 강조)
    if (idx > 0) h += `<div class="stage-arrow">▼</div>`;
    h += `<div class="diag-stage"><div class="diag-stage-h">${escapeHtml(s.label)} ${badge}</div>`;
    for (const i of list) {
      const st = pending ? "pending" : (i.ok ? "ok" : (i.required ? "req" : "warn"));
      const icon = st === "ok" ? "✓" : st === "req" ? "✕" : st === "warn" ? "!" : "";
      const detail = pending ? (i.need || "") : (i.detail || "");
      h += `<div class="diag-row ${st}">
        <div class="box">${icon}</div>
        <div class="grow">
          <div class="nm">${escapeHtml(i.name)}${i.required ? '<span class="diag-star">★</span>' : ''}</div>
          <div class="nd">${escapeHtml(detail)}</div>
        </div>
      </div>`;
    }
    h += `</div>`;
  });
  return h;
}

window.runDiagnose = async () => {
  const btn = $("diagBtn"), stat = $("diagStatus"), res = $("diagResult");
  if (btn) btn.disabled = true;
  if (stat) stat.innerHTML = `<span style="color:var(--accent)">진단중…</span>`;
  if (res) res.innerHTML = "";
  try {
    const d = await api("/api/diagnose");
    DIAG = d; DIAG_DONE = true;
    paintDiag(d);
    updateGateButtons();  // 진단 완료 → 게이트 버튼 활성화
  } catch (e) {
    if (stat) stat.textContent = "진단 실패: " + e.message;
  }
  if (btn) { btn.disabled = false; btn.textContent = "다시 진단"; }
};

function renderAudit() {
  const box = $("auditLog");
  if (!STATE || !STATE.audit_log) { box.innerHTML = ""; return; }
  box.innerHTML = STATE.audit_log.slice().reverse().slice(0, 40).map((a) =>
    `<div class="a"><span class="tm">${(a.t || "").slice(11)}</span> ${escapeHtml(a.action)} — ${escapeHtml(a.detail || "")}</div>`
  ).join("");
}

async function loadDoc(ref) {
  if (!ref) { $("docView").textContent = "(연결된 문서 없음)"; $("docTitle").textContent = ""; return; }
  $("docTitle").textContent = "📄 " + ref;
  try {
    const d = await api("/api/doc?ref=" + encodeURIComponent(ref));
    $("docView").textContent = d.text || "(빈 문서)";
  } catch (e) { $("docView").textContent = "(문서 로드 실패: " + ref + ")"; }
}

// ---------- 입력 이벤트 배선 ----------
function wireInputs(s, locked) {
  if (locked) return;
  document.querySelectorAll("[data-field]").forEach((el) => {
    el.onchange = () => saveInput(el.getAttribute("data-field"), el.value);
  });
  document.querySelectorAll("[data-engine]").forEach((el) => {
    el.onchange = () => setEngine(el.getAttribute("data-engine"), el.value);
  });
  const ai = $("assetInput");
  if (ai) ai.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); addAsset(); } };
  loadExampleBody();
}

// ---------- 액션 ----------
async function saveInput(field, value) {
  STATE = await postJSON(`/api/projects/${PID}/input`, { field, value });
  renderFlowList(); // 게이트 버튼 활성화 등 갱신
  updateGateButtons();
}
async function setEngine(key, value) {
  STATE = await postJSON(`/api/projects/${PID}/engine`, { key, value });
}
window.passGate = async (step) => {
  STATE = await postJSON(`/api/projects/${PID}/gate`, { step });
  SELECTED = STATE.current_step;
  renderAll();
};
window.undoGate = async (step) => {
  STATE = await postJSON(`/api/projects/${PID}/ungate`, { step });
  renderAll();
};
window.fillFromExample = async (name) => {
  if (!confirm("예시 '" + name + "' 값을 현재 프로젝트 입력에 복사합니다. 진행할까요?")) return;
  STATE = await postJSON(`/api/projects/${PID}/fill-from-example`, { example: name });
  renderCenter(); renderAudit();
};
window.addAsset = async () => {
  const el = $("assetInput"); if (!el || !el.value.trim()) return;
  const arr = Array.isArray(STATE.inputs.asset_list) ? STATE.inputs.asset_list.slice() : [];
  arr.push(el.value.trim());
  STATE = await postJSON(`/api/projects/${PID}/input`, { field: "asset_list", value: arr });
  renderCenter();
};
window.removeAsset = async (i) => {
  const arr = (STATE.inputs.asset_list || []).slice();
  arr.splice(i, 1);
  STATE = await postJSON(`/api/projects/${PID}/input`, { field: "asset_list", value: arr });
  renderCenter();
};

function updateGateButtons() {
  const s = stepDef(SELECTED);
  if (!s || !s.gate) return;
  const btn = document.querySelector(".gatebox .btn.gate");
  if (btn) btn.disabled = !stepReady(s);
}

// ---------- 플로우 편집 ----------
function openFlowEditor() {
  $("flowEditor").value = JSON.stringify(FLOW, null, 2);
  $("flowEditErr").textContent = "";
  $("flowOverlay").classList.add("open");
}
async function saveFlow() {
  let parsed;
  try { parsed = JSON.parse($("flowEditor").value); }
  catch (e) { $("flowEditErr").textContent = "JSON 오류: " + e.message; return; }
  if (!parsed.steps) { $("flowEditErr").textContent = "steps 배열이 필요합니다."; return; }
  await api("/api/flow", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(parsed) });
  FLOW = parsed;
  $("flowOverlay").classList.remove("open");
  if (PID) STATE = await api(`/api/projects/${PID}/state`);
  renderAll();
}

// ---------- 헬퍼 ----------
function stepReady(s) {
  // 진단 단계는 진단을 한 번 돌려야 확정 가능. 그 외는 필수 입력이 채워져야.
  if (s.diagnostic) return DIAG_DONE;
  return inputsFilled(s);
}
function inputsFilled(s) {
  if (!s.inputs || !s.inputs.length) return true;
  for (const f of s.inputs) {
    const v = STATE.inputs ? STATE.inputs[f] : null;
    if (v == null) return false;
    if (Array.isArray(v) && v.length === 0) return false;
    if (typeof v === "string" && v.trim() === "") return false;
  }
  return true;
}
function labelFor(f) {
  return { topic: "주제", background: "배경", anchor: "앵커(스타일 기준)", asset_list: "에셋 리스트" }[f] || f;
}
function escapeHtml(s) { return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
function escapeAttr(s) { return escapeHtml(s).replace(/"/g, "&quot;"); }

init().catch((e) => { document.body.innerHTML = "<pre style='padding:20px;color:#ff6b6b'>초기화 실패: " + e.message + "</pre>"; });
