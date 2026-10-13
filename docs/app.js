// app.js - camera, MediaPipe, drawing, sound and voice for the browser demo.
// The detection rules themselves are in logic.js (a port of the Python app).
import { FaceLandmarker, FilesetResolver } from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/vision_bundle.mjs";
import { CFG, DriverMonitor, LEVEL_NAMES, MOUTH_OUTLINE, driveContext, measureFace } from "./logic.js";

const WASM = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/wasm";
const MODEL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";

const MESSAGES = {
  wake_up: { en: "Wake up! Please stay alert." },
  tired: { en: "You seem tired. Please take a break soon." },
  very_tired: { en: "Warning. High fatigue detected. Please stop the vehicle and rest." },
  distracted: { en: "Please keep your eyes on the road." },
};

const synth = window.speechSynthesis || { cancel() {}, speak() {}, getVoices() { return []; }, speaking: false };
const $ = (id) => document.getElementById(id);
const video = $("video"), overlay = $("overlay"), octx = overlay.getContext("2d");
const chart = $("chart"), cctx = chart.getContext("2d");

let landmarker = null, stream = null, running = false, monitor = null;
let startTime = 0, lastState = null, lang = "en", soundOn = true;
let frames = 0, fpsT = performance.now(), fps = 0, lastVideoTime = -1;
const history = [];            // [t, ear, limit, closed] for the chart
window.__bts = { ready: false, state: null, fps: 0, events: [] };   // read by tests

// ------------------------------------------------------------ setup
async function loadModel() {
  const files = await FilesetResolver.forVisionTasks(WASM);
  const opts = (delegate) => ({
    baseOptions: { modelAssetPath: MODEL, delegate },
    runningMode: "VIDEO", numFaces: 1,
    minFaceDetectionConfidence: 0.5, minFacePresenceConfidence: 0.5, minTrackingConfidence: 0.5,
  });
  try {
    return await FaceLandmarker.createFromOptions(files, opts("GPU"));
  } catch (e) {
    console.warn("GPU not available, using CPU", e);
    return await FaceLandmarker.createFromOptions(files, opts("CPU"));
  }
}

async function start() {
  const btn = $("startBtn");
  btn.disabled = true;
  showError("");
  unlockAudio();
  try {
    setBanner("calibrating", "Starting…", "Loading face model");
    const camPromise = navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
    const [s, lm] = await Promise.all([camPromise, landmarker ? Promise.resolve(landmarker) : loadModel()]);
    stream = s; landmarker = lm;
    video.srcObject = stream;
    await video.play();
  } catch (e) {
    btn.disabled = false;
    stopStream();
    setBanner("idle", "Camera off", "");
    const name = e && e.name;
    showError(name === "NotAllowedError" ? "Camera permission was blocked. Allow the camera in your browser's address bar and try again."
      : name === "NotFoundError" ? "No camera was found on this device."
      : !window.isSecureContext ? "The camera only works on an https:// page."
      : "Could not start: " + (e && e.message ? e.message : e));
    return;
  }
  $("intro").hidden = true;
  $("stopBtn").disabled = false; $("recalBtn").disabled = false;
  monitor = new DriverMonitor(CFG);
  startTime = performance.now() / 1000;
  history.length = 0; clearEvents();
  running = true; window.__bts.ready = true;
  requestWakeLock();
  loop();
}

function stopStream() {
  if (stream) stream.getTracks().forEach((t) => t.stop());
  stream = null;
}

function stop() {
  running = false;
  stopStream();
  alarm(false); flash(false);
  synth.cancel();
  octx.clearRect(0, 0, overlay.width, overlay.height);
  $("intro").hidden = false; $("startBtn").disabled = false; $("startBtn").textContent = "Start again";
  $("stopBtn").disabled = true; $("recalBtn").disabled = true; $("calib").hidden = true;
  setBanner("idle", "Camera off", "");
  $("fps").textContent = "";
}

// ------------------------------------------------------------ main loop
function loop() {
  if (!running) return;
  if (video.readyState >= 2 && video.currentTime !== lastVideoTime) {
    lastVideoTime = video.currentTime;
    const nowMs = performance.now();
    const res = landmarker.detectForVideo(video, nowMs);
    const w = video.videoWidth, h = video.videoHeight;
    const face = res.faceLandmarks && res.faceLandmarks.length ? measureFace(res.faceLandmarks[0], w, h) : null;
    const now = nowMs / 1000;
    const ctx = driveContext(CFG, new Date(), now - startTime);
    const st = monitor.update(face, now, ctx);
    lastState = st;
    window.__bts.state = { status: st.status, ear: st.ear, threshold: st.threshold, fatigue: st.fatigue,
      drowsyReason: st.drowsyReason, distractReason: st.distractReason, pitch: st.head.pitchDelta, yaw: st.head.yawDelta };
    draw(face, st, w, h);
    render(st, now);
    handleEvents(st, now);
    frames++;
    if (nowMs - fpsT > 1000) { fps = frames * 1000 / (nowMs - fpsT); frames = 0; fpsT = nowMs; window.__bts.fps = fps;
      $("fps").textContent = fps.toFixed(0) + " frames/s"; }
  }
  if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(loop);
  else requestAnimationFrame(loop);
}

// ------------------------------------------------------------ drawing
function draw(face, st, w, h) {
  if (overlay.width !== w || overlay.height !== h) { overlay.width = w; overlay.height = h; }
  octx.clearRect(0, 0, w, h);
  if (!face) return;
  const col = st.status === "DROWSY" ? "#ff4b44" : st.eyesClosed ? "#f0b429" : st.status === "CALIBRATING" ? "#f7c600" : "#3fd68f";
  octx.lineWidth = Math.max(2, w / 320);
  for (const eye of face.eyes) {
    octx.strokeStyle = col;
    octx.beginPath();
    [0, 1, 2, 3, 4, 5, 0].forEach((k, i) => (i ? octx.lineTo(...eye[k]) : octx.moveTo(...eye[k])));
    octx.stroke();
    octx.fillStyle = col;
    for (const p of eye) { octx.beginPath(); octx.arc(p[0], p[1], octx.lineWidth * 1.1, 0, 7); octx.fill(); }
  }
  octx.strokeStyle = st.yawning ? "#b18cff" : "rgba(255,255,255,.55)";
  octx.beginPath();
  MOUTH_OUTLINE.concat(MOUTH_OUTLINE[0]).forEach((k, i) => (i ? octx.lineTo(...face.pts[k]) : octx.moveTo(...face.pts[k])));
  octx.stroke();
}

const STATE_UI = {
  CALIBRATING: ["calibrating", "Calibrating"],
  AWAKE: ["awake", "Awake"],
  "EYES CLOSED": ["closed", "Eyes closed"],
  DROWSY: ["drowsy", "Drowsy – wake up!"],
  DISTRACTED: ["distracted", "Distracted"],
  "NO FACE": ["noface", "No face"],
};

function render(st, now) {
  const [cls, label] = STATE_UI[st.status] || ["idle", st.status];
  let detail = "";
  if (st.status === "CALIBRATING") detail = "Learning your normal eye opening";
  else if (st.status === "DROWSY") detail = st.drowsyReason;
  else if (st.status === "DISTRACTED") detail = st.distractReason;
  else if (st.status === "EYES CLOSED") detail = st.closedFor.toFixed(1) + " s";
  else if (st.status === "NO FACE") detail = "Move into the camera view";
  else if (st.yawning) detail = "Yawning";
  setBanner(cls, label, detail);

  $("calib").hidden = st.status !== "CALIBRATING";
  if (st.status === "CALIBRATING") $("calibFill").style.width = ((st.progress || 0) * 100) + "%";

  const f = Math.round(st.fatigue || 0);
  $("fatigueVal").textContent = f;
  $("needle").style.left = Math.min(100, f) + "%";
  const lt = $("levelTag");
  lt.dataset.level = st.level; lt.textContent = LEVEL_NAMES[st.level];

  const calib = st.status === "CALIBRATING";
  $("mEar").textContent = st.ear == null ? "–" : st.ear.toFixed(3);
  $("mThr").textContent = calib ? "limit after calibration" : "limit " + (st.threshold * st.thrScale).toFixed(3);
  $("mPerclos").textContent = calib ? "–" : (st.perclos * 100).toFixed(1) + "%";
  $("mBlinks").textContent = calib ? "–" : monitor.eyes.blinksPerMinute(now).toFixed(0);
  $("mBlinkTotal").textContent = st.blinks + " total";
  const hd = st.head;
  $("mHead").textContent = hd.pitchDelta == null ? "–" : `${fmtDeg(hd.pitchDelta)} / ${fmtDeg(hd.yawDelta)}`;
  $("mYawn").textContent = `${st.yawns} · ${st.nods}`;
  $("mMar").textContent = st.mar == null ? "mouth –" : "mouth " + st.mar.toFixed(2);
  $("mAlarm").textContent = `${st.drowsyEvents} · ${st.distractions}`;

  if (st.ear != null && !calib) history.push([now, st.ear, st.threshold * st.thrScale, st.eyesClosed]);
  while (history.length && now - history[0][0] > 20) history.shift();
  drawChart(now);
  flash(st.status === "DROWSY");
}
const fmtDeg = (v) => (v > 0 ? "+" : "") + v.toFixed(0) + "°";

function drawChart(now) {
  const dpr = window.devicePixelRatio || 1;
  const W = chart.clientWidth, H = chart.clientHeight;
  if (chart.width !== Math.round(W * dpr)) { chart.width = Math.round(W * dpr); chart.height = Math.round(H * dpr); }
  cctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  cctx.clearRect(0, 0, W, H);
  const pad = { l: 30, r: 6, t: 6, b: 16 };
  const x = (t) => pad.l + (W - pad.l - pad.r) * (1 - (now - t) / 20);
  const yMax = 0.45, y = (v) => pad.t + (H - pad.t - pad.b) * (1 - Math.min(v, yMax) / yMax);
  cctx.font = "11px Barlow, sans-serif"; cctx.fillStyle = "#6b7a71"; cctx.strokeStyle = "#e1e5e0"; cctx.lineWidth = 1;
  for (const v of [0, 0.1, 0.2, 0.3, 0.4]) {
    cctx.beginPath(); cctx.moveTo(pad.l, y(v)); cctx.lineTo(W - pad.r, y(v)); cctx.stroke();
    cctx.fillText(v.toFixed(1), 4, y(v) + 4);
  }
  cctx.fillText("now", W - pad.r - 20, H - 3); cctx.fillText("−20 s", pad.l, H - 3);
  if (history.length < 2) return;
  // shade eye-closed periods
  cctx.fillStyle = "rgba(198,47,43,.14)";
  for (let i = 1; i < history.length; i++) if (history[i][3]) cctx.fillRect(x(history[i - 1][0]), pad.t, x(history[i][0]) - x(history[i - 1][0]) + 0.5, H - pad.t - pad.b);
  const line = (k, color, width) => {
    cctx.strokeStyle = color; cctx.lineWidth = width; cctx.beginPath();
    history.forEach((h, i) => (i ? cctx.lineTo(x(h[0]), y(h[k])) : cctx.moveTo(x(h[0]), y(h[k]))));
    cctx.stroke();
  };
  line(2, "#c62f2b", 1.5);
  line(1, "#0e6b4a", 1.5);
}

function setBanner(state, label, detail) {
  const b = $("banner");
  if (b.dataset.state !== state) b.dataset.state = state;
  if ($("bannerLabel").textContent !== label) $("bannerLabel").textContent = label;
  if ($("bannerDetail").textContent !== detail) $("bannerDetail").textContent = detail;
}

function flash(on) { $("flash").classList.toggle("on", on); }
function showError(msg) { const e = $("error"); e.textContent = msg; e.hidden = !msg; }

// ------------------------------------------------------------ events, sound, voice
const lastSpoken = {};
let wakeRepeat = 0;
function handleEvents(st, now) {
  for (const ev of st.events) {
    logEvent(ev, st, now);
    window.__bts.events.push(ev);
    if (ev === "drowsy") { alarm(true); say("wake_up", true); wakeRepeat = now; }
    if (ev === "distracted" && st.status !== "DROWSY" && cooled("distracted", now, 8)) { chime([660, 880]); say("distracted", true); }
    if (ev === "level_up") {
      const id = st.fatigueLevel >= 2 ? "very_tired" : "tired";
      if (cooled(id, now, 45)) { chime([523, 659]); say(id, false); }
    }
  }
  if (st.status !== "DROWSY") alarm(false);
  else if (now - wakeRepeat > 5) { say("wake_up", true); wakeRepeat = now; }
}
function cooled(id, now, sec) {
  if (lastSpoken[id] && now - lastSpoken[id] < sec) return false;
  lastSpoken[id] = now; return true;
}

const EVENT_UI = {
  drowsy: ["drowsy", "DROWSY", (s) => s.drowsyReason + " – alarm"],
  distracted: ["distracted", "DISTRACTED", (s) => s.distractReason],
  yawn: ["yawn", "YAWN", () => "Mouth wide open for over 1 s"],
  nod: ["nod", "NOD", () => "Head dipped and came back up"],
  slow_blink: ["slow", "SLOW BLINK", () => "Eyes closed 0.5–1.5 s"],
  level_up: ["level", "LEVEL", (s) => "Fatigue " + Math.round(s.fatigue) + " → " + LEVEL_NAMES[s.fatigueLevel]],
};
function clearEvents() { $("events").innerHTML = '<li class="muted">Nothing yet.</li>'; }
function logEvent(ev, st, now) {
  const ui = EVENT_UI[ev]; if (!ui) return;
  const list = $("events");
  if (list.firstElementChild && list.firstElementChild.classList.contains("muted")) list.innerHTML = "";
  const li = document.createElement("li");
  const t = now - startTime;
  li.innerHTML = `<time>${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}</time><span class="tag ${ui[0]}">${ui[1]}</span><span></span>`;
  li.lastChild.textContent = ui[2](st);
  list.prepend(li);
  while (list.children.length > 40) list.lastChild.remove();
}

let actx = null, alarmTimer = null;
function unlockAudio() {
  if (!actx) { try { actx = new (window.AudioContext || window.webkitAudioContext)(); } catch { actx = null; } }
  if (actx && actx.state === "suspended") actx.resume();
}
function tone(freq, start, dur, type = "sine", vol = 0.2) {
  if (!actx || !soundOn) return;
  const o = actx.createOscillator(), g = actx.createGain();
  o.type = type; o.frequency.value = freq;
  g.gain.setValueAtTime(0, start);
  g.gain.linearRampToValueAtTime(vol, start + 0.01);
  g.gain.setValueAtTime(vol, start + dur - 0.03);
  g.gain.linearRampToValueAtTime(0, start + dur);
  o.connect(g).connect(actx.destination);
  o.start(start); o.stop(start + dur + 0.02);
}
function chime(freqs) {
  if (!actx) return;
  freqs.forEach((f, i) => tone(f, actx.currentTime + i * 0.16, 0.22, "sine", 0.18));
}
function alarm(on) {
  if (on && !alarmTimer) {
    const beep = () => { if (!actx) return; const t = actx.currentTime; tone(988, t, 0.18, "square", 0.12); tone(740, t + 0.22, 0.18, "square", 0.12); };
    beep(); alarmTimer = setInterval(beep, 500);
  } else if (!on && alarmTimer) { clearInterval(alarmTimer); alarmTimer = null; }
}

let clip = null;
function say(id, urgent) {
  if (!soundOn) return;
  if (urgent) { synth.cancel(); if (clip) { clip.pause(); clip = null; } }
  else if (synth.speaking || (clip && !clip.paused)) return;
  if (lang === "en") {
    if (!window.SpeechSynthesisUtterance) return;
    const u = new SpeechSynthesisUtterance(MESSAGES[id].en);
    const v = synth.getVoices().find((x) => /en[-_]IN/i.test(x.lang)) || synth.getVoices().find((x) => /^en/i.test(x.lang));
    if (v) u.voice = v;
    u.rate = 1.05;
    synth.speak(u);
  } else {
    clip = new Audio(`voices/${lang}/${id}.mp3`);
    clip.play().catch(() => {});
  }
}

let wakeLock = null;
async function requestWakeLock() {
  try { if ("wakeLock" in navigator) wakeLock = await navigator.wakeLock.request("screen"); } catch { /* not supported */ }
}
document.addEventListener("visibilitychange", () => { if (running && document.visibilityState === "visible") requestWakeLock(); });

// ------------------------------------------------------------ controls
$("startBtn").addEventListener("click", start);
$("stopBtn").addEventListener("click", stop);
$("recalBtn").addEventListener("click", () => { if (monitor) { monitor.recalibrate(); history.length = 0; } });
document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
  lang = b.dataset.lang;
  document.querySelectorAll(".seg button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", x === b); });
  unlockAudio(); say("distracted", true);     // short sample so you hear the language
}));
$("soundChk").addEventListener("change", (e) => {
  soundOn = e.target.checked;
  if (!soundOn) { alarm(false); synth.cancel(); if (clip) clip.pause(); }
  else if (lastState && lastState.status === "DROWSY") alarm(true);
});
synth.getVoices();
if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
  showError(window.isSecureContext ? "This browser cannot use the camera. Try Chrome, Edge, Firefox or Safari." : "The camera only works on an https:// page.");
  $("startBtn").disabled = true;
}
