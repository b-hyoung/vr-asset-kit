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
let DOC_FULL = "";     // 현재 문서 전체 텍스트 (더보기 모달용)
let DOC_REF = "";      // 현재 문서 ref
let COLLAPSED = {};    // 스테이지 접힘 상태(사용자 토글). 없으면 '완료 시 접힘' 기본
let AUTO_INSTALL = new Set();  // 그 자리 설치 가능한 항목
let WINGET = false;
let MODELS = { image: [] };    // 이미지 모델 카탈로그
let MODEL_PRESENT = {};        // repo -> true/false/undefined(확인중)
let MODEL_PARTIAL = {};        // repo -> 받다 만 조각이 있나
let MODEL_CHECKED_AT = {};     // repo -> 마지막 확인 시각(ms). 미설치 판정 재확인용
let CHECKING = new Set();      // 존재 확인 진행중 repo (중복 fetch 방지)
let KEY_SAVED = new Set();     // 이번 세션에 저장한 키(즉시 반영)
let HF_USER = null;            // {logged_in, name, invalid}
let ASSET_SUGGESTIONS = null;
let LAST_SUGGEST_USED_REF = false;   // 마지막 추천이 배경 이미지를 봤는가
let LIGHTING = { presets: [] };  // 조명 프리셋 표(lighting.json) — 노을은 그중 하나

async function loadHfWhoami() {
  try { HF_USER = await api("/api/hf/whoami"); } catch (e) { HF_USER = { logged_in: false }; }
}

// 모델 상태줄에 붙는 보조 UI.
// ★ '미다운로드'로 보이는데 실제로는 받아둔 경우가 있어(밖에서 설치·조회 실패)
//   사용자가 새로고침 없이 다시 확인할 수 있어야 한다.
function presenceRecheckHtml(repo, pres) {
  let h = "";
  if (pres === false) {
    h += ` <button class="btn small" style="margin-left:6px" onclick="recheckModels()" title="이미 받아뒀는데 미다운로드로 보이면 누르세요">↻ 다시 확인</button>`;
  }
  if (MODEL_PARTIAL[repo]) {
    h += `<div class="hint" style="color:var(--warn);margin-top:4px">⚠ 받다 만 조각(.incomplete)이 남아 있습니다 — 설치를 다시 돌려 마저 받으세요.</div>`;
  }
  return h;
}

async function checkPresence(repo) {
  if (!repo) return;
  try {
    const r = await api("/api/hf/present?repo=" + encodeURIComponent(repo));
    MODEL_PRESENT[repo] = !!r.present;
    MODEL_PARTIAL[repo] = !!r.partial;
    MODEL_CHECKED_AT[repo] = Date.now();
  } catch (e) {
    // ★ 조회 실패를 '미설치'로 저장하면 안 된다 — false 가 캐시로 굳어
    //   실제로 받아둔 모델이 새로고침 전까지 계속 미설치로 보인다(실측 버그).
    //   모르는 상태(undefined)로 두어 다음 렌더에서 다시 확인하게 한다.
    delete MODEL_PRESENT[repo];
    delete MODEL_CHECKED_AT[repo];
  }
}

// ★ 캐시 무효화 — 밖에서 받은 모델(별도 설치 창·다른 방법)을 화면이 못 따라가는 문제를 막는다.
function invalidatePresence(repo) {
  if (repo) { delete MODEL_PRESENT[repo]; delete MODEL_CHECKED_AT[repo]; }
  else { MODEL_PRESENT = {}; MODEL_CHECKED_AT = {}; }
}

// '미설치'로 판정된 항목만 오래됐으면 다시 본다. (있음=true 는 뒤집힐 일이 없어 재조회 불필요)
function refreshStalePresence(maxAgeMs) {
  const now = Date.now();
  let dirty = false;
  for (const repo of Object.keys(MODEL_PRESENT)) {
    if (MODEL_PRESENT[repo] === true) continue;
    if (now - (MODEL_CHECKED_AT[repo] || 0) < maxAgeMs) continue;
    invalidatePresence(repo);
    dirty = true;
  }
  if (dirty) updateReadyUI();
}

window.recheckModels = async () => {
  invalidatePresence(null);
  updateReadyUI();
};

// 창으로 돌아오면(설치 창에서 받고 온 직후 등) 미설치 판정을 다시 확인한다.
window.addEventListener("focus", () => refreshStalePresence(5000));
// 선택/키 변경 시 전체 리렌더 없이 관련 부분만 갱신 (딸깍 방지)
function updateReadyUI() {
  const ic = $("imgChooserWrap"); if (ic) ic.innerHTML = imageChooser();
  const mc = $("meshChooserWrap"); if (mc) mc.innerHTML = meshChooser();
  const ef = $("envFlow"); if (ef) ef.outerHTML = envFlowLine();
  updateGateButtons();
  maybeRelockEnv();   // 준비 깨지면 1단계 재잠금
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 스크롤 위치 보존(재렌더 시 위로 튀는 것 방지)
function keepScroll(fn) {
  const el = $("centerPane");
  const sp = el ? el.scrollTop : 0;
  fn();
  if (!el) return;
  el.scrollTop = sp;
  setTimeout(() => { el.scrollTop = sp; }, 60);   // async 재그림 뒤 한 번 더
  setTimeout(() => { el.scrollTop = sp; }, 220);
}
function stageCollapsed(key, fullyOk) {
  return (key in COLLAPSED) ? COLLAPSED[key] : fullyOk;  // 기본: 완료된 단계는 접힘
}
window.toggleStage = (key) => {
  const shown = (window._stageState || {})[key];  // 현재 화면의 접힘 여부를 정확히 반전
  COLLAPSED[key] = !shown;
  keepScroll(() => renderCenter());
};

const $ = (id) => document.getElementById(id);
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  if (!r.ok) {
    // ★ 서버가 사람이 읽을 안내(message)를 주는 경우가 있다. 그걸 버리고 "→ 409" 만
    //   보여주면 사용자는 무엇을 해야 할지 알 수 없다.
    let detail = null;
    try { detail = await r.json(); } catch (e) {}
    const err = new Error((detail && (detail.message || detail.error)) || (url + " → " + r.status));
    err.status = r.status;
    err.detail = detail;
    throw err;
  }
  return r.json();
};
const postJSON = (url, body) =>
  api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

// ---------- 초기화 ----------
async function init() {
  [FLOW, ENGINES] = await Promise.all([api("/api/flow"), api("/api/engines")]);
  try { LIGHTING = await api("/api/lighting"); } catch (e) { LIGHTING = { presets: [] }; }
  try { EXAMPLES = (await api("/api/examples")).examples || []; } catch (e) { EXAMPLES = []; }
  try { const a = await api("/api/install/available"); AUTO_INSTALL = new Set(a.items || []); WINGET = !!a.winget; } catch (e) {}
  try { MODELS = await api("/api/models"); } catch (e) { MODELS = { image: [] }; }
  await loadHfWhoami();

  $("newProjectBtn").onclick = onNewProject;
  $("editFlowBtn").onclick = openFlowEditor;
  $("resetProjectBtn").onclick = onResetProject;
  $("projectSelect").onchange = (e) => selectProject(e.target.value);
  $("flowCancel").onclick = () => $("flowOverlay").classList.remove("open");
  $("flowSave").onclick = saveFlow;
  $("docMoreBtn").onclick = openDocModal;
  $("docModalClose").onclick = () => $("docOverlay").classList.remove("open");
  $("docOverlay").onclick = (e) => { if (e.target.id === "docOverlay") $("docOverlay").classList.remove("open"); };

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
  // ★ 다른 PC에서 만들어진 프로젝트를 자동으로 열지 않는다.
  //   폴더째 넘겨받으면 이전 사람의 주제·에셋이 채워진 채로 열려 자기 작업처럼 보인다(실측 버그).
  const last = projects[projects.length - 1];
  const foreignOnly = projects.every((p) => p.foreign === true);
  if (!PID && foreignOnly) {
    const o = document.createElement("option");
    o.textContent = "(열지 않음 — 아래 안내 확인)";
    o.value = "";
    sel.insertBefore(o, sel.firstChild);
    sel.value = "";
    renderForeignNotice(projects);
    return;
  }
  const target = PID && projects.some((p) => p.id === PID) ? PID : last.id;
  sel.value = target;
  await selectProject(target);
}

// 넘겨받은 폴더에 남의 프로젝트만 있을 때 뜨는 안내. 자동으로 열지도, 지우지도 않는다.
function renderForeignNotice(projects) {
  const who = projects.map((p) => (p.origin && p.origin.host) ? p.origin.host : "다른 PC");
  const empty = $("centerEmpty"), detail = $("stepDetail");
  if (!empty || !detail) return;
  empty.style.display = "none";
  detail.style.display = "";
  detail.innerHTML = `<div class="card" style="border-color:var(--warn)">
    <h2 style="margin-top:0">⚠ 이 폴더에 다른 PC의 작업이 남아 있습니다</h2>
    <p class="hint">프로젝트 ${projects.length}개가 <b>${escapeHtml(who[0])}</b> 에서 만들어진 것입니다.
    이전 사람의 주제·배경·에셋 목록이 그대로 들어 있어, 열면 내 작업처럼 보입니다.</p>
    <p class="hint">새로 시작하려면 아래를 누르세요. 남의 프로젝트는 지우지 않고 그대로 둡니다
    (위 선택 상자에서 골라 열어볼 수는 있습니다).</p>
    <button class="btn gate" onclick="onNewProject()">＋ 내 프로젝트 새로 만들기</button>
  </div>`;
}

// 넘겨받은 프로젝트를 이어 쓰거나, 주제를 갈아엎을 때 쓴다.
// 입력값과 게이트만 비우고 모델·엔진 선택(환경 설정)은 남긴다 — 다시 고르게 하면 준비를 처음부터 반복하게 된다.
async function onResetProject() {
  if (!PID) { alert("먼저 프로젝트를 선택하세요."); return; }
  const inp = (STATE && STATE.inputs) || {};
  const filled = Object.keys(inp).filter((k) => {
    const v = inp[k];
    return Array.isArray(v) ? v.length > 0 : (v !== null && v !== undefined && String(v).trim() !== "");
  });
  const list = filled.length ? filled.join(", ") : "(채워진 입력 없음)";
  if (!confirm(
    "이 프로젝트의 입력을 모두 비웁니다.\n\n" +
    "지워짐: " + list + "\n" +
    "게이트: 전부 해제되어 1단계부터 다시 확정해야 합니다.\n" +
    "남음: 모델·엔진 선택, 생성된 파일(out 폴더)\n\n계속할까요?"
  )) return;
  STATE = await postJSON(`/api/projects/${PID}/reset`, {});
  SELECTED = STATE.current_step;
  renderAll();
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
  ASSET_SUGGESTIONS = (STATE.asset_suggestions && STATE.asset_suggestions.length) ? STATE.asset_suggestions : null;  // 저장된 추천 복원
  connectSSE(id);
  renderAll();
  // 선택된 로컬 모델의 실제 존재를 확인 → 준비 깨졌으면 1단계 재잠금
  const ec = STATE.engine_choices || {};
  const repos = [ec.image_repo, ec.mesh_repo].filter(Boolean);
  Promise.all(repos.map((r) => (MODEL_PRESENT[r] === undefined ? checkPresence(r) : null)))
    .then(() => { maybeRelockEnv(); renderFlowList(); });
}

function connectSSE(id) {
  if (sse) { sse.close(); sse = null; }
  sse = new EventSource(`/sse/projects/${id}`);
  sse.addEventListener("update", async () => {
    try {
      STATE = await api(`/api/projects/${id}/state`);
      // 가운데는 사용자가 조작 중이므로 건드리지 않음 (스크롤 튐·생성물 소실 방지)
      renderFlowList(); renderAudit(); updateGateButtons();
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

// a→z 지도: 준비 → 제작 → 배치 → 완료 로 묶어서 표시
// 제작~export: 웹이 아니라 Claude+언리얼 MCP가 실행하는 단계
const CLAUDE_STEPS = new Set(["make", "blender", "ue_import", "place", "lighting", "export"]);
function claudeHandoff() {
  // ★ 지시문은 서버가 state 로 만든다. 화면에서 조립하면 실행되는 문장과 보이는 문장이
  //   달라질 수 있다(실측: 옛 경로 vr-harness/ 가 화면에만 남아 있었다).
  return `<div class="handoff">
    <div class="hh-title">🤖 이 단계는 <b>Claude + 언리얼 MCP</b>가 실행합니다 (웹은 준비·확정 담당)</div>
    <div class="hint" style="margin:6px 0">
      아래 버튼을 누르면 <b>Claude 창이 열리면서 지시문이 자동으로 입력</b>됩니다. 붙여넣지 않아도 됩니다.
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px">
      <button class="btn gate" onclick="launchClaude(this)">▶ Claude 실행 (지시문 자동 입력)</button>
      <button class="btn small ghost" onclick="toggleHandoff()">지시문 보기</button>
      <button class="btn small ghost" onclick="copyHandoff()">📋 복사</button>
    </div>
    <span class="hint" id="handoffCopied"></span>
    <pre class="hh-msg" id="handoffMsg" style="display:none"></pre>
  </div>`;
}

// 지시문을 서버에서 받아 채운다 (없으면 빈 상태).
async function loadHandoffMsg() {
  const el = $("handoffMsg"); if (!el || !PID) return "";
  if (el.dataset.loaded === PID) return el.textContent;
  try {
    const d = await postJSON("/api/claude/message", { pid: PID });
    el.textContent = d.message || "";
    el.dataset.loaded = PID;
    return el.textContent;
  } catch (e) { return ""; }
}

window.toggleHandoff = async () => {
  const el = $("handoffMsg"); if (!el) return;
  await loadHandoffMsg();
  el.style.display = el.style.display === "none" ? "" : "none";
};

window.launchClaude = async (btn) => {
  const c = $("handoffCopied");
  if (btn) { btn.disabled = true; btn.textContent = "▶ Claude 여는 중…"; }
  try {
    const d = await postJSON("/api/claude/launch", { pid: PID });
    const el = $("handoffMsg");
    if (el) { el.textContent = d.message || ""; el.dataset.loaded = PID; }
    if (c) c.innerHTML = `<span style="color:var(--good)">새 창에서 Claude 가 열렸습니다 — 그 창에서 대화하세요.</span>`;
  } catch (e) {
    if (c) c.innerHTML = `<span style="color:var(--bad)">실행 실패: ${escapeHtml(e.message)}</span>`;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "▶ Claude 실행 (지시문 자동 입력)"; }
  }
};

window.copyHandoff = async () => {
  const txt = await loadHandoffMsg();
  const c = $("handoffCopied");
  try { await navigator.clipboard.writeText(txt); if (c) c.textContent = "복사됨 ✓"; }
  catch (e) { if (c) c.textContent = "복사 실패 — '지시문 보기'로 직접 선택하세요"; }
};



const FLOW_GROUPS = [
  { k: "준비", ids: ["env", "topic", "anchor", "assets"] },
  { k: "제작", ids: ["make", "blender"] },
  { k: "배치", ids: ["ue_import", "place", "lighting"] },
  { k: "완료", ids: ["export"] },
];
function renderFlowList() {
  const box = $("flowList");
  box.innerHTML = "";
  const renderStep = (s) => {
    const i = FLOW.steps.indexOf(s);
    const st = (STATE && STATE.steps[s.id]) || { status: "locked", gate: s.gate };
    const div = document.createElement("div");
    div.className = "step-item " + st.status +
      (s.id === SELECTED ? " on" : "") +
      (s.gate ? " gate" : "") +
      (st.status === "done" ? " done" : "") +
      (st.status === "locked" ? " locked" : "");
    const gateBadge = s.gate ? `<span class="badge gate">🔒</span>` : "";
    const stBadge =
      st.status === "done" ? `<span class="badge done">완료</span>` :
      st.status === "awaiting_user" ? `<span class="badge gate">확정대기</span>` : "";
    div.innerHTML =
      `<div class="num">${i + 1}</div>
       <div><div class="t">${escapeHtml(s.title)} ${gateBadge}${stBadge}</div></div>`;
    div.onclick = () => { SELECTED = s.id; renderCenter(); renderFlowList(); };
    box.appendChild(div);
  };
  const used = new Set();
  for (const g of FLOW_GROUPS) {
    const steps = g.ids.map((id) => FLOW.steps.find((s) => s.id === id)).filter(Boolean);
    if (!steps.length) continue;
    const hd = document.createElement("div");
    hd.className = "flow-group";
    hd.textContent = g.k;
    box.appendChild(hd);
    steps.forEach((s) => { used.add(s.id); renderStep(s); });
  }
  FLOW.steps.filter((s) => !used.has(s.id)).forEach(renderStep);  // 그룹 밖 스텝 안전 처리
}

// 상단 산출-흐름 미니 스트립: 에셋이 어떻게 만들어져 검증되는지 한눈에
const PIPE_CHIPS = [
  { k: "준비" }, { k: "이미지", ic: "🖼" }, { k: "3D", ic: "🧊" },
  { k: "검수", ic: "🔍", gate: true }, { k: "배치", ic: "🏙", gate: true },
  { k: "조명", ic: "💡", gate: true }, { k: "export", ic: "📦" },
];
const PIPE_MAP = {  // step id → [현재 시작칩, 끝칩]
  env: [0, 0], topic: [0, 0], anchor: [0, 0], assets: [0, 0],
  make: [1, 3], ue_import: [4, 4], place: [4, 4], lighting: [5, 5], export: [6, 6],
};
function pipelineStrip(stepId) {
  const [cs, ce] = PIPE_MAP[stepId] || [0, 0];
  let h = `<div class="pipe" title="에셋 제작→검증 흐름">`;
  PIPE_CHIPS.forEach((c, idx) => {
    const st = idx < cs ? "done" : (idx >= cs && idx <= ce ? "cur" : "future");
    h += `<span class="pipe-chip ${st}">${c.ic ? c.ic + " " : ""}${c.k}${c.gate ? " 🔒" : ""}</span>`;
    if (idx < PIPE_CHIPS.length - 1) h += `<span class="pipe-sep">→</span>`;
  });
  return h + `</div>`;
}

function renderCenter() {
  const empty = $("centerEmpty"), detail = $("stepDetail");
  if (!STATE) { empty.style.display = ""; detail.style.display = "none"; return; }
  empty.style.display = "none"; detail.style.display = "";
  const s = stepDef(SELECTED) || FLOW.steps[0];
  const st = STATE.steps[s.id] || {};
  const locked = st.status === "locked";

  let html = pipelineStrip(s.id) + `<div class="card"><h3>${escapeHtml(s.title)}</h3>
    <p class="desc">${escapeHtml(s.desc || "")}</p>`;

  if (locked) {
    html += `<div class="locknote">🔒 이전 게이트가 통과되지 않아 잠겨 있습니다. 앞 단계를 먼저 확정하세요.</div>`;
  }

  // 진단 단계 (환경·도구 체크)
  if (s.diagnostic && !locked) {
    html += renderDiagnosticBlock();
  }

  // 단계 도움말 (빈 종이 막막함 완화)
  if (s.help && !locked) {
    html += `<div class="step-help">💡 ${escapeHtml(s.help)}</div>`;
  }

  // 제작 단계(Claude+MCP가 실행) — 웹은 준비만
  if (CLAUDE_STEPS.has(s.id) && !locked) {
    html += claudeHandoff();
  }

  // 입력 필드
  const inputs = s.inputs || [];
  const PH = { topic: "예: 조선 저잣거리 / 눈 내리는 산사", background: "예: 노을 질 무렵, 따뜻한 톤 / 비 내리는 밤" };
  if (inputs.length) {
    html += `<div style="margin-top:8px">`;
    for (const f of inputs) {
      const val = (STATE.inputs && STATE.inputs[f] != null) ? STATE.inputs[f] : "";
      if (f === "asset_list") {
        html += renderAssetList(val, locked);
      } else if (f === "anchor") {
        html += `<div id="anchorWrap">${anchorChooser(locked)}</div>`;
      } else if (f === "lighting") {
        html += lightingChooser(locked);
      } else {
        const isLong = f === "background";
        const ph = PH[f] || "여기에 직접 입력…";
        html += `<div class="field"><label>${labelFor(f)}</label>` +
          (isLong
            ? `<textarea data-field="${f}" ${locked ? "disabled" : ""} placeholder="${escapeAttr(ph)}">${escapeHtml(String(val))}</textarea>`
            : `<input data-field="${f}" ${locked ? "disabled" : ""} placeholder="${escapeAttr(ph)}" value="${escapeAttr(String(val))}">`) +
          `</div>`;
      }
    }
    // 아이디어 예시: 기본 접힘 (막힐 때만 펼침 — 산만함 방지)
    if (s.ideas && !locked) {
      let panel = "";
      for (const f of Object.keys(s.ideas)) {
        const chips = (s.ideas[f] || []).map((t) => `<button class="idea-chip" onclick="appendIdea('${f}','${escapeAttr(t)}')">+ ${escapeHtml(t)}</button>`).join("");
        panel += `<div class="idea-row"><span class="idea-lbl">${labelFor(f)}</span><div class="idea-chips">${chips}</div></div>`;
      }
      html += `<button type="button" class="ideas-toggle" onclick="toggleIdeas(this)">💡 아이디어 예시 ▾</button>
        <div id="ideasPanel" style="display:none">${panel}</div>`;
    }
    html += `</div>`;
  }

  // 에셋 단계: AI 제안 (추상적인 빈 목록 → 제안받아 골라 담기)
  if (s.id === "assets" && !locked) {
    html += `<button type="button" class="btn small ghost" onclick="suggestAssets()" style="margin-top:6px">🔄 추천 다시 받기</button>
      <div id="assetSuggest" style="margin-top:8px"></div>`;
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
  // 에셋 단계 진입 시: 캐시 있으면 그리고, 없으면 자동 추천
  if (s.id === "assets" && !locked) {
    // ★ 2단계를 고치고 다시 확정했으면 옛 추천은 근거가 달라진 것이다 → 새로 받는다.
    if (ASSET_SUGGESTIONS && suggestBasisStale()) ASSET_SUGGESTIONS = null;
    if (ASSET_SUGGESTIONS) paintAssetSuggest();
    else if ((STATE.inputs || {}).topic) setTimeout(() => suggestAssets(), 0);
  }
}

// 강도 스펙트럼 4단계 (은은/중간/뚜렷/하이) — 카드로 골라 앵커 확정
const ANCHOR_LEVELS = [
  { name: "은은", desc: "낮은 대비·뮤트 색·부드러운 빛. 잔잔하고 은은." },
  { name: "중간", desc: "자연스러운 사실적 톤. 보통 대비·채도." },
  { name: "뚜렷", desc: "선명·또렷. 높은 대비, 진한 색, 분명한 그림자." },
  { name: "하이", desc: "강렬한 하이톤. 과장된 대비·채도, 극적 조명·발광." },
];
// 조명·시간대 선택 — 값 표는 web/lighting.json (서버가 /api/lighting 로 준다).
// ★ 노을은 여러 프리셋 중 하나일 뿐이다. 고르지 않으면 조명을 건드리지 않는다.
function lightingPresets() {
  const ps = (LIGHTING && LIGHTING.presets) || [];
  if (ps.length) return ps;
  return [{ id: "none", label: "손대지 않음", desc: "조명을 건드리지 않는다." }];  // lighting.json 없을 때 최소 동작
}
function lightingChooser(locked) {
  const cur = (STATE.inputs && STATE.inputs.lighting) || "";
  let h = `<div class="field"><label>${labelFor("lighting")} — 하나 선택</label>`;
  h += `<div class="hint" style="margin-bottom:6px">배치가 끝난 씬에 어떤 빛을 넣을지 고릅니다.
        <b>노을은 기본값이 아니라 선택지 중 하나</b>이며, 고른 것만 적용됩니다.</div>`;
  h += `<div class="anchor-grid">`;
  for (const pr of lightingPresets()) {
    const on = cur === pr.id;
    h += `<button class="anchor-card ${on ? "on" : ""}" data-name="${escapeAttr(pr.id)}" ${locked ? "disabled" : ""} onclick="setLighting('${escapeAttr(pr.id)}')">
      <div class="ac-name">${on ? "● " : ""}${escapeHtml(pr.label || pr.id)}${pr.measured ? " <span class='hint'>실측</span>" : ""}</div>
      <div class="ac-desc">${escapeHtml(pr.desc || "")}</div>
      ${pr.warn ? `<div class="ac-desc" style="color:var(--warn);margin-top:4px">⚠ ${escapeHtml(pr.warn)}</div>` : ""}
    </button>`;
  }
  h += `</div>`;
  const sel = lightingPresets().find((x) => x.id === cur);
  if (sel && sel.sun) {
    const su = sel.sun;
    h += `<div class="hint" style="margin-top:8px">적용값 — 태양 pitch ${su.pitch} · yaw ${su.yaw} · 세기 ${su.intensity} · 색온도 ${su.temperature}K
      ${sel.fog ? "· 안개 조정 있음" : "· 안개 미조정"} / 기본 SkyLight 미개입(하드룰)</div>`;
  } else if (sel) {
    h += `<div class="hint" style="margin-top:8px">조명을 건드리지 않습니다 — 레벨에 있던 조명이 그대로 남습니다.</div>`;
  }
  h += `<div class="hint" style="margin-top:6px">적용 명령: <code>py -u scripts/apply_lighting.py --project ${escapeHtml(PID || "<프로젝트id>")}</code></div>`;
  return h + `</div>`;
}
window.setLighting = async (id) => {
  STATE = await postJSON(`/api/projects/${PID}/input`, { field: "lighting", value: id });
  renderCenter(); renderFlowList(); updateGateButtons();
};

let ANCHOR_DESC = {};   // AI가 주제 맞춤 설명을 채우면 override
// 배경(참고) 이미지 — 한 장만. 큰 상자를 눌러 고르거나 파일을 끌어다 놓는다.
function refImageBox(refs) {
  const bg = refs[0];
  let inner;
  if (bg) {
    inner = `<div class="dz-single">
      <img src="data:image/${bg.ext === "jpg" ? "jpeg" : bg.ext};base64,${bg.b64}" alt="${escapeAttr(bg.name)}">
      <button class="btn small ghost dz-del" title="지우기" onclick="deleteRefImage()">✕</button>
      <div class="dz-cap">${escapeHtml(bg.name)}</div>
    </div>
    <div class="dz-more">다른 이미지를 넣으면 이 배경을 <b>교체</b>합니다 (상자 클릭 또는 끌어다 놓기)</div>`;
  } else {
    inner = `<div class="dz-hint">
      <span class="dz-big">🖼</span>
      <span class="dz-main">배경 이미지를 여기에 끌어다 놓으세요</span>
      <div class="dz-sub">또는 상자를 눌러 파일 선택 · PNG / JPG / WEBP · 한 장</div>
    </div>`;
  }
  return `<div class="field" style="margin-top:10px">
    <label>배경 참고 이미지 (1장)</label>
    <div class="hint" style="margin-bottom:2px">
      이 그림을 기준으로 에셋을 리스트업하고 배치합니다. 화면에 합성되지는 않습니다.
      파일은 프로젝트 폴더에 저장됩니다.
    </div>
    <div class="dropzone" id="refDrop"
         onclick="refDropClick(event)"
         ondragover="refDragOver(event)" ondragleave="refDragLeave(event)" ondrop="refDropFiles(event)">
      ${inner}
    </div>
    <input type="file" id="refFile" accept="image/png,image/jpeg,image/webp"
           style="display:none" onchange="uploadRefImages(this.files); this.value='';">
    <div class="hint" id="refHint" style="margin-top:4px"></div>
  </div>`;
}

// 상자 안의 카드·삭제버튼을 눌렀을 땐 파일 선택창을 열지 않는다.
window.refDropClick = (e) => {
  if (e.target.closest("button.btn")) return;   // 지우기 버튼을 눌렀을 땐 파일창을 열지 않는다
  const f = $("refFile"); if (f) f.click();
};
window.refDragOver = (e) => { e.preventDefault(); const d = $("refDrop"); if (d) d.classList.add("over"); };
window.refDragLeave = (e) => { const d = $("refDrop"); if (d) d.classList.remove("over"); };
window.refDropFiles = (e) => {
  e.preventDefault();
  const d = $("refDrop"); if (d) d.classList.remove("over");
  const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
  uploadRefImages(files);
};

// 원본 그대로 올리면 state.json 이 수십 MB 로 붓는다 → 브라우저에서 먼저 줄인다.
function shrinkImage(file, maxSide) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onerror = () => reject(new Error("파일을 읽지 못했습니다"));
    fr.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("이미지 형식을 읽지 못했습니다"));
      img.onload = () => {
        const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
        const w = Math.round(img.width * scale), hgt = Math.round(img.height * scale);
        const cv = document.createElement("canvas");
        cv.width = w; cv.height = hgt;
        cv.getContext("2d").drawImage(img, 0, 0, w, hgt);
        resolve(cv.toDataURL("image/png").split(",")[1]);
      };
      img.src = fr.result;
    };
    fr.readAsDataURL(file);
  });
}

window.uploadRefImages = async (fileList) => {
  // 배경은 한 장뿐 — 여러 개를 떨궈도 첫 장만 받는다.
  const files = Array.from(fileList || []).filter((f) => /^image\//.test(f.type)).slice(0, 1);
  const hint = $("refHint"), zone = $("refDrop");
  if (!files.length) {
    if (hint) hint.innerHTML = `<span style="color:var(--warn)">이미지 파일만 넣을 수 있습니다.</span>`;
    return;
  }
  if (zone) zone.classList.add("busy");
  try {
    const f = files[0];
    if (hint) hint.textContent = `${f.name} 처리 중…`;
    const b64 = await shrinkImage(f, 1024);
    const name = f.name.replace(/\.[^.]+$/, "");
    STATE = await postJSON(`/api/projects/${PID}/ref-image`, { b64, ext: "png", name });
    if (hint) hint.textContent = "";
    renderCenter(); renderFlowList(); updateGateButtons();
  } catch (e) {
    if (hint) hint.innerHTML = `<span style="color:var(--bad)">실패: ${escapeHtml(e.message)}</span>`;
  } finally {
    if (zone) zone.classList.remove("busy");
  }
};

window.deleteRefImage = async () => {
  if (!confirm("배경 참고 이미지를 지웁니다. 앵커 확정도 함께 풀립니다. 계속할까요?")) return;
  STATE = await postJSON(`/api/projects/${PID}/ref-image-delete`, {});
  renderCenter(); renderFlowList(); updateGateButtons();
};

function anchorChooser(locked) {
  const refs = STATE.ref_images || [];
  const mode = anchorMode();
  let h = `<div class="field"><label>참고 이미지 — 어떻게 정할까요?</label>`;
  h += `<div class="hint" style="margin-bottom:6px">이후 모든 에셋이 여기서 정한 그림·기준을 따릅니다.</div>`;

  // 두 갈래 중 하나만 고른다. 둘을 한 화면에 늘어놓으면 무엇을 해야 하는지가 흐려진다.
  h += `<div class="anchor-grid">
    <button class="anchor-card ${mode === "upload" ? "on" : ""}" ${locked ? "disabled" : ""}
            onclick="setAnchorMode('upload')">
      <div class="ac-name">${mode === "upload" ? "● " : ""}📁 참고 이미지 넣기</div>
      <div class="ac-desc">이미 원하는 배경 그림이 있을 때. 한 장 넣으면 바로 기준이 됩니다.</div>
    </button>
    <button class="anchor-card ${mode === "generate" ? "on" : ""}" ${locked ? "disabled" : ""}
            onclick="setAnchorMode('generate')">
      <div class="ac-name">${mode === "generate" ? "● " : ""}🖼 참고 이미지 생성</div>
      <div class="ac-desc">주제·배경으로 강도 4단계(은은/중간/뚜렷/하이)를 뽑아 하나 고릅니다.</div>
    </button>
  </div>`;

  if (!mode) {
    h += `<div class="hint" style="margin-top:8px">위에서 하나를 고르세요.</div>`;
    return h + `</div>`;
  }
  h += mode === "upload" ? anchorUploadPane(locked, refs) : anchorGeneratePane(locked);
  return h + `</div>`;
}

// 저장된 선택이 없으면 현재 상태로 추측한다 — 이미 넣었/뽑았으면 그 갈래를 편다.
function anchorMode() {
  const m = (STATE.inputs || {}).anchor_mode;
  if (m === "upload" || m === "generate") return m;
  if ((STATE.ref_images || []).length) return "upload";
  if (STATE.spectrum && (STATE.spectrum.images || []).length) return "generate";
  return "";
}

window.setAnchorMode = async (m) => {
  STATE = await postJSON(`/api/projects/${PID}/input`, { field: "anchor_mode", value: m });
  const el = $("anchorWrap"); if (el) el.innerHTML = anchorChooser(false);
  renderFlowList(); updateGateButtons();
};

function anchorUploadPane(locked, refs) {
  // 안내는 드롭존 안에 이미 있다 — 밖에 또 쓰면 같은 말이 두 번 보인다.
  return refImageBox(refs);
}

function anchorGeneratePane(locked) {
  const cur = (STATE.inputs && STATE.inputs.anchor) || "";
  let h = `<div class="hint" style="margin:10px 0 6px">이 장면을 어느 "강도"로 만들지 고르세요.</div>`;
  h += `<div class="anchor-grid">`;
  for (const lv of ANCHOR_LEVELS) {
    const on = cur === lv.name;
    const desc = ANCHOR_DESC[lv.name] || lv.desc;
    h += `<button class="anchor-card ${on ? "on" : ""}" data-name="${lv.name}" ${locked ? "disabled" : ""} onclick="setAnchor('${lv.name}')">
      <div class="ac-name">${on ? "● " : ""}${lv.name}</div>
      <div class="ac-desc">${escapeHtml(desc)}</div>
    </button>`;
  }
  h += `</div>`;
  if (!locked) {
    h += `<div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
      <button type="button" class="btn small" onclick="genSpectrum(this)">🖼 강도별 4장 이미지 생성</button>
      <button type="button" class="btn small ghost" id="specCancelBtn" style="display:none" onclick="cancelSpectrum(this)">■ 생성 취소</button>
      <button type="button" class="btn small ghost" onclick="suggestAnchor(this)">🤖 설명만 생성</button>
    </div>
    <div id="spectrumImgs" class="spectrum-grid">${savedSpectrumHtml()}</div>`;
  }
  return h;
}

window.setAnchor = async (name) => {
  STATE = await postJSON(`/api/projects/${PID}/input`, { field: "anchor", value: name });
  // 제자리 선택 갱신 (생성된 이미지 유지)
  // [data-name] 이 있는 카드만 — 모드 선택 카드(넣기/생성)는 data-name 이 없어 여기서 건드리면 안 된다.
  document.querySelectorAll(".anchor-card[data-name]").forEach((el) => el.classList.toggle("on", el.dataset.name === name));
  document.querySelectorAll(".spec-card").forEach((el) => el.classList.toggle("on", el.dataset.name === name));
  renderFlowList(); updateGateButtons();
};
// state에 저장된 스펙트럼 이미지 (새로고침·확정취소해도 유지)
function savedSpectrumHtml() {
  const sp = STATE.spectrum;
  if (!sp || !sp.images || !sp.images.length) return "";
  const cur = (STATE.inputs || {}).anchor || "";
  return sp.images.map((im) =>
    `<button class="spec-card ${cur === im.name ? "on" : ""}" data-name="${im.name}" onclick="setAnchor('${im.name}')">
      <img src="data:image/png;base64,${im.b64}" alt="${escapeAttr(im.name)}">
      <span class="spec-name">${escapeHtml(im.name)}</span>
    </button>`).join("");
}
function renderSpecImages(images) {
  const box = $("spectrumImgs"); if (!box) return;
  const cur = (STATE.inputs || {}).anchor || "";
  box.innerHTML = (images || []).map((im) =>
    `<button class="spec-card ${cur === im.name ? "on" : ""}" data-name="${im.name}" onclick="setAnchor('${im.name}')">
      <img src="data:image/png;base64,${im.b64}" alt="${escapeAttr(im.name)}">
      <span class="spec-name">${escapeHtml(im.name)}</span>
    </button>`).join("");
}
// ★ 입력은 onchange(포커스 잃을 때)에 비동기로 저장된다. 타이핑 직후 생성 버튼을 누르면
//   저장 POST가 끝나기 전에 STATE.inputs 를 읽어 **옛 글로 생성**된다(실측).
//   생성 계열 동작 전에 화면의 실제 값을 먼저 밀어 넣는다.
async function flushInputs() {
  const els = Array.from(document.querySelectorAll("[data-field]"));
  for (const el of els) {
    const f = el.getAttribute("data-field");
    if (!f) continue;
    const cur = (STATE.inputs || {})[f];
    const v = el.value;
    if (String(cur == null ? "" : cur) !== String(v)) {
      STATE = await postJSON(`/api/projects/${PID}/input`, { field: f, value: v });
    }
  }
}

window.genSpectrum = async (btn) => {
  await flushInputs();              // 방금 친 주제·배경이 반영되도록
  const inp = STATE.inputs || {};
  const ec = STATE.engine_choices || {};
  const box = $("spectrumImgs");
  const engine = ec.image || "";
  const repo = ec.image_repo || "";
  const isCloud = /gpt-image/i.test(engine);
  if (!isCloud) {
    if (!repo) {
      if (box) box.innerHTML = `<span class="hint" style="color:var(--warn)">로컬 모델을 먼저 선택하세요 (2단계 이미지 엔진 → 모델).</span>`;
      return;
    }
    // 로컬 생성은 모델이 이미 다운로드돼 있어야 함
    if (MODEL_PRESENT[repo] === undefined) { if (box) box.innerHTML = `<span class="hint">모델 확인 중…</span>`; await checkPresence(repo); }
    if (MODEL_PRESENT[repo] !== true) {
      if (box) box.innerHTML = `<div class="hint" style="color:var(--warn)">이 모델(<b>${escapeHtml(repo)}</b>)이 아직 다운로드되지 않았습니다.<br>
        → <b>2단계(이미지 엔진)</b>에서 이 모델을 <b>'이 모델 설치'</b>로 먼저 받으세요.<br>
        (게이트 모델이면 그 화면에서 <b>HF 로그인 + 라이선스 동의</b> 후 설치)<br>
        <b>팁:</b> 로그인 없이 바로 되는 건 <code>black-forest-labs/FLUX.1-schnell</code>(비게이트).</div>`;
      return;
    }
  }
  if (btn) { btn.disabled = true; btn.textContent = "🖼 생성 중…"; }
  const cancelBtn = $("specCancelBtn");
  if (cancelBtn) { cancelBtn.style.display = ""; cancelBtn.disabled = false; cancelBtn.textContent = "■ 생성 취소"; }
  if (box) box.innerHTML = `<span class="hint">${isCloud ? "gpt-image로 생성 중…" : "로컬(" + escapeHtml(repo) + ")로 생성 중… 모델 로딩 포함, 몇 분 걸릴 수 있어요"}</span><pre id="specLog" class="inst-log" style="display:block"></pre>`;
  try {
    const s = await postJSON("/api/spectrum", { topic: inp.topic || "", background: inp.background || "", engine, repo, pid: PID });
    if (s.error) throw new Error(s.error);
    // 폴링
    while (true) {
      await sleep(1800);
      let st;
      try { st = await api("/api/spectrum/status"); } catch (e) { continue; }
      const lg = $("specLog"); if (lg) { lg.textContent = (st.log || []).join("\n"); lg.scrollTop = lg.scrollHeight; }
      if (!st.running) {
        if (st.images) { renderSpecImages(st.images); }
        else if (st.cancelled) {
          if (box) box.innerHTML = `<span class="hint">생성을 취소했습니다.</span>`;
        }
        else if (box) box.innerHTML = `<span class="hint" style="color:var(--bad)">생성 실패: ${escapeHtml(st.error || "")}</span>`;
        break;
      }
    }
  } catch (e) {
    if (box) box.innerHTML = `<span class="hint" style="color:var(--bad)">생성 실패: ${escapeHtml(e.message)}</span>`;
  }
  if (btn) { btn.disabled = false; btn.textContent = "🖼 다시 생성"; }
  const cb = $("specCancelBtn"); if (cb) cb.style.display = "none";
};
// 생성 취소 — 서버가 다음 스텝에서 스스로 빠져나온다 (강제 종료 아님)
window.cancelSpectrum = async (btn) => {
  if (btn) { btn.disabled = true; btn.textContent = "■ 취소 중…"; }
  try { await postJSON("/api/spectrum/cancel", {}); }
  catch (e) { if (btn) { btn.disabled = false; btn.textContent = "■ 생성 취소"; } }
};
window.suggestAnchor = async (btn) => {
  await flushInputs();
  const inp = STATE.inputs || {};
  if (btn) { btn.disabled = true; btn.textContent = "🤖 생성 중…"; }
  try {
    const d = await postJSON("/api/suggest-anchor", { topic: inp.topic || "", background: inp.background || "" });
    if (d.levels) { for (const lv of d.levels) ANCHOR_DESC[lv.name] = lv.desc; }
    const el = $("anchorWrap"); if (el) el.innerHTML = anchorChooser(false);
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = "🤖 이 주제에 맞춰 설명 생성 (실패, 재시도)"; }
  }
};

function assetTagsHtml() {
  const arr = (STATE.inputs && STATE.inputs.asset_list) || [];
  if (!arr.length) return `<span class="hint">아직 없음 — 아래 'AI로 제안'으로 담거나 직접 추가</span>`;
  return arr.map((a, i) => `<span class="chip">${escapeHtml(a)} <b onclick="removeAsset(${i})">✕</b></span>`).join("");
}
function refreshAssetTags() {
  const el = $("assetTags"); if (el) el.innerHTML = assetTagsHtml();
  updateGateButtons();
}
function renderAssetList(val, locked) {
  return `<div class="field"><label>${labelFor("asset_list")} <span class="hint" id="assetCount"></span></label>
    <div style="display:flex;gap:6px">
      <input id="assetInput" ${locked ? "disabled" : ""} placeholder="직접 추가 후 Enter" style="flex:1">
      <button class="btn small" ${locked ? "disabled" : ""} onclick="addAsset()">추가</button>
    </div>
    <div class="tag-list" id="assetTags">${assetTagsHtml()}</div>
  </div>`;
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
    ${envFlowLine()}
    <div class="hint" style="margin:8px 0">아래 <b>1~4단계</b>를 위에서 아래로 확인/선택하면 됩니다. <b>진단 시작</b>으로 상태를 점검하세요.</div>
    <button class="btn small" id="diagBtn" onclick="runDiagnose()">진단 시작</button>
    <span id="diagStatus" class="hint" style="margin-left:8px"></span>
    <div id="diagResult" style="margin-top:10px"></div>
  </div>`;
  // 진입 즉시: 이미 진단했으면 결과, 아니면 체크리스트(미확인)를 먼저 리스트업
  setTimeout(() => { if (DIAG) paintDiag(DIAG); else loadDiagSpec(); }, 0);
  return h;
}

// 이 화면에서 유저가 할 순서 (user flow)를 한 줄로 그림
function envFlowLine() {
  const steps = [
    { t: "진단", done: DIAG_DONE },
    { t: "이미지 엔진", done: imageEngineReady() },
    { t: "3D 엔진", done: meshEngineReady() },
    { t: "확정", done: false },
  ];
  return `<div class="env-flow" id="envFlow">` + steps.map((s, i) =>
    `<span class="ef ${s.done ? "done" : ""}">${s.done ? "✓" : (i + 1)} ${s.t}</span>`
  ).join(`<span class="ef-sep">→</span>`) + `</div>`;
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
  // 현재 엔진 선택에 관련된 필수 항목만 집계
  const miss = (d.items || []).filter((i) => i.required && itemRelevant(i.dep) && !i.ok).map((i) => i.name);
  stat.innerHTML = miss.length
    ? `<span style="color:var(--warn)">핵심 확인필요: ${escapeHtml(miss.join(", "))}</span>`
    : `<span style="color:var(--good)">핵심 준비됨 ✅</span>`;
  res.innerHTML = diagSummary(d) + buildDiagStages(d, false);
}

function specSummary(items) {
  const req = items.filter((i) => i.required).length;
  return `<div class="diag-summary">
    <div class="cell"><div class="lb">핵심 ★</div><div class="big" style="color:var(--gate)">${req}</div></div>
    <div class="cell"><div class="lb">전체</div><div class="big">${items.length}</div></div>
    <div class="diag-bar"><span style="transform:scaleX(0)"></span></div>
    <div class="diag-note">미진단 — '진단 시작'을 누르세요</div>
  </div>`;
}

function diagSummary(d) {
  const items = (d.items || []).filter((i) => itemRelevant(i.dep));   // 선택에 관련된 것만
  const req = items.filter((i) => i.required);
  const reqOk = req.filter((i) => i.ok).length;
  const allOk = items.filter((i) => i.ok).length;
  const pct = items.length ? Math.round(allOk / items.length * 100) : 0;
  const reqDone = reqOk === req.length;
  return `<div class="diag-summary">
    <div class="cell"><div class="lb">핵심 ★ 준비</div><div class="big" style="color:${reqDone ? 'var(--good)' : 'var(--bad)'}">${reqOk}/${req.length}</div></div>
    <div class="cell"><div class="lb">전체 준비</div><div class="big">${allOk}/${items.length}</div></div>
    <div class="diag-bar"><span style="transform:scaleX(${pct / 100})"></span></div>
    <div class="diag-note">${reqDone ? '<span style="color:var(--good)">핵심 준비 완료 — 확정 가능</span>' : '핵심 항목을 채우세요'}</div>
  </div>`;
}

function buildDiagStages(data, pending) {
  window._diagData = data;   // openGuide 가 참조
  const stages = data.stages || [];
  const items = data.items || [];
  const byStage = {};
  items.forEach((i) => { (byStage[i.stage] = byStage[i.stage] || []).push(i); });
  const shown = stages.filter((s) => (byStage[s.key] || []).length);

  // 한 단계 카드 HTML.
  const card = (s, oi) => {
    const list = byStage[s.key] || [];
    let badge = `<span class="stage-count">—</span>`, cardCls = "";
    if (!pending) {
      const rel = list.filter((i) => itemRelevant(i.dep));   // 선택에 관련된 항목만 집계
      const ok = rel.filter((i) => i.ok).length;
      const reqMiss = rel.some((i) => i.required && !i.ok);
      badge = `<span class="stage-count ${reqMiss ? "bad" : (ok === rel.length ? "good" : "")}">${ok}/${rel.length}</span>`;
      cardCls = reqMiss ? "stage-bad" : (ok === rel.length ? "stage-good" : "");
    }
    const stepTitle = s.action || s.label;
    // 완료(관련 항목 전부 OK)된 단계는 기본 접힘 — 특히 기반 설치
    let fullyOk = false;
    if (!pending) {
      const rel = list.filter((i) => itemRelevant(i.dep));
      fullyOk = rel.length > 0 && rel.every((i) => i.ok);
    }
    const collapsed = !pending && stageCollapsed(s.key, fullyOk);
    (window._stageState = window._stageState || {})[s.key] = collapsed;  // 토글이 참조
    let h = `<div class="diag-stage ${cardCls} ${collapsed ? "collapsed" : ""}">`
      + `<div class="diag-stage-h" onclick="toggleStage('${s.key}')"><span class="fold">${collapsed ? "▸" : "▾"}</span>`
      + `<span class="stage-step">${oi + 1}단계</span> ${escapeHtml(stepTitle)} ${badge}</div>`
      + `<div class="stage-body">`
      + (s.todo ? `<div class="stage-todo">할 일 · ${escapeHtml(s.todo)}</div>` : "");
    for (const i of list) {
      const rel = pending ? true : itemRelevant(i.dep);
      const st = pending ? "pending" : (!rel ? "irrelevant" : (i.ok ? "ok" : (i.required ? "req" : "warn")));
      const icon = st === "ok" ? "✓" : st === "req" ? "✕" : st === "warn" ? "!" : st === "irrelevant" ? "–" : "";
      const detail = !rel ? "현재 엔진 선택엔 불필요" : (pending ? (i.need || "") : (i.detail || ""));
      let tail = "";
      if (!pending && rel && !i.ok) {
        if (i.runtime) {
          tail = `<span class="later-tag" title="에디터를 열면 자동으로 확인됩니다">나중에 확인</span>`;
        } else if (i.guide) {
          const lbl = AUTO_INSTALL.has(i.name) ? "설치" : "설치법";
          tail = `<button class="btn small guide-btn" onclick="openGuide('${escapeAttr(i.name)}')">${lbl}</button>`;
        }
      }
      h += `<div class="diag-row ${st}" title="${escapeAttr(detail)}"><div class="box">${icon}</div><div class="grow"><div class="nm">${escapeHtml(i.name)}${(i.required && rel) ? '<span class="diag-star">★</span>' : ''}</div><div class="nd">${escapeHtml(detail)}</div></div>${tail}</div>`;
    }
    if (s.key === "image" && !pending) h += `<div id="imgChooserWrap">${imageChooser()}</div>`;
    if (s.key === "mesh" && !pending) h += `<div id="meshChooserWrap">${meshChooser()}</div>`;
    return h + `</div></div>`;   // stage-body + diag-stage 닫기
  };

  // 차분한 세로 스택: 1→2→3→4 위에서 아래로, 단계 사이 ↓
  let h = `<div class="diag-stack">`;
  shown.forEach((s, oi) => {
    if (oi > 0) h += `<div class="stack-arrow">↓</div>`;
    h += card(s, oi);
  });
  return h + `</div>`;
}

// 이미지 엔진 선택 + 로컬 모델(프리셋/커스텀) 설치
const FLUX_PRESETS = [
  "black-forest-labs/FLUX.1-schnell",
  "black-forest-labs/FLUX.1-dev",
  "black-forest-labs/FLUX.2-dev",
];
// 이 PC(GPU) 기준 배너 — 모델 판정의 근거를 보여줌
function gpuBanner() {
  const g = MODELS._gpu;
  if (!g) return "";
  if (!g.has_gpu)
    return `<div class="gpu-banner nogpu">⚠ GPU 미감지 — CPU만으로는 로컬 생성이 매우 느립니다. 아래 판정은 참고치입니다.</div>`;
  return `<div class="gpu-banner">🖥 이 PC: <b>${escapeHtml(g.gpu || "GPU")}</b> · VRAM <b>${g.vram_total_gb}GB</b> (가용 ${g.vram_free_gb}GB)
    <span class="gb-legend"><span class="v-rec">추천</span> 직접·빠름 · <span class="v-ok">가능</span> 오프로드·느림 · <span class="v-risk">위험</span> OOM 튕김 가능 · <span class="v-no">불가</span></span></div>`;
}
// 태그 렌더 — verdict가 있으면 첫 태그(판정)를 색상 강조
function mtagsHtml(m) {
  const vc = { rec: "v-rec", ok: "v-ok", risk: "v-risk", no: "v-no" }[m.verdict];
  return (m.tags || []).map((t, i) =>
    `<span class="mtag${i === 0 && vc ? " " + vc : ""}">${escapeHtml(t)}</span>`).join("");
}

function imageChooser() {
  const choices = (ENGINES.roles && ENGINES.roles.image && ENGINES.roles.image.choices) || [];
  const cur = (STATE.engine_choices || {}).image || "";
  const repo = (STATE.engine_choices || {}).image_repo || "";
  let h = `<div class="img-choose"><div class="ic-h">이미지 엔진 — 하나를 눌러 확정</div>`;
  for (const c of choices) {
    const needKey = /gpt-image/i.test(c);
    const on = c === cur;
    h += `<button class="img-opt ${on ? "on" : ""}" onclick="chooseImageEngine('${escapeAttr(c)}')">
      <span class="io-dot">${on ? "●" : "○"}</span><span class="io-name">${escapeHtml(c)}</span>${needKey ? '<span class="io-tag key">🔑 키필요</span>' : '<span class="io-tag local">로컬</span>'}</button>`;
  }

  // 로컬 엔진: 카탈로그에서 모델 선택(hover 설명) + 직접입력
  if (cur && !/gpt-image/i.test(cur)) {
    h += `<div class="model-pick">`;
    h += gpuBanner();
    if (MODELS.image_guide) h += `<div class="step-help" style="margin:2px 0 8px">${escapeHtml(MODELS.image_guide)}</div>`;
    h += `<div class="hint" style="margin-bottom:6px">모델 선택 (마우스를 올리면 설명):</div>`;
    h += `<div class="model-list">`;
    for (const m of (MODELS.image || [])) {
      const on = m.repo === repo;
      const tags = mtagsHtml(m);
      h += `<button class="model-opt ${on ? "on" : ""}" title="${escapeAttr(m.desc || "")}" onclick="setImageRepo('${escapeAttr(m.repo)}')">
        <span class="io-dot">${on ? "●" : "○"}</span>
        <span class="mo-main"><span class="mo-name">${escapeHtml(m.name)}</span> <span class="mo-repo">${escapeHtml(m.repo)}</span><div class="mo-tags">${tags}</div></span>
      </button>`;
    }
    h += `</div>`;
    // 직접 입력 (목록에 없는 모델)
    const inList = (MODELS.image || []).some((m) => m.repo === repo);
    h += `<div style="display:flex;gap:6px;margin-top:6px">
        <input id="imgRepoInput" value="${(!inList && repo) ? escapeAttr(repo) : ""}" placeholder="직접 입력: org/name (예: Qwen/Qwen-Image)" style="flex:1;background:#0c0f13;color:var(--ink);border:1px solid var(--line);border-radius:7px;padding:6px 9px;font-family:var(--mono);font-size:12px">
        <button class="btn small" onclick="setImageRepo((document.getElementById('imgRepoInput')||{}).value)">직접 설정</button>
      </div>`;
    if (repo) {
      // 진입 시 미확인이면 자동으로 한 번 경량 확인 (중복 방지)
      if (MODEL_PRESENT[repo] === undefined && !CHECKING.has(repo)) {
        CHECKING.add(repo);
        checkPresence(repo).then(() => { CHECKING.delete(repo); updateReadyUI(); });
      }
      const pres = MODEL_PRESENT[repo];   // true/false/undefined(확인중)
      const ok = pres === true;
      const statusTxt = pres === undefined ? "⏳ 확인 중…"
        : (ok ? "✓ 모델 있음: " + escapeHtml(repo) : "미다운로드: " + escapeHtml(repo));
      h += `<div class="ic-status ${ok ? "ok" : "wait"}" style="margin-top:8px">${statusTxt}${presenceRecheckHtml(repo, pres)}</div>`;
      if (pres === false) {
        h += `<button class="btn gate" style="margin-top:6px" onclick="installImageModel()">⚡ 이 모델 설치(다운로드)</button>
          ${hfAuthBox(repo)}
          <span class="hint" id="instHint" style="display:block;margin-top:6px"></span>
          <pre id="instLog" class="inst-log"></pre>`;
      }
    }
    h += `</div>`;
  }

  // gpt-image 키
  if (/gpt-image/i.test(cur) && !openaiKeyOk()) {
    h += `<div class="key-row">
      <input id="openaiKeyInput" type="password" placeholder="OPENAI_API_KEY 붙여넣기" autocomplete="off" spellcheck="false">
      <button class="btn small" onclick="saveOpenAIKey()">키 저장(.env)</button>
    </div><div class="hint" style="color:var(--warn);margin-top:4px">gpt-image는 키가 있어야 확정됩니다.</div>`;
  }

  const msg = !cur ? "아직 미선택 — 하나를 눌러 확정하세요"
    : (imageEngineReady() ? `✓ '${escapeHtml(cur)}' 확정 준비됨` : "모델 다운로드/키 후 확정 가능");
  h += `<div class="ic-status ${!cur ? "wait" : (imageEngineReady() ? "ok" : "wait")}">${msg}</div>`;
  return h + `</div>`;
}
window.setImageRepo = async (v) => {
  v = (v || "").trim();
  if (!v) return;
  STATE = await postJSON(`/api/projects/${PID}/engine`, { key: "image_repo", value: v });
  if (MODEL_PRESENT[v] === undefined) MODEL_PRESENT[v] = undefined; // 확인중 상태
  updateReadyUI();                    // "확인 중…" 즉시 표시 (전체 리렌더 X)
  await checkPresence(v);             // 경량 존재 확인
  updateReadyUI();
};
window.installImageModel = () => {
  const repo = (STATE.engine_choices || {}).image_repo;
  if (repo) runInstall("이미지 모델 (로컬)", repo);
};
function openaiKeyOk() {
  if (KEY_SAVED.has("OPENAI_API_KEY")) return true;
  const item = DIAG && (DIAG.items || []).find((i) => i.name === "OPENAI_API_KEY");
  return !!(item && item.ok);
}
function imageEngineReady() {
  const ch = (STATE.engine_choices || {}).image;
  if (!ch) return false;
  if (/gpt-image/i.test(ch)) return openaiKeyOk();
  // 로컬 엔진 = 선택한 모델(repo)이 실제로 받아져 있어야 준비됨 (경량 캐시)
  const repo = (STATE.engine_choices || {}).image_repo;
  return !!repo && MODEL_PRESENT[repo] === true;
}
window.chooseImageEngine = async (v) => {
  STATE = await postJSON(`/api/projects/${PID}/engine`, { key: "image", value: v });
  const repo = (STATE.engine_choices || {}).image_repo;
  if (repo && MODEL_PRESENT[repo] === undefined) checkPresence(repo).then(updateReadyUI);
  updateReadyUI();   // 부분 갱신 (전체 리렌더 X)
};
window.saveOpenAIKey = async () => {
  const el = $("openaiKeyInput");
  const v = el ? el.value.trim() : "";
  if (!v) return;
  await postJSON("/api/env", { key: "OPENAI_API_KEY", value: v });
  if (el) el.value = "";
  KEY_SAVED.add("OPENAI_API_KEY");   // 즉시 반영 (재진단 없이)
  updateReadyUI();
};

// 3D 엔진 선택 (Hunyuan 로컬 / Rodin 클라우드) — 이미지와 동일 패턴
function meshChooser() {
  const choices = (ENGINES.roles && ENGINES.roles.mesh_3d && ENGINES.roles.mesh_3d.choices) || [];
  const cur = (STATE.engine_choices || {}).mesh_3d || "";
  const repo = (STATE.engine_choices || {}).mesh_repo || "";
  let h = `<div class="img-choose"><div class="ic-h">3D 엔진 — 하나를 눌러 확정</div>`;
  for (const c of choices) {
    const cloud = isCloudMesh(c);
    const on = c === cur;
    h += `<button class="img-opt ${on ? "on" : ""}" onclick="chooseMeshEngine('${escapeAttr(c)}')">
      <span class="io-dot">${on ? "●" : "○"}</span><span class="io-name">${escapeHtml(c)}</span>${cloud ? '<span class="io-tag key">🔑 키필요</span>' : '<span class="io-tag local">로컬</span>'}</button>`;
  }

  // 로컬(Hunyuan): 모델 카탈로그 선택 + 설치
  if (cur && !isCloudMesh(cur)) {
    h += `<div class="model-pick">${gpuBanner()}<div class="hint" style="margin-bottom:6px">3D 모델 선택 (마우스 올리면 설명 · shape=메시 / texgen=텍스처 따로 판정):</div><div class="model-list">`;
    for (const m of (MODELS.mesh || [])) {
      const on = m.repo === repo;
      const tags = mtagsHtml(m);
      h += `<button class="model-opt ${on ? "on" : ""}" title="${escapeAttr(m.desc || "")}" onclick="setMeshRepo('${escapeAttr(m.repo)}')">
        <span class="io-dot">${on ? "●" : "○"}</span>
        <span class="mo-main"><span class="mo-name">${escapeHtml(m.name)}</span> <span class="mo-repo">${escapeHtml(m.repo)}</span><div class="mo-tags">${tags}</div></span>
      </button>`;
    }
    h += `</div>`;
    if (repo) {
      if (MODEL_PRESENT[repo] === undefined && !CHECKING.has(repo)) {
        CHECKING.add(repo);
        checkPresence(repo).then(() => { CHECKING.delete(repo); updateReadyUI(); });
      }
      const pres = MODEL_PRESENT[repo];
      const ok = pres === true;
      const statusTxt = pres === undefined ? "⏳ 확인 중…" : (ok ? "✓ 모델 있음: " + escapeHtml(repo) : "미다운로드: " + escapeHtml(repo));
      h += `<div class="ic-status ${ok ? "ok" : "wait"}" style="margin-top:8px">${statusTxt}${presenceRecheckHtml(repo, pres)}</div>`;
      if (pres === false) {
        h += `<button class="btn gate" style="margin-top:6px" onclick="installMeshModel()">⚡ 이 모델 설치(다운로드)</button>
          <div class="hint" style="margin-top:4px">Hunyuan은 게이트 아님(토큰 불필요). 실행엔 레포 코드/의존성이 추가로 필요할 수 있음.</div>
          <span class="hint" id="instHint" style="display:block;margin-top:6px"></span>
          <pre id="instLog" class="inst-log"></pre>`;
      }
    }
    h += `</div>`;
  }

  if (isCloudMesh(cur) && !rodinKeyOk()) {
    h += `<div class="key-row">
      <input id="rodinKeyInput" type="password" placeholder="RODIN_API_KEY 붙여넣기" autocomplete="off" spellcheck="false">
      <button class="btn small" onclick="saveRodinKey()">키 저장(.env)</button>
    </div><div class="hint" style="color:var(--warn);margin-top:4px">Rodin은 키가 있어야 확정됩니다.</div>`;
  }
  const msg = !cur ? "아직 미선택 — 하나를 눌러 확정하세요"
    : (meshEngineReady() ? `✓ '${escapeHtml(cur)}' 확정 준비됨` : "모델 다운로드/키 후 확정 가능");
  h += `<div class="ic-status ${!cur ? "wait" : (meshEngineReady() ? "ok" : "wait")}">${msg}</div>`;
  return h + `</div>`;
}
function isCloudMesh(v) { return /rodin|hyper3d|클라우드/i.test(v || ""); }
window.setMeshRepo = async (v) => {
  v = (v || "").trim();
  if (!v) return;
  STATE = await postJSON(`/api/projects/${PID}/engine`, { key: "mesh_repo", value: v });
  updateReadyUI();
  await checkPresence(v);
  updateReadyUI();
};
window.installMeshModel = () => {
  const repo = (STATE.engine_choices || {}).mesh_repo;
  if (repo) runInstall("3D 모델 (로컬)", repo);
};
function rodinKeyOk() {
  if (KEY_SAVED.has("RODIN_API_KEY")) return true;
  const item = DIAG && (DIAG.items || []).find((i) => i.name === "RODIN_API_KEY (Hyper3D)");
  return !!(item && item.ok);
}
function meshEngineReady() {
  const ch = (STATE.engine_choices || {}).mesh_3d;
  if (!ch) return false;
  if (isCloudMesh(ch)) return rodinKeyOk();
  // 로컬(Hunyuan) = 선택한 모델(repo)이 실제로 받아져 있어야 준비됨 (경량 캐시)
  const repo = (STATE.engine_choices || {}).mesh_repo;
  return !!repo && MODEL_PRESENT[repo] === true;
}
function enginesReady() { return imageEngineReady() && meshEngineReady(); }
// 확실히 '준비 안 됨'인가 (확인중 undefined 는 제외 — 재잠금 오작동 방지)
function envDefinitelyNotReady() {
  const ec = STATE.engine_choices || {};
  const ie = ec.image;
  if (!ie) return true;
  if (/gpt-image/i.test(ie)) { if (!openaiKeyOk()) return true; }
  else { if (!ec.image_repo) return true; if (MODEL_PRESENT[ec.image_repo] === false) return true; }
  const me = ec.mesh_3d;
  if (!me) return true;
  if (isCloudMesh(me)) { if (!rodinKeyOk()) return true; }
  else { if (!ec.mesh_repo) return true; if (MODEL_PRESENT[ec.mesh_repo] === false) return true; }
  return false;
}
// 준비가 깨졌는데 env 게이트가 통과 상태면 다시 잠금 (제대로 강제)
async function maybeRelockEnv() {
  const st = (STATE.steps || {}).env;
  if (st && st.gate_passed && envDefinitelyNotReady()) {
    try {
      STATE = await postJSON(`/api/projects/${PID}/ungate`, { step: "env" });
      renderFlowList();          // 왼쪽 목록만 갱신 (강제 이동/전체 리렌더 X → 스크롤 유지)
      updateGateButtons();
    } catch (e) {}
  }
}
window.chooseMeshEngine = async (v) => {
  STATE = await postJSON(`/api/projects/${PID}/engine`, { key: "mesh_3d", value: v });
  updateReadyUI();   // 부분 갱신
};
window.saveRodinKey = async () => {
  const el = $("rodinKeyInput");
  const v = el ? el.value.trim() : "";
  if (!v) return;
  await postJSON("/api/env", { key: "RODIN_API_KEY", value: v });
  if (el) el.value = "";
  KEY_SAVED.add("RODIN_API_KEY");
  updateReadyUI();
};

// 항목이 현재 엔진 선택에 필요한지 (선택에 따라 불필요한 건 회색+필수제외)
function itemRelevant(dep) {
  const ic = (STATE.engine_choices || {}).image || "";
  const mc = (STATE.engine_choices || {}).mesh_3d || "";
  const cloudImage = /gpt-image/i.test(ic);
  const cloudMesh = isCloudMesh(mc);
  const localImage = ic && !cloudImage;
  const localMesh = mc && !cloudMesh;
  switch (dep) {
    case "local": return !(cloudImage && cloudMesh);   // 둘 다 클라우드로 확정돼야 불필요
    case "image:local": return !cloudImage;
    case "image:cloud": return !localImage;
    case "mesh:local": return !cloudMesh;
    case "mesh:cloud": return !localMesh;
    default: return true;
  }
}

window.runDiagnose = async () => {
  const btn = $("diagBtn"), stat = $("diagStatus"), res = $("diagResult");
  if (btn) btn.disabled = true;
  if (stat) stat.innerHTML = `<span style="color:var(--accent)">진단중…</span>`;
  if (res) res.innerHTML = "";
  try {
    const ir = (STATE && STATE.engine_choices && STATE.engine_choices.image_repo) || "";
    const d = await api("/api/diagnose" + (ir ? "?image_repo=" + encodeURIComponent(ir) : ""));
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
  const moreBtn = $("docMoreBtn");
  if (!ref) {
    $("docView").innerHTML = "<p class='faint'>(연결된 문서 없음)</p>";
    $("docTitle").textContent = "";
    DOC_FULL = ""; DOC_REF = "";
    if (moreBtn) moreBtn.style.display = "none";
    return;
  }
  $("docTitle").textContent = "📄 " + ref;
  try {
    const d = await api("/api/doc?ref=" + encodeURIComponent(ref));
    DOC_FULL = d.text || "(빈 문서)"; DOC_REF = ref;
    const short = shortMd(DOC_FULL);
    const truncated = short.length < DOC_FULL.length;
    $("docView").innerHTML = mdToHtml(short) + (truncated ? `<p class="faint" style="margin-top:8px">… (더보기로 전체 보기)</p>` : "");
    if (moreBtn) moreBtn.style.display = truncated ? "" : "none";
  } catch (e) {
    $("docView").innerHTML = "<p class='faint'>(문서 로드 실패: " + escapeHtml(ref) + ")</p>";
    if (moreBtn) moreBtn.style.display = "none";
  }
}

// 문서 요약: 첫 섹션(2번째 heading 전) 또는 최대 14줄
function shortMd(text) {
  const lines = text.split(/\r?\n/);
  const out = []; let headings = 0;
  for (const ln of lines) {
    if (/^#{1,6}\s/.test(ln)) { headings++; if (headings >= 2 && out.length > 0) break; }
    out.push(ln);
    if (out.length >= 14) break;
  }
  return out.join("\n").trim();
}

window.openGuide = (name) => {
  const data = window._diagData || {};
  const item = (data.items || []).find((i) => i.name === name);
  const g = (item && item.guide) ? item.guide : "설치 가이드가 없습니다.";
  $("docModalTitle").textContent = "🛠 설치 — " + name;
  let extra = "";
  if (AUTO_INSTALL.has(name)) {
    const wingetItem = /node|git|Blender|Unreal Engine/i.test(name);
    const warn = (wingetItem && !WINGET) ? " (winget 미설치 — 아래 수동 가이드 이용)" : "";
    extra = `<div class="inst-box">
      <button class="btn gate" id="instBtn" onclick="runInstall('${escapeAttr(name)}')" ${(wingetItem && !WINGET) ? "disabled" : ""}>⚡ 지금 설치</button>
      <span class="hint" id="instHint" style="margin-left:8px">이 자리에서 바로 설치합니다${warn}</span>
      <pre id="instLog" class="inst-log" style="display:none"></pre>
    </div>`;
  }
  $("docModalBody").innerHTML = extra + mdToHtml(g);
  $("docOverlay").classList.add("open");
};

// HF 로그인 상태에 맞춰 인증 박스 렌더 (게이트 모델 4단계 안내)
function hfAuthBox(repo) {
  const licUrl = "https://huggingface.co/" + repo;
  const licLink = `<a href="#" onclick="window.open('${escapeAttr(licUrl)}');return false" style="color:var(--accent)">라이선스 동의 페이지 열기 ↗</a>`;
  if (HF_USER && HF_USER.logged_in) {
    return `<div class="auth-box">
      <div class="hint" style="color:var(--good);margin-bottom:4px">✅ HuggingFace 로그인됨: <b>${escapeHtml(HF_USER.name || "")}</b></div>
      <div style="font-size:12px">게이트 모델이면 <b>먼저 ${licLink}</b> → 상단 <b>"Agree and access repository"</b> 클릭 후 → 아래 <b>'이 모델 설치'</b>.</div>
    </div>`;
  }
  const warn = HF_USER && HF_USER.invalid ? "저장된 토큰이 <b>만료/무효</b>예요 — 새 토큰으로 로그인하세요." : "게이트 모델은 <b>로그인 + 라이선스 동의</b>가 필요해요.";
  return `<div class="auth-box">
    <div class="hint" style="margin-bottom:8px">🔒 ${warn}</div>
    <div class="auth-step"><b>1)</b> <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer" style="color:var(--accent)">토큰 발급 ↗</a> — New token → 유형 <b>Read</b> → 복사(hf_...)</div>
    <div class="auth-step"><b>2)</b> 토큰 붙여넣고 로그인:
      <div style="display:flex;gap:6px;margin-top:4px">
        <input id="hfToken" type="password" placeholder="hf_..." autocomplete="off" spellcheck="false" style="flex:1;background:#0c0f13;color:var(--ink);border:1px solid var(--line);border-radius:7px;padding:6px 9px;font-family:var(--mono);font-size:12px">
        <button class="btn small" onclick="hfLogin()">로그인</button>
      </div>
    </div>
    <div class="auth-step"><b>3)</b> ${licLink} → 상단 <b>"Agree and access repository"</b> 클릭</div>
    <div class="auth-step"><b>4)</b> 아래 <b>'이 모델 설치'</b> → 다운로드 (대용량·시간 걸림)</div>
  </div>`;
}
window.hfLogin = async () => {
  const el = $("hfToken");
  const v = el ? el.value.trim() : "";
  const hint = $("instHint");
  if (!v) return;
  if (hint) hint.textContent = "로그인 중…";
  try {
    const r = await postJSON("/api/hf/login", { token: v });
    if (el) el.value = "";
    HF_USER = { logged_in: true, name: r.name };
    if (hint) hint.innerHTML = '<span style="color:var(--good)">로그인됨 ✅ ' + escapeHtml(r.name || "") + ' — 라이선스 동의 후 설치</span>';
    updateReadyUI();
  } catch (e) {
    if (hint) hint.innerHTML = '<span style="color:var(--bad)">로그인 실패 — 토큰 확인(read 권한)</span>';
  }
};

window.runInstall = async (name, repoArg) => {
  const btn = $("instBtn"), hint = $("instHint"), log = $("instLog");
  if (btn) btn.disabled = true;
  if (hint) hint.textContent = "설치 시작…";
  if (log) { log.style.display = "block"; log.textContent = ""; }
  const payload = repoArg ? { item: name, repo: repoArg } : { item: name };
  try { await postJSON("/api/install", payload); }
  catch (e) {
    if (e.detail && e.detail.error === "gpu_not_ready") {
      // 수십 GB 를 받고 나서 CPU 로 도는 것보다, 여기서 세우고 바로 고치게 한다.
      if (hint) hint.innerHTML =
        `<span style="color:var(--warn)">⚠ ${escapeHtml(e.message)}</span>` +
        `<div class="hint" style="margin-top:4px">현재 torch: ${escapeHtml(String(e.detail.torch || "없음"))}</div>` +
        `<button class="btn gate" style="margin-top:6px" onclick="runInstall('PyTorch (GPU)')">⚡ PyTorch (GPU) 지금 설치</button>`;
    } else if (hint) {
      hint.textContent = "설치 시작 실패: " + e.message;
    }
    if (btn) btn.disabled = false;
    return;
  }
  while (true) {
    await sleep(1500);
    let s;
    try { s = await api("/api/install/status?item=" + encodeURIComponent(name)); } catch (e) { continue; }
    if (log) { log.textContent = (s.lines || []).join("\n"); log.scrollTop = log.scrollHeight; }
    if (!s.running && s.code !== null && s.code !== undefined) {
      if (s.code === 0) {
        if (repoArg) {
          // 이미지 모델: 경량 존재 확인 + 부분 갱신 (전체 재진단/리렌더 X)
          if (hint) hint.innerHTML = '<span style="color:var(--accent)">다운로드 완료 · 확인 중…</span>';
          await checkPresence(repoArg);
          updateReadyUI();
          if (hint) hint.innerHTML = MODEL_PRESENT[repoArg]
            ? '<span style="color:var(--good)">설치 완료 ✅ — 모델 준비됨</span>'
            : '<span style="color:var(--warn)">받아졌지만 감지 실패 — 로그 확인(라이선스/토큰?)</span>';
        } else {
          if (hint) hint.innerHTML = '<span style="color:var(--accent)">명령 완료 · 재진단 중…</span>';
          await runDiagnose();
          keepScroll(() => renderCenter());
          const nowItem = ((window._diagData || {}).items || []).find((i) => i.name === name);
          if (hint) hint.innerHTML = (nowItem && nowItem.ok)
            ? '<span style="color:var(--good)">설치 완료 ✅ — 이 항목 OK</span>'
            : '<span style="color:var(--warn)">명령 완료 ✅ 하지만 추가 단계 남음 — 로그 확인</span>';
        }
        if (btn) btn.disabled = false;
      } else {
        const txt = (s.lines || []).join("\n");
        const gated = /gated|restricted|401|log ?in|authenticate|access to model/i.test(txt);
        if (hint) hint.innerHTML = gated
          ? '<span style="color:var(--warn)">🔒 게이트 접근 거부 — ① HF 토큰 저장 ② 라이선스 동의(위 링크) 후 다시 설치하세요</span>'
          : '<span style="color:var(--bad)">실패(코드 ' + s.code + ') — 로그 확인 후 수동 가이드</span>';
        if (btn) btn.disabled = false;
      }
      break;
    }
  }
};

function openDocModal() {
  if (!DOC_FULL) return;
  $("docModalTitle").textContent = "📄 " + DOC_REF;
  $("docModalBody").innerHTML = mdToHtml(DOC_FULL);
  $("docOverlay").classList.add("open");
}

// 경량 마크다운 렌더러 (외부 의존성 없음)
function mdToHtml(src) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s) => s
    .replace(/`([^`]+)`/g, (m, c) => `<code>${c}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');

  const lines = esc(src).split(/\r?\n/);
  let html = "", inCode = false, codeBuf = [], listType = null, listBuf = [], tableBuf = [];
  const closeList = () => { if (listType) { html += `<${listType}>` + listBuf.join("") + `</${listType}>`; listType = null; listBuf = []; } };
  const closeTable = () => {
    if (!tableBuf.length) return;
    let out = "<table>";
    tableBuf.forEach((r, idx) => {
      if (/^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$/.test(r)) return; // 구분선
      const cells = r.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());
      const tag = idx === 0 ? "th" : "td";
      out += "<tr>" + cells.map((c) => `<${tag}>${inline(c)}</${tag}>`).join("") + "</tr>";
    });
    html += out + "</table>"; tableBuf = [];
  };
  for (const ln of lines) {
    if (/^```/.test(ln)) {
      if (inCode) { html += `<pre><code>${codeBuf.join("\n")}</code></pre>`; codeBuf = []; inCode = false; }
      else { closeList(); closeTable(); inCode = true; }
      continue;
    }
    if (inCode) { codeBuf.push(ln); continue; }
    if (/^\s*\|.*\|\s*$/.test(ln)) { closeList(); tableBuf.push(ln); continue; } else closeTable();
    let m;
    if ((m = ln.match(/^(#{1,6})\s+(.*)$/))) { closeList(); html += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`; continue; }
    if (/^\s*[-*]\s+/.test(ln)) { if (listType !== "ul") { closeList(); listType = "ul"; } listBuf.push(`<li>${inline(ln.replace(/^\s*[-*]\s+/, ""))}</li>`); continue; }
    if (/^\s*\d+\.\s+/.test(ln)) { if (listType !== "ol") { closeList(); listType = "ol"; } listBuf.push(`<li>${inline(ln.replace(/^\s*\d+\.\s+/, ""))}</li>`); continue; }
    closeList();
    if (/^\s*>\s?/.test(ln)) { html += `<blockquote>${inline(ln.replace(/^\s*>\s?/, ""))}</blockquote>`; continue; }
    if (/^\s*(---|\*\*\*|___)\s*$/.test(ln)) { html += "<hr>"; continue; }
    if (ln.trim() === "") continue;
    html += `<p>${inline(ln)}</p>`;
  }
  closeList(); closeTable();
  if (inCode) html += `<pre><code>${codeBuf.join("\n")}</code></pre>`;
  return html;
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
window.toggleIdeas = (btn) => {
  const p = $("ideasPanel"); if (!p) return;
  const show = p.style.display === "none";
  p.style.display = show ? "block" : "none";
  btn.textContent = show ? "💡 아이디어 예시 ▴" : "💡 아이디어 예시 ▾";
};
// 아이디어 조각 클릭 → 해당 입력칸에 이어붙임 (전체 리렌더 없이)
window.appendIdea = async (field, text) => {
  const el = document.querySelector(`[data-field="${field}"]`);
  if (!el) return;
  const curv = el.value.replace(/\s+$/, "");
  el.value = curv ? (curv + " " + text) : text;
  el.focus();
  await saveInput(field, el.value);
};
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
  el.value = "";
  refreshAssetTags();   // 부분 갱신 (리렌더 없이)
};
window.addAssetItem = async (t, btn) => {
  const arr = Array.isArray(STATE.inputs.asset_list) ? STATE.inputs.asset_list.slice() : [];
  if (arr.includes(t)) return;
  arr.push(t);
  STATE = await postJSON(`/api/projects/${PID}/input`, { field: "asset_list", value: arr });
  refreshAssetTags();
  if (btn) { btn.classList.add("added"); btn.textContent = "✓ " + t; }
};
window.removeAsset = async (i) => {
  const arr = (STATE.inputs.asset_list || []).slice();
  arr.splice(i, 1);
  STATE = await postJSON(`/api/projects/${PID}/input`, { field: "asset_list", value: arr });
  refreshAssetTags();
};
function paintAssetSuggest() {
  const box = $("assetSuggest"); if (!box) return;
  if (!ASSET_SUGGESTIONS) { box.innerHTML = ""; return; }
  const have = new Set((STATE.inputs || {}).asset_list || []);
  const basis = STATE.asset_suggest_basis || {};
  const src = basis.ref_image
    ? `<b style="color:var(--accent)">배경 이미지</b>(${escapeHtml(basis.ref_image)})를 보고 뽑음`
    : `주제·배경 글 기준`;
  let h = `<div class="hint" style="margin-bottom:4px">추천 에셋 — 클릭해서 담기 (필요 없는 건 무시) · ${src}</div>`;
  // 무엇을 보고 뽑았는지 보여준다 — 빠진 게 있을 때 어디서 어긋났는지 사용자가 바로 안다.
  if (basis.seen) {
    h += `<div class="hint" style="margin-bottom:6px;color:var(--faint)">
      👁 그림에서 본 것: ${escapeHtml(basis.seen)}</div>`;
  }
  for (const c of ASSET_SUGGESTIONS) {
    const chips = (c.items || []).map((t) => {
      const on = have.has(t);
      return `<button class="idea-chip ${on ? "added" : ""}" onclick="addAssetItem('${escapeAttr(t)}', this)">${on ? "✓ " : "+ "}${escapeHtml(t)}</button>`;
    }).join("");
    h += `<div class="idea-row"><span class="idea-lbl">${escapeHtml(c.name || "")}</span><div class="idea-chips">${chips}</div></div>`;
  }
  box.innerHTML = h;
}
// 마지막 추천이 무엇을 근거로 뽑혔는지와 현재 2단계 값을 비교한다.
function suggestBasisStale() {
  const b = STATE.asset_suggest_basis;
  if (!b) return true;                       // 근거 기록이 없으면 옛 추천 → 다시
  const inp = STATE.inputs || {};
  const refFile = ((STATE.ref_images || [])[0] || {}).file || null;
  return (b.topic || "") !== (inp.topic || "")
      || (b.background || "") !== (inp.background || "")
      || (b.ref_image || null) !== refFile;
}

window.suggestAssets = async () => {
  const box = $("assetSuggest"); if (!box) return;
  // ★ 값을 여기서 넘기지 않는다 — 서버가 state 에서 읽는다(계약: 값은 state 에서만).
  //   배경 이미지를 준 경우 서버가 그 그림까지 함께 보고 뽑는다.
  const hasRef = (STATE.ref_images || []).length > 0;
  box.innerHTML = `<span class="hint">🤖 2단계를 참고해 에셋 추천 중… ` +
    `${hasRef ? "(배경 이미지를 보고 뽑는 중 — 조금 더 걸립니다)" : "(주제·배경 기준)"}</span>`;
  try {
    const d = await postJSON("/api/suggest-assets", { pid: PID });
    if (d.error) { box.innerHTML = `<span class="hint" style="color:var(--warn)">${escapeHtml(d.error)}</span>`; return; }
    ASSET_SUGGESTIONS = d.categories || [];
    LAST_SUGGEST_USED_REF = !!d.used_ref_image;
    paintAssetSuggest();
  } catch (e) {
    box.innerHTML = `<span class="hint" style="color:var(--bad)">추천 실패: ${escapeHtml(e.message)}</span>`;
  }
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
  // 진단 단계: 진단 완료 + 이미지·3D 엔진 확정(클라우드면 키까지)돼야 확정 가능.
  if (s.diagnostic) return DIAG_DONE && enginesReady();
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
  return { topic: "주제", background: "배경", anchor: "앵커(스타일 기준)", asset_list: "에셋 리스트",
           lighting: "조명·시간대" }[f] || f;
}
function escapeHtml(s) { return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
function escapeAttr(s) { return escapeHtml(s).replace(/"/g, "&quot;"); }

init().catch((e) => { document.body.innerHTML = "<pre style='padding:20px;color:#ff6b6b'>초기화 실패: " + e.message + "</pre>"; });
