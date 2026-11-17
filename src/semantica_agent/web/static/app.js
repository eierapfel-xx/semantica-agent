// 審査支援の画面。状態（色）はサーバーが計算して送る view を描くだけにする（仕様 §9）。
"use strict";

const BUSINESS_JA = { birth: "出生", marriage: "婚姻", divorce: "離婚", death: "死亡", certificate: "交付" };
const DECISION_JA = {
  reject: "受理できない", needsCorrection: "補正・追完が要る", needsInquiry: "法務局への受理照会が要る",
  additionalProcedure: "受理できるが追加の手続が要る", acceptable: "受理可", pending: "判定保留",
};
const STATE_JA = {
  finding: "指摘", unevaluated: "評価できず", human: "人の確認", passed: "通過", referenced: "参照", none: "",
};
const KIND_JA = { rule: "ルール", fact: "事実", speculation: "推測" };
const BADGE_JA = { info: "参考", provisional: "暫定", manual: "手順書時点", current: "現行" };
const STATUS_JA = { given: "値あり", none: "無い", unknown: "未確認" };
const EVENT_JA = {
  user: "質問", assistant_text: "AIの文章", thinking: "AIの思考", tool_call: "ツール呼び出し",
  tool_result: "ツールの結果", answer: "回答", error: "エラー",
};
const TOOL_JA = {
  judge_birth_case: "判定", search_nodes: "検索", describe_node: "詳細", run_cq: "CQ",
  run_sparql: "SPARQL", submit_answer: "回答の提出",
};
const LEGEND = [
  ["通過", "--passed"], ["受理不可", "--finding-reject"], ["補正", "--finding-correction"],
  ["照会", "--finding-inquiry"], ["追加の手続", "--finding-procedure"], ["評価できず", "--unevaluated"],
  ["人の確認", "--human"], ["参照", "--referenced"],
];

const $ = (id) => document.getElementById(id);
const state = {
  sessionId: null, shapes: {}, business: "birth", turnEvents: [], views: [], selected: null, busy: false,
};

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

// ── フロー ─────────────────────────────────────────────

async function shape(business) {
  if (!state.shapes[business]) state.shapes[business] = await getJSON(`/api/flow/${business}`);
  return state.shapes[business];
}

function idLink(id) {
  return el("span", { class: "idlink", onclick: () => showDetail(id) }, id);
}

function itemNode(item, view) {
  const st = (view && view.flow[item.id]) || { state: "none", badges: [] };
  const cls = ["item", `s-${st.state}`];
  if (st.outcome) cls.push(`o-${st.outcome}`);
  const badges = (st.badges || []).map((b) => el("span", { class: "badge" }, BADGE_JA[b] || b));
  const label = STATE_JA[st.state] ? ` [${STATE_JA[st.state]}${st.outcome ? "：" + DECISION_JA[st.outcome] : ""}]` : "";
  return el("li", {},
    el("div", { class: cls.join(" "), "data-id": item.id, title: item.id, onclick: () => showDetail(item.id) },
      el("span", { class: "lbl" }, item.itemLabel), item.label, el("strong", {}, label), badges,
      item.conditions.length ? el("span", { class: "cond" }, "条件：" + item.conditions.join("、")) : null,
      st.reason ? el("span", { class: "why" }, st.reason) : null),
    item.children.length ? el("ul", { class: "items" }, item.children.map((c) => itemNode(c, view))) : null);
}

async function drawFlow(view) {
  const s = await shape(state.business);
  const steps = (view && view.steps[state.business]) || {};
  $("flow").replaceChildren(...s.steps.map((st) =>
    el("div", { class: `step s-${steps[st.id] || "none"}` },
      el("h3", { title: st.id, onclick: () => showDetail(st.id) }, `${st.number}. ${st.label}`),
      el("ul", { class: "items" }, st.items.map((i) => itemNode(i, view))))));
  drawTabs(view);
  drawOthers(view);
}

function drawTabs(view) {
  $("tabs").replaceChildren(...Object.keys(BUSINESS_JA).map((b) => {
    const touched = view && Object.values(view.steps[b] || {}).some((x) => x !== "none");
    return el("button", {
      type: "button", class: b === state.business ? "active" : "",
      onclick: () => { state.business = b; drawFlow(currentView()); },
    }, BUSINESS_JA[b], touched ? el("span", { class: "dot", style: "background: var(--accent)" }) : null);
  }));
}

function drawOthers(view) {
  if (!view) return $("others").replaceChildren();
  const inFlow = new Set();
  const walk = (items) => items.forEach((i) => { inFlow.add(i.id); walk(i.children); });
  Object.values(state.shapes).forEach((s) => s.steps.forEach((st) => { inFlow.add(st.id); walk(st.items); }));
  const others = Object.entries(view.flow).filter(([id, st]) => st.state === "referenced" && !inFlow.has(id));
  $("others").replaceChildren(others.length ? el("span", { class: "muted" }, "参照した法令・ノード：") : "",
    ...others.map(([id]) => idLink(id)));
}

function drawLegend() {
  $("legend").replaceChildren(...LEGEND.map(([t, v]) => el("li", { style: `--c: var(${v})` }, t)));
}

function currentView() {
  if (state.selected !== null) return state.views[state.selected];
  return state.views[state.views.length - 1];
}

// ── AIの処理（イベントの列） ───────────────────────────

function eventLabel(e) {
  if (e.type === "tool_call" || e.type === "tool_result") return `${EVENT_JA[e.type]}：${TOOL_JA[e.tool] || e.tool}`;
  if (e.type === "turn_end") return "完了";
  return EVENT_JA[e.type] || e.type;
}

function drawProcess() {
  $("process").replaceChildren(...state.turnEvents.map((e, i) => {
    const cls = [`ev-${e.type}`];
    if (e.is_error) cls.push("is-error");
    if (i === state.selected) cls.push("selected");
    const title = e.type === "tool_call" ? JSON.stringify(e.args) : (e.text || e.message || "");
    return el("li", {
      class: cls.join(" "), title: title.slice(0, 500),
      onclick: () => {
        state.selected = i === state.selected ? null : i;
        drawProcess();
        const v = currentView();
        if (v) state.business = v.business;
        drawFlow(v);
      },
    }, `${i + 1}. ${eventLabel(e)}`);
  }));
}

function pushEvent(e) {
  state.turnEvents.push(e);
  state.views.push(e.view);
  if (state.selected === null && e.view) state.business = e.view.business;
  drawProcess();
  drawFlow(currentView());
}

// ── 会話と回答 ─────────────────────────────────────────

function decisionBox(j) {
  if (!j) return null;
  const extra = [];
  if (j.has_unconfirmed && j.decision !== "pending") extra.push("（ほかに未確認あり）");
  return el("div", { class: `decision ${j.decision}` },
    el("div", {}, "判定（コードの結果）："), el("strong", {}, DECISION_JA[j.decision], extra),
    j.unconfirmed.length ? el("div", {}, "未確認：" + j.unconfirmed.map((u) => u.label).join("、")) : null,
    j.provisional_decision ? el("div", {}, `暫定の判定（未承認の現行版）：${DECISION_JA[j.provisional_decision]}`) : null,
    [...j.findings, ...(j.info || [])].map((f) =>
      el("div", {}, `・${DECISION_JA[f.outcome] || "参考"}：${f.message}`, idLink(f.rule), f.check ? idLink(f.check) : null)));
}

function claimsList(answer) {
  if (!answer) return null;
  return el("ul", { class: "claims" }, answer.claims.map((c) =>
    el("li", {}, el("span", { class: `kind ${c.kind}` }, KIND_JA[c.kind]), c.text, c.nodes.map(idLink),
      c.downgraded_reason ? el("div", { class: "reason" }, `推測に下げた理由：${c.downgraded_reason}`) : null)));
}

function caseTable(c) {
  if (!c) return null;
  const rows = c.fields.map((f) => el("tr", { class: `st-${f.status}` },
    el("td", {}, f.label), el("td", {}, STATUS_JA[f.status]),
    el("td", {}, Array.isArray(f.value) ? f.value.join("、") : (f.value ?? ""),
      f.inferred ? el("span", { class: "inferred" }, ` 推測（${f.note || "補った値"}）`) : null),
    el("td", {}, f.quote ? `「${f.quote}」` : "")));
  return el("details", {}, el("summary", {}, "入力の解釈"),
    el("table", { class: "interp" },
      el("tr", {}, el("th", {}, "項目"), el("th", {}, "状態"), el("th", {}, "値"), el("th", {}, "引用")), rows));
}

function renderTurn(trace) {
  const box = el("div", { class: "msg" });
  if (trace.status === "error") {
    const err = trace.events.filter((e) => e.type === "error").map((e) => e.message).join(" / ");
    box.append(el("div", { class: "error" }, `エラー：${err}`));
  }
  box.append(...[decisionBox(trace.judgment),
    trace.answer ? el("div", { class: "answer" }, trace.answer.answer) : null,
    claimsList(trace.answer), caseTable(trace.case)].filter(Boolean));
  $("conversation").append(box);
  box.scrollIntoView({ block: "end" });
}

function addUser(text) {
  $("conversation").append(el("div", { class: "msg user" }, text));
}

// ── 送信（SSE を fetch で読む） ────────────────────────

async function ensureSession() {
  if (!state.sessionId) state.sessionId = (await getJSON("/api/sessions", { method: "POST" })).session_id;
  return state.sessionId;
}

async function send(text) {
  setBusy(true);
  state.turnEvents = []; state.views = []; state.selected = null;
  addUser(text);
  try {
    const sid = await ensureSession();
    const r = await fetch(`/api/sessions/${sid}/messages`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        const e = JSON.parse(line.slice(5));
        pushEvent(e);
        if (e.type === "turn_end") { renderTurn(e.trace); loadTraceList(); }
      }
    }
  } catch (err) {
    $("conversation").append(el("div", { class: "msg error" }, `送信に失敗しました：${err.message}`));
  } finally {
    setBusy(false);
  }
}

function setBusy(b) {
  state.busy = b;
  $("ask-send").disabled = b;
  $("ask-send").textContent = b ? "処理中…" : "送信";
}

// ── ノードの詳細 ───────────────────────────────────────

function sourceView(s) {
  if (s.url) return el("div", {}, "e-Gov：", el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.url),
    s.fetchedDate ? `（取得 ${s.fetchedDate}）` : "", s.reviewer ? `（確認 ${s.reviewer} ${s.reviewedDate || ""}）` : "");
  if (s.pdfPage) return el("div", {}, `手順書 PDF ${s.pdfPage} 頁（印刷 ${s.printedPage} 頁）${s.rowId ? " " + s.rowId : ""}`,
    s.quote ? el("blockquote", {}, s.quote) : null);
  return el("div", {}, s.comment || JSON.stringify(s));
}

async function showDetail(id) {
  document.querySelectorAll(".item.focus").forEach((n) => n.classList.remove("focus"));
  document.querySelectorAll(`.item[data-id="${CSS.escape(id)}"]`).forEach((n) => n.classList.add("focus"));
  try {
    const d = await getJSON(`/api/nodes/${encodeURIComponent(id)}`);
    const rows = [];
    const add = (k, v) => { if (v && (!Array.isArray(v) || v.length)) rows.push(el("dt", {}, k), el("dd", {}, v)); };
    add("種類", d.classes.join("、"));
    add("属する", d.parents.map((p) => idLink(p.id)));
    add("ルール", d.rules.map((r) => idLink(r.id)));
    const p = d.properties;
    if (p.currentTreatment) add("現行での扱い", [p.currentTreatment.join("、"), " ", (p.currentTreatmentNote || []).join(" ")]);
    if (p.implementsCheck) add("判定する審査項目", p.implementsCheck.map((x) => idLink(x.id)));
    if (p.underVersion) add("法の版", p.underVersion.map((x) => idLink(x.id)));
    if (p.outcome) add("判定の種類", p.outcome.join("、"));
    if (p.reviewStatus) add("レビュー", p.reviewStatus.join("、"));
    add("条文", d.provisions.map((pr) => el("div", {}, idLink(pr.id), ` ${pr.label}`,
      pr.versions.map((v) => el("div", { class: "muted" },
        `版 ${v.id}（${v.status}${v.validFrom ? "、" + v.validFrom + "〜" : ""}${v.validUntil ? "〜" + v.validUntil : ""}、${v.reviewStatus}）`,
        v.summary ? ` ${v.summary}` : "", v.sources.map(sourceView))))));
    add("出典", d.sources.map(sourceView));
    $("detail").replaceChildren(el("h3", {}, d.label || d.id), el("div", { class: "muted" }, d.id), el("dl", {}, rows));
  } catch (err) {
    $("detail").replaceChildren(el("p", { class: "error" }, `取得できません：${err.message}`));
  }
}

// ── 過去のトレース ─────────────────────────────────────

async function loadTraceList() {
  const items = await getJSON("/api/traces");
  $("trace-list").replaceChildren(el("option", { value: "" }, "過去のトレースを開く…"),
    ...items.map((t) => el("option", { value: `${t.session_id}/${t.turn}` },
      `${t.started.slice(0, 16)} ${t.question.slice(0, 24)}（${DECISION_JA[t.decision] || "問い合わせ"}）`)));
}

async function openTrace(key) {
  const t = await getJSON(`/api/traces/${key}`);
  state.turnEvents = t.events; state.views = t.timeline; state.selected = null;
  state.business = t.business;
  $("conversation").replaceChildren();
  addUser(t.question);
  renderTurn(t);
  drawProcess();
  drawFlow(currentView());
}

// ── 起動 ───────────────────────────────────────────────

async function resetSession() {
  if (state.sessionId) await fetch(`/api/sessions/${state.sessionId}`, { method: "DELETE" });
  state.sessionId = null; state.turnEvents = []; state.views = []; state.selected = null;
  $("conversation").replaceChildren();
  drawProcess();
  drawFlow(null);
}

window.addEventListener("DOMContentLoaded", () => {
  drawLegend();
  drawFlow(null);
  loadTraceList();
  $("ask-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const text = $("ask-text").value.trim();
    if (!text || state.busy) return;
    $("ask-text").value = "";
    send(text);
  });
  $("new-session").addEventListener("click", resetSession);
  $("trace-list").addEventListener("change", (ev) => { if (ev.target.value) openTrace(ev.target.value); });
});
