const el = (id) => document.getElementById(id);
const logEl = el("log");
const statusPill = el("statusPill");

function setStatus(text, ok = true) {
  statusPill.textContent = text;
  statusPill.classList.toggle("ok", ok);
  statusPill.classList.toggle("bad", !ok);
}

function logLine(text, kind = "") {
  const prefix = kind ? `[${kind}] ` : "";
  logEl.textContent += prefix + text + "\n";
  logEl.scrollTop = logEl.scrollHeight;
}

const nativeFns = new Map();
const pending = new Map();
let lastResultId = 0;

function getBackend() {
  const backend = window.__JUCE__ && window.__JUCE__.backend;
  if (!backend) throw new Error("window.__JUCE__.backend 不可用");
  return backend;
}

function ensurePromiseWireup() {
  const backend = getBackend();
  if (ensurePromiseWireup._wired) return;
  ensurePromiseWireup._wired = true;

  backend.addEventListener("__juce__complete", (event) => {
    const payload = event && event.detail ? event.detail : event;
    const resultId = payload && (payload.resultId ?? payload.promiseId);
    const result = payload && payload.result;
    if (resultId === undefined || resultId === null) return;

    if (pending.has(resultId)) {
      pending.get(resultId)(result);
      pending.delete(resultId);
    }
  });
}

function getNativeFunction(name) {
  ensurePromiseWireup();
  if (nativeFns.has(name)) return nativeFns.get(name);

  const backend = getBackend();
  const f = (...params) => {
    const resultId = lastResultId++;
    const p = new Promise((resolve) => pending.set(resultId, resolve));
    backend.emitEvent("__juce__invoke", { name, params, resultId, promiseId: resultId });
    return p;
  };

  nativeFns.set(name, f);
  return f;
}

async function callNative(name, args = []) {
  return await getNativeFunction(name)(...args);
}

function applyState(s) {
  if (!s) return;
  el("pluginName").textContent = s.pluginName || "未加载";
  el("inPath").textContent = s.inputPath || "";
  el("outPath").textContent = s.outputPath || "";
  el("blockSize").value = (s.blockSize || 1024).toString();
}

async function refresh() {
  try {
    const s = await callNative("refreshState");
    if (s.ok === false) throw new Error(s.error || "刷新失败");
    applyState(s);
    setStatus("已刷新", true);
  } catch (e) {
    setStatus("错误", false);
    logLine(e.message || String(e), "ERR");
  }
}

el("refreshBtn").addEventListener("click", refresh);

el("applyBlockBtn").addEventListener("click", async () => {
  try {
    const bs = parseInt(el("blockSize").value || "1024", 10);
    const s = await callNative("setBlockSize", [bs]);
    if (s.ok === false) throw new Error(s.error || "设置失败");
    applyState(s);
    setStatus("BlockSize 已应用", true);
  } catch (e) {
    setStatus("错误", false);
    logLine(e.message || String(e), "ERR");
  }
});

el("choosePluginBtn").addEventListener("click", async () => {
  try {
    const s = await callNative("choosePlugin");
    if (s.ok === false) throw new Error(s.error || "加载失败");
    applyState(s);
    setStatus("插件已加载", true);
    logLine("插件: " + (s.pluginName || ""), "OK");
  } catch (e) {
    setStatus("错误", false);
    logLine(e.message || String(e), "ERR");
  }
});

el("openEditorBtn").addEventListener("click", async () => {
  try {
    const r = await callNative("openPluginEditor");
    if (r.ok === false) throw new Error(r.error || "打开失败");
    setStatus("已打开插件界面", true);
  } catch (e) {
    setStatus("错误", false);
    logLine(e.message || String(e), "ERR");
  }
});

el("chooseInBtn").addEventListener("click", async () => {
  try {
    const s = await callNative("chooseInputAudio");
    if (s.ok === false) throw new Error(s.error || "选择失败");
    applyState(s);
    setStatus("已选择输入", true);
  } catch (e) {
    setStatus("错误", false);
    logLine(e.message || String(e), "ERR");
  }
});

el("chooseOutBtn").addEventListener("click", async () => {
  try {
    const s = await callNative("chooseOutputAudio");
    if (s.ok === false) throw new Error(s.error || "选择失败");
    applyState(s);
    setStatus("已选择输出", true);
  } catch (e) {
    setStatus("错误", false);
    logLine(e.message || String(e), "ERR");
  }
});

el("startBtn").addEventListener("click", async () => {
  try {
    setStatus("处理中…", true);
    logLine("开始离线处理", "RUN");
    const r = await callNative("startProcess");
    if (r.ok === false) throw new Error(r.error || "处理失败");
    setStatus("完成", true);
    if (r.stats) {
      logLine("输出通道数: " + r.stats.outputChannels, "OK");
      logLine("输入 RMS (dB): " + r.stats.inputRmsDb.toFixed(2), "OK");
      logLine("差异 RMS (dB): " + r.stats.diffRmsDb.toFixed(2), "OK");
      logLine("最大差异: " + r.stats.maxAbsDiff.toFixed(6), "OK");
    }
    if (r.outputPath) logLine("输出: " + r.outputPath, "OK");
    await refresh();
  } catch (e) {
    setStatus("错误", false);
    logLine(e.message || String(e), "ERR");
  }
});

el("processArrayBtn").addEventListener("click", async () => {
  try {
    const sr = parseFloat(el("sampleRate").value || "44100");
    const text = el("arrayIn").value || "";
    setStatus("处理中…", true);
    const r = await callNative("processArray", [sr, text]);
    if (r.ok === false) throw new Error(r.error || "处理失败");
    el("arrayOut").value = r.outputText || "";
    setStatus("数组处理完成", true);
  } catch (e) {
    setStatus("错误", false);
    logLine(e.message || String(e), "ERR");
  }
});

el("copyOutBtn").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(el("arrayOut").value || "");
    setStatus("已复制输出", true);
  } catch (e) {
    logLine("复制失败: " + (e.message || String(e)), "ERR");
  }
});

el("clearBtn").addEventListener("click", () => {
  el("arrayIn").value = "";
  el("arrayOut").value = "";
  setStatus("已清空", true);
});

refresh();
