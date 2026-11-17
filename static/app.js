"use strict";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmtS = (s) => { s = Math.round(s); return s >= 60 ? `${Math.floor(s/60)} min ${s%60} s` : `${s} s`; };
const fmtDate = (t) => new Date(t * 1000).toLocaleString("es-PA", {dateStyle: "short", timeStyle: "short"});

let STATUS = null;
let enrollBlob = null, audioBlob = null;

// ------------------------------------------------------------------ utilidades
function toast(msg, bad = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : "");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), 4500);
}
async function api(path, opts = {}) {
  const r = await fetch(path, {credentials: "same-origin", ...opts});
  if (r.status === 401) { showLogin(); throw new Error("No autorizado"); }
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : null;
  if (!r.ok) throw new Error(data?.detail || `Error ${r.status}`);
  return data;
}
function upload(path, form, bar) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", path); x.withCredentials = true;
    bar.classList.remove("hidden"); bar.firstElementChild.style.width = "0";
    x.upload.onprogress = (e) => { if (e.lengthComputable) bar.firstElementChild.style.width = (90 * e.loaded / e.total) + "%"; };
    x.onload = () => {
      bar.firstElementChild.style.width = "100%"; setTimeout(() => bar.classList.add("hidden"), 600);
      let d = null; try { d = JSON.parse(x.responseText); } catch {}
      if (x.status === 401) { showLogin(); return reject(new Error("No autorizado")); }
      x.status < 300 ? resolve(d) : reject(new Error(d?.detail || `Error ${x.status}`));
    };
    x.onerror = () => { bar.classList.add("hidden"); reject(new Error("Fallo de red")); };
    x.send(form);
  });
}
function pickMime(kind) {
  const c = kind === "video"
    ? ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm", "video/mp4"]
    : ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  return c.find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || "";
}
const extFor = (mime) => mime.includes("mp4") ? ".mp4" : mime.includes("ogg") ? ".ogg" : ".webm";

// ------------------------------------------------------------------ pestañas
document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === b));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + b.dataset.tab));
  if (b.dataset.tab === "generar") refreshAll();
}));

// ------------------------------------------------------------------ acceso
function showLogin() { $("#login").classList.remove("hidden"); $("#loginToken").focus(); }
$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/login", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token: $("#loginToken").value})});
    $("#login").classList.add("hidden"); init();
  } catch (err) { $("#loginErr").textContent = err.message; }
});

// ------------------------------------------------------------------ 1. sesión de aprendizaje
const PROMPTS = [
  [0, "Mire a la cámara, hombros relajados, labios cerrados con suavidad."],
  [4, "Parpadee con naturalidad. Respire tranquilo."],
  [8, "Asienta levemente con la cabeza, como cuando escucha a un estudiante."],
  [12, "Lea en voz muy baja: «Hoy estudiaremos la estructura de los alcanos.»"],
  [17, "Gire apenas la cabeza a su izquierda… y vuelva al centro."],
  [21, "Ahora apenas a su derecha… y vuelva al centro."],
  [24, "Una sonrisa breve y natural… y vuelva a la expresión neutra."],
  [27, "Mire a la cámara. Mantenga la posición unos segundos más."],
];
const REC_SECONDS = 30;
let camStream = null, recorder = null, recTimer = null;

$("#btnCam").addEventListener("click", async () => {
  try {
    camStream = await navigator.mediaDevices.getUserMedia({
      video: {width: {ideal: 1280}, height: {ideal: 720}, frameRate: {ideal: 25}, facingMode: "user"}, audio: false});
    $("#cam").srcObject = camStream;
    $("#btnRec").disabled = false;
    $("#prompter").textContent = "Ubique su rostro dentro del óvalo y pulse Grabar.";
  } catch (e) {
    toast("No se pudo acceder a la cámara. Requiere HTTPS o localhost y permiso del navegador.", true);
  }
});

$("#btnRec").addEventListener("click", async () => {
  if (!camStream) return;
  $("#btnRec").disabled = true;
  const cd = $("#countdown"); cd.classList.remove("hidden");
  for (const n of [3, 2, 1]) { cd.textContent = n; await new Promise((r) => setTimeout(r, 1000)); }
  cd.classList.add("hidden");
  const mime = pickMime("video");
  const chunks = [];
  recorder = new MediaRecorder(camStream, {mimeType: mime || undefined, videoBitsPerSecond: 8_000_000});
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = () => {
    clearInterval(recTimer);
    $("#recBadge").classList.add("hidden");
    $("#btnStop").disabled = true; $("#btnRec").disabled = false;
    enrollBlob = new Blob(chunks, {type: recorder.mimeType || "video/webm"});
    enrollBlob.ext = extFor(enrollBlob.type);
    $("#avFile").value = "";
    const pv = $("#recPreview"); pv.src = URL.createObjectURL(enrollBlob); pv.classList.remove("hidden");
    $("#prompter").textContent = "Grabación lista. Revísela a la derecha y pulse «Analizar video».";
    updateAvBtn();
  };
  recorder.start(1000);
  const t0 = Date.now();
  $("#recBadge").classList.remove("hidden"); $("#btnStop").disabled = false;
  recTimer = setInterval(() => {
    const s = (Date.now() - t0) / 1000;
    $("#recTime").textContent = Math.floor(s);
    const p = PROMPTS.filter(([t]) => t <= s).pop();
    $("#prompter").innerHTML = `<b>${Math.max(0, Math.ceil(REC_SECONDS - s))} s</b> · ${esc(p[1])}`;
    if (s >= REC_SECONDS) recorder.stop();
  }, 250);
});
$("#btnStop").addEventListener("click", () => recorder && recorder.state === "recording" && recorder.stop());

$("#avFile").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (!f) return;
  enrollBlob = f; enrollBlob.ext = "";
  const pv = $("#recPreview"); pv.src = URL.createObjectURL(f); pv.classList.remove("hidden");
  updateAvBtn();
});
["#avConsent", "#avName"].forEach((s) => $(s).addEventListener("input", updateAvBtn));
function updateAvBtn() { $("#btnUploadAv").disabled = !(enrollBlob && $("#avConsent").checked && $("#avName").value.trim()); }

$("#btnUploadAv").addEventListener("click", async () => {
  const fd = new FormData();
  fd.append("name", $("#avName").value.trim());
  fd.append("consent", "true");
  fd.append("file", enrollBlob, enrollBlob.name || "sesion" + (enrollBlob.ext || ".webm"));
  $("#btnUploadAv").disabled = true;
  $("#quality").innerHTML = '<p class="muted">Subiendo y analizando calidad del rostro…</p>';
  try {
    const av = await upload("/api/avatars", fd, $("#avProgress"));
    $("#quality").innerHTML = qualityHTML(av);
    bindQualityButtons(av);
    loadAvatars();
  } catch (e) { $("#quality").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  updateAvBtn();
});

function qualityHTML(av) {
  const q = av.quality;
  const items = q.checks.map((c) => `<li><span class="${c.passed ? "ok" : "bad"}">${c.passed ? "✔" : "✖"}</span>
    <span>${esc(c.label)}</span><span class="muted">${esc(c.value)}</span>${c.passed ? "" : `<small>${esc(c.hint)}</small>`}</li>`).join("");
  return `<div class="qual"><h3><span>Calidad del material: ${q.score}/100</span>
    <span class="${q.ok ? "ok" : "bad"}">${q.ok ? "Apto" : "No apto"}</span></h3><ul>${items}</ul>
    <div class="row"><button class="btn primary" data-train="${av.id}">Iniciar aprendizaje</button>
    ${q.ok ? "" : `<button class="btn small" data-force="${av.id}">Forzar de todos modos</button>`}</div></div>`;
}
function bindQualityButtons(root = document) {
  document.querySelectorAll("[data-train],[data-force]").forEach((b) => {
    if (b._bound) return; b._bound = true;
    b.addEventListener("click", async () => {
      const id = b.dataset.train || b.dataset.force;
      try {
        await api(`/api/avatars/${id}/train${b.dataset.force ? "?force=true" : ""}`, {method: "POST"});
        toast("Sesión de aprendizaje en cola."); $("#quality").innerHTML = ""; loadAvatars(); pollSoon();
      } catch (e) { toast(e.message, true); }
    });
  });
}

async function loadAvatars() {
  const list = await api("/api/avatars");
  $("#avatarList").innerHTML = list.length ? list.map((a) => {
    const engineNote = a.status === "listo" && STATUS && a.engine !== STATUS.engine
      ? `<span class="pill error">aprendido con ${esc(a.engine)}</span>` : "";
    const canTrain = ["analizado", "error", "listo"].includes(a.status);
    return `<div class="item"><img src="/api/avatars/${a.id}/thumb" alt="">
      <div class="grow"><div class="title">${esc(a.name)}</div>
      <div class="muted">${fmtDate(a.created)} · ${a.quality.seconds} s · calidad ${a.quality.score}/100
      ${a.train_seconds ? ` · aprendizaje en ${fmtS(a.train_seconds)}` : ""}</div></div>
      <span class="pill ${a.status}">${a.status.replace("_", " ")}</span> ${engineNote}
      ${canTrain ? `<button class="btn small" data-${a.quality.ok ? "train" : "force"}="${a.id}">${a.status === "listo" ? "Re-aprender" : "Aprender"}</button>` : ""}
      <button class="btn small danger" data-delav="${a.id}">Eliminar</button></div>`;
  }).join("") : '<p class="muted">Aún no hay avatares. Grabe su primera sesión de aprendizaje.</p>';
  bindQualityButtons();
  document.querySelectorAll("[data-delav]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("¿Eliminar este avatar y sus datos faciales aprendidos?")) return;
    try { await api(`/api/avatars/${b.dataset.delav}`, {method: "DELETE"}); loadAvatars(); } catch (e) { toast(e.message, true); }
  }));
  const ready = list.filter((a) => a.status === "listo");
  const sel = $("#genAvatar"), prev = sel.value;
  sel.innerHTML = ready.length ? ready.map((a) => `<option value="${a.id}">${esc(a.name)}</option>`).join("")
    : '<option value="">— ningún avatar listo —</option>';
  if (ready.some((a) => a.id === prev)) sel.value = prev;
  return list;
}

// ------------------------------------------------------------------ 2. audio
let micStream = null, micRec = null, micTimer = null, meterRAF = null;
$("#btnMic").addEventListener("click", async () => {
  try {
    micStream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, channelCount: 1}});
  } catch { return toast("No se pudo acceder al micrófono (requiere HTTPS o localhost).", true); }
  const mime = pickMime("audio"), chunks = [];
  micRec = new MediaRecorder(micStream, {mimeType: mime || undefined, audioBitsPerSecond: 128000});
  micRec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  micRec.onstop = () => {
    clearInterval(micTimer); cancelAnimationFrame(meterRAF);
    micStream.getTracks().forEach((t) => t.stop());
    audioBlob = new Blob(chunks, {type: micRec.mimeType || "audio/webm"}); audioBlob.ext = extFor(audioBlob.type);
    $("#auFile").value = "";
    const a = $("#micPreview"); a.src = URL.createObjectURL(audioBlob); a.classList.remove("hidden");
    $("#btnMic").disabled = false; $("#btnMicStop").disabled = true; updateAuBtn();
  };
  micRec.start(1000);
  const t0 = Date.now();
  micTimer = setInterval(() => { $("#micTime").textContent = fmtS((Date.now() - t0) / 1000); }, 500);
  $("#btnMic").disabled = true; $("#btnMicStop").disabled = false;
  drawMeter(micStream);
});
$("#btnMicStop").addEventListener("click", () => micRec && micRec.state === "recording" && micRec.stop());
function drawMeter(stream) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const an = ctx.createAnalyser(); an.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(an);
  const buf = new Uint8Array(an.fftSize), cv = $("#meter"), g = cv.getContext("2d");
  cv.width = cv.clientWidth;
  (function loop() {
    an.getByteTimeDomainData(buf);
    g.fillStyle = "#0f140c"; g.fillRect(0, 0, cv.width, cv.height);
    g.strokeStyle = "#8bc34a"; g.beginPath();
    for (let i = 0; i < buf.length; i++) { const x = i / buf.length * cv.width, y = buf[i] / 255 * cv.height; i ? g.lineTo(x, y) : g.moveTo(x, y); }
    g.stroke(); meterRAF = requestAnimationFrame(loop);
  })();
}
$("#auFile").addEventListener("change", (e) => { audioBlob = e.target.files[0] || null; if (audioBlob) audioBlob.ext = ""; updateAuBtn(); });
function updateAuBtn() { $("#btnUploadAu").disabled = !audioBlob; }
$("#btnUploadAu").addEventListener("click", async () => {
  const fd = new FormData();
  fd.append("name", $("#auName").value.trim());
  fd.append("file", audioBlob, audioBlob.name || "grabacion" + (audioBlob.ext || ".webm"));
  $("#btnUploadAu").disabled = true;
  try {
    const a = await upload("/api/audios", fd, $("#auProgress"));
    toast(`Audio guardado (${fmtS(a.seconds)}).`);
    audioBlob = null; $("#auFile").value = ""; $("#auName").value = ""; $("#micPreview").classList.add("hidden");
    loadAudios();
  } catch (e) { toast(e.message, true); }
  updateAuBtn();
});
async function loadAudios() {
  const list = await api("/api/audios");
  $("#audioList").innerHTML = list.length ? list.map((a) => `<div class="item">
    <div class="grow"><div class="title">${esc(a.name)}</div><div class="muted">${fmtS(a.seconds)} · ${fmtDate(a.created)}</div></div>
    <audio controls preload="none" src="/api/audios/${a.id}/file"></audio>
    <button class="btn small danger" data-delau="${a.id}">Eliminar</button></div>`).join("")
    : '<p class="muted">Aún no hay audios.</p>';
  document.querySelectorAll("[data-delau]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("¿Eliminar este audio?")) return;
    await api(`/api/audios/${b.dataset.delau}`, {method: "DELETE"}); loadAudios();
  }));
  const sel = $("#genAudio"), prev = sel.value;
  sel.innerHTML = list.length ? list.map((a) => `<option value="${a.id}">${esc(a.name)} (${fmtS(a.seconds)})</option>`).join("")
    : '<option value="">— sin audios —</option>';
  if (list.some((a) => a.id === prev)) sel.value = prev;
}

// ------------------------------------------------------------------ 3. generación
$("#btnGen").addEventListener("click", async () => {
  const avatar_id = $("#genAvatar").value, audio_id = $("#genAudio").value;
  if (!avatar_id || !audio_id) return toast("Seleccione un avatar listo y un audio.", true);
  try {
    await api("/api/generate", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({avatar_id, audio_id, title: $("#genTitle").value, watermark: $("#genWm").checked})});
    $("#genTitle").value = ""; toast("Video en cola de generación."); pollSoon();
  } catch (e) { toast(e.message, true); }
});

const openLogs = new Set();
async function loadJobs() {
  const list = await api("/api/jobs");
  const active = list.filter((j) => ["en_cola", "procesando"].includes(j.status));
  const detail = await Promise.all(list.slice(0, 12).map((j) =>
    (openLogs.has(j.id) || active.includes(j)) ? api(`/api/jobs/${j.id}`) : j));
  $("#jobList").innerHTML = detail.length ? detail.map((j) => {
    const dur = j.finished && j.started ? ` · ${fmtS(j.finished - j.started)}` : "";
    const label = j.kind === "aprendizaje" ? `Aprendizaje · ${esc(j.payload.name)}` : `Video · ${esc(j.payload.title)}`;
    const showLog = j.log && (openLogs.has(j.id) || j.status === "procesando");
    return `<div class="item" style="display:block"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <div class="grow"><div class="title">${label}</div><div class="muted">${fmtDate(j.created)}${dur}
      ${j.error ? ` · <span class="err">${esc(j.error)}</span>` : ""}</div></div>
      <span class="pill ${j.status}">${j.status.replace("_", " ")}</span>
      <button class="btn small" data-log="${j.id}">${openLogs.has(j.id) ? "Ocultar" : "Ver"} bitácora</button></div>
      ${showLog ? `<div class="log">${esc(j.log.join("\n"))}</div>` : ""}</div>`;
  }).join("") : '<p class="muted">Sin trabajos.</p>';
  document.querySelectorAll("[data-log]").forEach((b) => b.addEventListener("click", () => {
    openLogs.has(b.dataset.log) ? openLogs.delete(b.dataset.log) : openLogs.add(b.dataset.log); loadJobs();
  }));
  document.querySelectorAll(".log").forEach((l) => (l.scrollTop = l.scrollHeight));
  return active.length;
}
async function loadOutputs() {
  const list = await api("/api/outputs");
  $("#outList").innerHTML = list.length ? list.map((o) => `<div class="vcard">
    <video controls preload="none" poster="/api/outputs/${o.id}/thumb" src="/api/outputs/${o.id}/file"></video>
    <div class="meta"><div class="title">${esc(o.title)}</div>
    <div class="muted">${fmtS(o.seconds)} · ${esc(o.engine)} · generado en ${fmtS(o.render_seconds)}</div>
    <div class="row"><a class="btn small primary" href="/api/outputs/${o.id}/file?download=true">Descargar MP4</a>
    <button class="btn small danger" data-delout="${o.id}">Eliminar</button></div></div></div>`).join("")
    : '<p class="muted">Aún no hay videos generados.</p>';
  document.querySelectorAll("[data-delout]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("¿Eliminar este video?")) return;
    await api(`/api/outputs/${b.dataset.delout}`, {method: "DELETE"}); loadOutputs();
  }));
}

// ------------------------------------------------------------------ sondeo
let pollT = null, lastActive = 0;
async function refreshAll() {
  try {
    const [, , active] = await Promise.all([loadAvatars(), loadAudios(), loadJobs()]);
    if (active < lastActive) loadOutputs();
    lastActive = active;
    return active;
  } catch { return 0; }
}
function pollSoon() { clearTimeout(pollT); pollT = setTimeout(poll, 800); }
async function poll() { const active = await refreshAll(); pollT = setTimeout(poll, active ? 2500 : 15000); }

async function init() {
  STATUS = await fetch("/api/status", {credentials: "same-origin"}).then((r) => r.json());
  const names = {musetalk: "MuseTalk · GPU", wav2lip: "Wav2Lip · CPU", mock: "Modo de prueba"};
  $("#engineBadge").textContent = "Motor: " + (names[STATUS.engine] || STATUS.engine);
  const w = $("#engineWarn");
  if (STATUS.engine_problems.length) {
    w.innerHTML = "<b>El motor no está listo:</b> " + STATUS.engine_problems.map(esc).join(" · ") +
      ". Ejecute el instalador correspondiente (ver README).";
    w.classList.remove("hidden");
  } else if (STATUS.engine === "mock") {
    w.innerHTML = "<b>Modo de prueba:</b> el video final repite su grabación con el audio, sin mover los labios.";
    w.classList.remove("hidden");
  } else w.classList.add("hidden");
  if (STATUS.auth_required && !STATUS.authenticated) return showLogin();
  await refreshAll(); await loadOutputs(); poll();
}
init();
