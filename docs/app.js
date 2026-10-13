// app.js - camera, MediaPipe, drawing, sound, voice, themes and trip report
// for the browser demo. The detection rules are in logic.js (a port of the
// Python app's detector.py and monitor.py).
import { FaceLandmarker, FilesetResolver } from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/vision_bundle.mjs";
import { CFG, DriverMonitor, LEVEL_NAMES, MOUTH_OUTLINE, driveContext, measureFace } from "./logic.js";

const WASM = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/wasm";
const MODEL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
const BREAK_AFTER = 2 * 3600, BREAK_REPEAT = 30 * 60;      // same as the Python app

const MESSAGES = {
  wake_up: "Wake up! Please stay alert.",
  tired: "You seem tired. Please take a break soon.",
  very_tired: "Warning. High fatigue detected. Please stop the vehicle and rest.",
  distracted: "Please keep your eyes on the road.",
  long_drive: "You have been driving for a long time. Please take a short break.",
  night: "Night driving. The risk of drowsiness is high. Please stay alert.",
};

const synth = window.speechSynthesis || { cancel() {}, speak() {}, getVoices() { return []; }, speaking: false };
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};
const $ = (id) => document.getElementById(id);
const video = $("video"), overlay = $("overlay"), octx = overlay.getContext("2d");
const chart = $("chart"), cctx = chart.getContext("2d");
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

let landmarker = null, stream = null, running = false, monitor = null, cfg = { ...CFG };
let lastState = null, lang = "en", soundOn = true, chartMode = "ear", trip = null;
let frames = 0, fpsT = performance.now(), lastVideoTime = -1;
const history = [];            // [t, ear, limit, closed] for the eye chart (last 20 s)
window.__bts = { ready: false, state: null, fps: 0, events: [], trip: null };   // read by tests

// ------------------------------------------------------------ setup
async function loadModel() {
  const files = await FilesetResolver.forVisionTasks(WASM);
  const opts = (delegate) => ({
    baseOptions: { modelAssetPath: MODEL, delegate },
    runningMode: "VIDEO", numFaces: 1,
    minFaceDetectionConfidence: 0.5, minFacePresenceConfidence: 0.5, minTrackingConfidence: 0.5,
  });
  try { return await FaceLandmarker.createFromOptions(files, opts("GPU")); }
  catch (e) { console.warn("GPU not available, using CPU", e); return await FaceLandmarker.createFromOptions(files, opts("CPU")); }
}

async function start() {
  const btn = $("startBtn");
  btn.disabled = true;
  showError("");
  unlockAudio();
  try {
    setBanner("calibrating", "Starting…", "Loading face model");
    const cam = navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
    const [s, lm] = await Promise.all([cam, landmarker ? Promise.resolve(landmarker) : loadModel()]);
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
  ["stopBtn", "recalBtn", "driveBtn", "reportBtn"].forEach((id) => ($(id).disabled = false));
  monitor = new DriverMonitor(cfg);
  const now = performance.now() / 1000;
  trip = { startDate: new Date(), t0: now, last: now, series: [], perclos: [], events: [], lastSample: -1,
    nightWarned: false, nextBreak: BREAK_AFTER, alarmTimes: [], sosDismissedAt: -1 };
  window.__bts.trip = trip;
  history.length = 0; clearEvents();
  running = true; window.__bts.ready = true;
  requestWakeLock();
  loop();
}

function stopStream() {
  if (stream) stream.getTracks().forEach((t) => t.stop());
  stream = null;
}

function endTrip() {
  running = false;
  stopStream();
  alarm(false); flash(false); setDriving(false);
  synth.cancel();
  octx.clearRect(0, 0, overlay.width, overlay.height);
  $("intro").hidden = false; $("startBtn").disabled = false; $("startBtn").textContent = "Start a new trip";
  ["stopBtn", "recalBtn", "driveBtn"].forEach((id) => ($(id).disabled = true));
  $("calib").hidden = true; $("lightChip").hidden = true;
  setBanner("idle", "Trip ended", "");
  $("fps").textContent = "";
  if (trip && trip.series.length > 3) openReport();
}

// ------------------------------------------------------------ main loop
function loop() {
  if (!running) return;
  if (video.readyState >= 2 && video.currentTime !== lastVideoTime) {
    lastVideoTime = video.currentTime;
    const nowMs = performance.now(), now = nowMs / 1000;
    const res = landmarker.detectForVideo(video, nowMs);
    const w = video.videoWidth, h = video.videoHeight;
    const face = res.faceLandmarks && res.faceLandmarks.length ? measureFace(res.faceLandmarks[0], w, h) : null;
    const ctx = driveContext(cfg, new Date(), now - trip.t0);
    const st = monitor.update(face, now, ctx);
    lastState = st;
    window.__bts.state = { status: st.status, ear: st.ear, threshold: st.threshold, fatigue: st.fatigue,
      drowsyReason: st.drowsyReason, distractReason: st.distractReason, pitch: st.head.pitchDelta, yaw: st.head.yawDelta };
    record(st, now, ctx);
    draw(face, st, w, h);
    render(st, now);
    handleEvents(st, now, ctx);
    checkLight(now);
    frames++;
    if (nowMs - fpsT > 1000) {
      window.__bts.fps = frames * 1000 / (nowMs - fpsT); frames = 0; fpsT = nowMs;
      $("fps").textContent = window.__bts.fps.toFixed(0) + " frames/s";
    }
  }
  if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(loop);
  else requestAnimationFrame(loop);
}

// keep one sample per second for the fatigue chart and the trip report
function record(st, now, ctx) {
  trip.last = now;
  if (st.status === "CALIBRATING") return;
  const t = now - trip.t0;
  if (t - trip.lastSample >= 1) {
    trip.lastSample = t;
    trip.series.push([t, st.fatigue, st.level]);
    trip.perclos.push(st.perclos);
  }
  trip.blinks = st.blinks; trip.yawns = st.yawns; trip.nods = st.nods;
  trip.alarms = st.drowsyEvents; trip.distractions = st.distractions; trip.night = ctx.riskHours;
  trip.monitorStart = monitor.eyes.monitorStart;
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
const LEVEL_TEXT = ["You look alert.", "Signs of tiredness – plan a break.", "High fatigue – stop and rest soon.", "Falling asleep – alarm!"];

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
  $("stage").dataset.state = cls;

  $("calib").hidden = st.status !== "CALIBRATING";
  if (st.status === "CALIBRATING") $("calibFill").style.width = ((st.progress || 0) * 100) + "%";

  const f = Math.round(st.fatigue || 0);
  $("fatigueVal").textContent = f;
  const ring = $("ringFill");
  ring.style.strokeDashoffset = 314.16 * (1 - Math.min(100, f) / 100);
  ring.style.stroke = css(["--ok", "--warn", "--high", "--danger"][st.level]);
  const lt = $("levelTag");
  lt.dataset.level = st.level; lt.textContent = LEVEL_NAMES[st.level];
  $("statusLine").textContent = st.status === "CALIBRATING" ? "Calibrating – keep your eyes open." : LEVEL_TEXT[st.level];
  const drive = fmtTime(now - trip.t0);
  $("mTime").textContent = drive;
  $("mAlarm").textContent = st.drowsyEvents;
  $("mDist").textContent = st.distractions;

  const calib = st.status === "CALIBRATING";
  $("mEar").textContent = st.ear == null ? "–" : st.ear.toFixed(3);
  $("mThr").textContent = calib ? "limit after calibration" : "limit " + (st.threshold * st.thrScale).toFixed(3);
  $("mPerclos").textContent = calib ? "–" : (st.perclos * 100).toFixed(1) + "%";
  $("mBlinks").textContent = calib ? "–" : monitor.eyes.blinksPerMinute(now).toFixed(0);
  $("mBlinkTotal").textContent = st.blinks + " total";
  const hd = st.head;
  $("mHead").textContent = hd.pitchDelta == null ? "–" : `${fmtDeg(hd.pitchDelta)} / ${fmtDeg(hd.yawDelta)}`;
  $("mYawn").textContent = st.yawns;
  $("mMar").textContent = st.mar == null ? "mouth –" : "mouth " + st.mar.toFixed(2);
  $("mNod").textContent = `${st.nods} · ${trip.slowBlinks || 0}`;

  // driving-mode heads-up display
  $("hudState").textContent = st.status === "DROWSY" ? "Wake up!" : label;
  $("hudScore").textContent = f;
  $("hudTime").textContent = drive;

  if (st.ear != null && !calib) history.push([now, st.ear, st.threshold * st.thrScale, st.eyesClosed]);
  while (history.length && now - history[0][0] > 20) history.shift();
  drawChart(now);
  flash(st.status === "DROWSY");
}
const fmtDeg = (v) => (v > 0 ? "+" : "") + v.toFixed(0) + "°";
const fmtTime = (s) => { s = Math.max(0, Math.floor(s)); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s % 60).padStart(2, "0"); };

function drawChart(now) {
  const dpr = window.devicePixelRatio || 1;
  const W = chart.clientWidth, H = chart.clientHeight;
  if (!W) return;
  if (chart.width !== Math.round(W * dpr)) { chart.width = Math.round(W * dpr); chart.height = Math.round(H * dpr); }
  cctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  cctx.clearRect(0, 0, W, H);
  const pad = { l: 30, r: 6, t: 6, b: 16 };
  const grid = css("--grid"), muted = css("--muted");
  cctx.font = "11px Barlow, sans-serif"; cctx.lineWidth = 1;

  if (chartMode === "ear") {
    $("legend").innerHTML = `<i style="background:${css("--chart-ear")}"></i>EAR <i style="background:${css("--chart-thr")}"></i>limit`;
    const x = (t) => pad.l + (W - pad.l - pad.r) * (1 - (now - t) / 20);
    const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - Math.min(v, 0.45) / 0.45);
    for (const v of [0, 0.1, 0.2, 0.3, 0.4]) {
      cctx.strokeStyle = grid; cctx.beginPath(); cctx.moveTo(pad.l, y(v)); cctx.lineTo(W - pad.r, y(v)); cctx.stroke();
      cctx.fillStyle = muted; cctx.fillText(v.toFixed(1), 4, y(v) + 4);
    }
    cctx.fillText("now", W - pad.r - 20, H - 3); cctx.fillText("−20 s", pad.l, H - 3);
    if (history.length < 2) return;
    cctx.fillStyle = "rgba(220,60,50,.16)";
    for (let i = 1; i < history.length; i++) if (history[i][3]) cctx.fillRect(x(history[i - 1][0]), pad.t, x(history[i][0]) - x(history[i - 1][0]) + 0.5, H - pad.t - pad.b);
    const line = (k, color) => { cctx.strokeStyle = color; cctx.lineWidth = 1.6; cctx.beginPath();
      history.forEach((p, i) => (i ? cctx.lineTo(x(p[0]), y(p[k])) : cctx.moveTo(x(p[0]), y(p[k])))); cctx.stroke(); };
    line(2, css("--chart-thr"));
    line(1, css("--chart-ear"));
  } else {
    $("legend").innerHTML = `<i style="background:${css("--chart-ear")}"></i>fatigue score`;
    drawFatigue(cctx, W, H, pad, { grid, muted, line: css("--chart-ear"), bands: [css("--ok"), css("--warn"), css("--high")], alarm: css("--danger") },
      trip ? trip.series : [], trip ? trip.events : [], trip ? Math.max(30, trip.last - trip.t0) : 30);
  }
}

// fatigue score over the whole trip (used on the page and in the report)
function drawFatigue(c, W, H, pad, col, series, events, span) {
  const x = (t) => pad.l + (W - pad.l - pad.r) * (t / span);
  const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - v / 100);
  const bands = [[0, 35], [35, 65], [65, 100]];
  bands.forEach(([a, b], i) => { c.globalAlpha = 0.12; c.fillStyle = col.bands[i]; c.fillRect(pad.l, y(b), W - pad.l - pad.r, y(a) - y(b)); });
  c.globalAlpha = 1;
  c.fillStyle = col.muted; c.strokeStyle = col.grid; c.lineWidth = 1;
  for (const v of [0, 35, 65, 100]) { c.beginPath(); c.moveTo(pad.l, y(v)); c.lineTo(W - pad.r, y(v)); c.stroke(); c.fillText(String(v), 4, y(v) + 4); }
  c.fillText("0:00", pad.l, H - 3);
  const endLbl = fmtTime(span); c.fillText(endLbl, W - pad.r - c.measureText(endLbl).width, H - 3);
  for (const e of events) if (e.kind === "drowsy") {
    c.strokeStyle = col.alarm; c.lineWidth = 1.5; c.setLineDash([3, 3]);
    c.beginPath(); c.moveTo(x(e.t), pad.t); c.lineTo(x(e.t), H - pad.b); c.stroke(); c.setLineDash([]);
  }
  if (series.length < 2) return;
  c.strokeStyle = col.line; c.lineWidth = 2; c.beginPath();
  series.forEach((p, i) => (i ? c.lineTo(x(p[0]), y(p[1])) : c.moveTo(x(p[0]), y(p[1]))));
  c.stroke();
}

function setBanner(state, label, detail) {
  const b = $("banner");
  if (b.dataset.state !== state) b.dataset.state = state;
  if ($("bannerLabel").textContent !== label) $("bannerLabel").textContent = label;
  if ($("bannerDetail").textContent !== detail) $("bannerDetail").textContent = detail;
}
function flash(on) { $("flash").classList.toggle("on", on); }
function showError(msg) { const e = $("error"); e.textContent = msg; e.hidden = !msg; }

// ------------------------------------------------------------ low light check
const probe = document.createElement("canvas"); probe.width = 32; probe.height = 24;
const pctx = probe.getContext("2d", { willReadFrequently: true });
let lastLight = 0;
function checkLight(now) {
  if (now - lastLight < 1) return;
  lastLight = now;
  pctx.drawImage(video, 0, 0, 32, 24);
  const d = pctx.getImageData(0, 0, 32, 24).data;
  let sum = 0;
  for (let i = 0; i < d.length; i += 4) sum += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
  $("lightChip").hidden = sum / (d.length / 4) >= 55;
}

// ------------------------------------------------------------ events, sound, voice
const lastSpoken = {};
let wakeRepeat = 0;
function handleEvents(st, now, ctx) {
  for (const ev of st.events) {
    logEvent(ev, st, now);
    window.__bts.events.push(ev);
    if (ev === "drowsy") {
      alarm(true); say("wake_up", true); wakeRepeat = now;
      trip.alarmTimes.push(now);
      const recent = trip.alarmTimes.filter((t) => now - t <= 600).length;
      if (recent >= 2 && now > trip.sosDismissedAt) $("sosCard").hidden = false;
    }
    if (ev === "distracted" && st.status !== "DROWSY" && cooled("distracted", now, 8)) { chime([660, 880]); say("distracted", true); }
    if (ev === "level_up") {
      const id = st.fatigueLevel >= 2 ? "very_tired" : "tired";
      if (cooled(id, now, 45)) { chime([523, 659]); say(id, false); }
    }
  }
  if (st.status !== "DROWSY") alarm(false);
  else if (now - wakeRepeat > 5) { say("wake_up", true); wakeRepeat = now; }

  if (st.status === "CALIBRATING") return;
  if (ctx.riskHours && !trip.nightWarned) {           // night hours: warn once
    trip.nightWarned = true;
    addEvent(now, "info", "NIGHT", "Night driving – more sensitive alarm (1.2 s)");
    say("night", false);
  }
  if (now - trip.t0 >= trip.nextBreak) {             // long drive: break reminder
    trip.nextBreak += BREAK_REPEAT;
    addEvent(now, "info", "BREAK", "Driving over " + fmtTime(now - trip.t0) + " – take a break");
    chime([523, 659]); say("long_drive", false);
  }
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
  addEvent(now, ui[0], ui[1], ui[2](st), ev);
}
function addEvent(now, cls, tag, text, kind = cls) {
  const t = now - trip.t0;
  trip.events.push({ t, kind, tag, text });
  if (kind === "slow_blink") trip.slowBlinks = (trip.slowBlinks || 0) + 1;
  const list = $("events");
  if (list.firstElementChild && list.firstElementChild.classList.contains("muted")) list.innerHTML = "";
  const li = document.createElement("li");
  li.innerHTML = `<time>${fmtTime(t)}</time><span class="tag ${cls}">${tag}</span><span></span>`;
  li.lastChild.textContent = text;
  list.prepend(li);
  while (list.children.length > 60) list.lastChild.remove();
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
function chime(freqs) { if (actx) freqs.forEach((f, i) => tone(f, actx.currentTime + i * 0.16, 0.22, "sine", 0.18)); }
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
    const u = new SpeechSynthesisUtterance(MESSAGES[id]);
    const vs = synth.getVoices();
    const v = vs.find((x) => /en[-_]IN/i.test(x.lang)) || vs.find((x) => /^en/i.test(x.lang));
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

// ------------------------------------------------------------ driving mode
function setDriving(on) {
  const stage = $("stage");
  stage.classList.toggle("driving", on);
  $("driveBtn").textContent = on ? "Exit driving mode" : "Driving mode";
  if (on) { stage.requestFullscreen?.().catch(() => {}); requestWakeLock(); }
  else if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}
document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && $("stage").classList.contains("driving")) setDriving(false); });

// ------------------------------------------------------------ emergency share
async function shareLocation() {
  const n = trip ? trip.alarmTimes.filter((t) => performance.now() / 1000 - t <= 600).length : 0;
  let text = `Blink to Safety alert: the driver had ${n} drowsiness alarms in the last 10 minutes and may need help.`;
  const pos = await new Promise((res) => {
    if (!navigator.geolocation) return res(null);
    navigator.geolocation.getCurrentPosition((p) => res(p), () => res(null), { enableHighAccuracy: true, timeout: 8000 });
  });
  if (pos) text += ` Location: https://maps.google.com/?q=${pos.coords.latitude.toFixed(5)},${pos.coords.longitude.toFixed(5)}`;
  const num = ($("sosNum").value || "").replace(/\D/g, "");
  if (!num && navigator.share) { try { await navigator.share({ text }); return; } catch { /* cancelled */ } }
  window.open(`https://wa.me/${num}?text=${encodeURIComponent(text)}`, "_blank", "noopener");
}

// ------------------------------------------------------------ trip report
function summary() {
  const s = trip.series, dur = Math.max(0, trip.last - trip.t0);
  const fs = s.map((p) => p[1]);
  const avg = fs.length ? fs.reduce((a, b) => a + b, 0) / fs.length : 0;
  const peak = fs.length ? Math.max(...fs) : 0;
  const lvl = s.length ? Math.max(...s.map((p) => p[2])) : 0;
  const per = trip.perclos.length ? trip.perclos.reduce((a, b) => a + b, 0) / trip.perclos.length : 0;
  const monMin = trip.monitorStart ? (trip.last - trip.monitorStart) / 60 : 0;
  return [
    ["Trip time", fmtTime(dur)], ["Drowsiness alarms", trip.alarms || 0], ["Distractions", trip.distractions || 0],
    ["Highest level", LEVEL_NAMES[lvl]], ["Average fatigue", avg.toFixed(0) + " / 100"], ["Peak fatigue", peak.toFixed(0) + " / 100"],
    ["Average PERCLOS", (per * 100).toFixed(1) + "%"], ["Blinks per minute", monMin > 0.25 ? ((trip.blinks || 0) / monMin).toFixed(0) : "–"],
    ["Yawns", trip.yawns || 0], ["Nods", trip.nods || 0],
    ["Slow blinks", trip.slowBlinks || 0], ["Night driving", trip.night ? "Yes" : "No"],
  ];
}
const REPORT_COLORS = { grid: "#e3e7ec", muted: "#6b7280", line: "#1f2937", bands: ["#2f9e6b", "#e8a317", "#d9692f"], alarm: "#c62f2b" };
function renderReportChart() {
  const c = $("repChart"), x = c.getContext("2d");
  x.setTransform(1, 0, 0, 1, 0, 0);
  x.fillStyle = "#ffffff"; x.fillRect(0, 0, c.width, c.height);
  x.font = "20px Barlow, Helvetica, sans-serif";
  x.fillStyle = "#1f2937"; x.fillText("Fatigue score over the trip (dashed red = drowsiness alarm)", 16, 28);
  x.font = "15px Barlow, Helvetica, sans-serif";
  drawFatigue(x, c.width, c.height, { l: 44, r: 16, t: 44, b: 24 }, REPORT_COLORS, trip.series, trip.events, Math.max(30, trip.last - trip.t0));
}
function openReport() {
  if (!trip) return;
  $("repWhen").textContent = "Started " + trip.startDate.toLocaleString("en-IN") + (running ? " · trip still running" : "");
  $("repGrid").innerHTML = summary().map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
  renderReportChart();
  const dlg = $("reportDlg");
  if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
}

function downloadPdf() {
  const J = window.jspdf && window.jspdf.jsPDF;
  if (!J) { alertBox("The PDF tool could not load. Check your internet connection and try again."); return; }
  const doc = new J({ unit: "mm", format: "a4" });
  let accent = hexToRgb(css("--header")) || [14, 107, 74];
  if (0.299 * accent[0] + 0.587 * accent[1] + 0.114 * accent[2] > 200) accent = hexToRgb(css("--accent")) || accent;   // white header (Ocean): use the accent colour
  const W = 210, M = 16;
  doc.setFillColor(...accent); doc.rect(0, 0, W, 30, "F");
  doc.setTextColor(255, 255, 255);
  doc.setFont("helvetica", "bold"); doc.setFontSize(20); doc.text("Blink to Safety - Trip Report", M, 15);
  doc.setFont("helvetica", "normal"); doc.setFontSize(10);
  doc.text("AI-based driver fatigue detection  |  " + trip.startDate.toLocaleString("en-IN"), M, 23);

  // summary in two columns
  doc.setTextColor(31, 41, 55);
  let y = 42;
  doc.setFont("helvetica", "bold"); doc.setFontSize(13); doc.text("Summary", M, y); y += 7;
  const rows = summary();
  doc.setFontSize(10.5);
  rows.forEach(([k, v], i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const cx = M + col * 90, cy = y + row * 7.5;
    if (row % 2 === 0) { doc.setFillColor(243, 245, 247); doc.rect(cx - 2, cy - 5, 88, 7.5, "F"); }
    doc.setFont("helvetica", "normal"); doc.setTextColor(90, 100, 115); doc.text(String(k), cx, cy);
    doc.setFont("helvetica", "bold"); doc.setTextColor(31, 41, 55); doc.text(String(v), cx + 84, cy, { align: "right" });
  });
  y += Math.ceil(rows.length / 2) * 7.5 + 6;

  // verdict line
  const alarms = trip.alarms || 0, lvl = Math.max(0, ...trip.series.map((p) => p[2]));
  const verdict = alarms ? `The driver fell asleep ${alarms} time(s) during this trip. Driving should stop until they have rested.`
    : lvl >= 2 ? "High fatigue was detected. A rest break is strongly advised."
    : lvl === 1 ? "Signs of tiredness were detected. A short break is advised."
    : "No significant fatigue was detected during this trip.";
  doc.setFont("helvetica", "italic"); doc.setFontSize(10.5); doc.setTextColor(31, 41, 55);
  doc.text(doc.splitTextToSize(verdict, W - 2 * M), M, y); y += 10;

  // chart
  renderReportChart();
  const img = $("repChart").toDataURL("image/png");
  const ih = (W - 2 * M) * $("repChart").height / $("repChart").width;
  doc.addImage(img, "PNG", M, y, W - 2 * M, ih); y += ih + 8;

  // events table
  doc.setFont("helvetica", "bold"); doc.setFontSize(13); doc.text("Events", M, y); y += 6;
  doc.setFontSize(9.5);
  const evs = trip.events.length ? trip.events : [{ t: 0, tag: "-", text: "No events recorded." }];
  for (const e of evs) {
    if (y > 280) { doc.addPage(); y = 18; }
    doc.setFont("helvetica", "normal"); doc.setTextColor(107, 114, 128); doc.text(fmtTime(e.t), M, y);
    doc.setFont("helvetica", "bold"); doc.setTextColor(e.kind === "drowsy" ? 198 : 31, e.kind === "drowsy" ? 47 : 41, e.kind === "drowsy" ? 43 : 55);
    doc.text(e.tag, M + 18, y);
    doc.setFont("helvetica", "normal"); doc.setTextColor(31, 41, 55); doc.text(String(e.text).replace(/[–→]/g, "-"), M + 48, y);
    y += 5.6;
  }
  const pages = doc.getNumberOfPages();
  for (let p = 1; p <= pages; p++) {
    doc.setPage(p); doc.setFont("helvetica", "normal"); doc.setFontSize(8); doc.setTextColor(140, 140, 140);
    doc.text("Generated by the Blink to Safety browser demo - github.com/itzapraagavi-eng/blink-to-safety - not a certified safety device.", M, 290);
    doc.text(`${p} / ${pages}`, W - M, 290, { align: "right" });
  }
  const d = trip.startDate, pad = (n) => String(n).padStart(2, "0");
  const name = `blink-to-safety-trip-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}.pdf`;
  window.__bts.pdfName = name;
  doc.save(name);
}
function hexToRgb(h) { const m = /^#?([0-9a-f]{6})$/i.exec(h); if (!m) return null; const n = parseInt(m[1], 16); return [n >> 16, (n >> 8) & 255, n & 255]; }
function alertBox(msg) { $("repWhen").textContent = msg; }

// ------------------------------------------------------------ themes
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  document.querySelectorAll(".themes button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.theme === t)));
  store.set("bts-theme", t);
  if (lastState) render(lastState, performance.now() / 1000); else drawChart(performance.now() / 1000);
}
document.querySelectorAll(".themes button").forEach((b) => b.addEventListener("click", () => applyTheme(b.dataset.theme)));
applyTheme(document.documentElement.dataset.theme || "highway");

// ------------------------------------------------------------ controls
function segment(id, onPick) {
  document.querySelectorAll(`#${id} button`).forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(`#${id} button`).forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", String(x === b)); });
    onPick(b.dataset.v);
  }));
}
segment("langSeg", (v) => { lang = v; store.set("bts-lang", v); unlockAudio(); say("distracted", true); });
segment("sensSeg", (v) => { cfg.closedSeconds = parseFloat(v); store.set("bts-sens", v); });
const savedLang = store.get("bts-lang"), savedSens = store.get("bts-sens");
if (savedLang) { lang = savedLang; document.querySelectorAll("#langSeg button").forEach((x) => { x.classList.toggle("on", x.dataset.v === lang); x.setAttribute("aria-pressed", String(x.dataset.v === lang)); }); }
if (savedSens) { cfg.closedSeconds = parseFloat(savedSens); document.querySelectorAll("#sensSeg button").forEach((x) => { x.classList.toggle("on", x.dataset.v === savedSens); x.setAttribute("aria-pressed", String(x.dataset.v === savedSens)); }); }
$("sosNum").value = store.get("bts-sos") || "";
$("sosNum").addEventListener("change", (e) => store.set("bts-sos", e.target.value.trim()));

$("startBtn").addEventListener("click", start);
$("stopBtn").addEventListener("click", endTrip);
$("recalBtn").addEventListener("click", () => { if (monitor) { monitor.recalibrate(); history.length = 0; } });
$("driveBtn").addEventListener("click", () => setDriving(!$("stage").classList.contains("driving")));
$("hudExit").addEventListener("click", () => setDriving(false));
$("reportBtn").addEventListener("click", openReport);
$("pdfBtn").addEventListener("click", downloadPdf);
$("sosBtn").addEventListener("click", shareLocation);
$("sosHide").addEventListener("click", () => { $("sosCard").hidden = true; if (trip) trip.sosDismissedAt = performance.now() / 1000; });
$("setBtn").addEventListener("click", () => {
  const s = $("settings"); s.hidden = !s.hidden; $("setBtn").setAttribute("aria-expanded", String(!s.hidden));
});
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  chartMode = b.dataset.chart;
  document.querySelectorAll(".tabs button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-selected", String(x === b)); });
  drawChart(performance.now() / 1000);
}));
$("soundChk").addEventListener("change", (e) => {
  soundOn = e.target.checked;
  if (!soundOn) { alarm(false); synth.cancel(); if (clip) clip.pause(); }
  else if (lastState && lastState.status === "DROWSY") alarm(true);
});
window.addEventListener("resize", () => drawChart(performance.now() / 1000));
synth.getVoices();
if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
  showError(window.isSecureContext ? "This browser cannot use the camera. Try Chrome, Edge, Firefox or Safari." : "The camera only works on an https:// page.");
  $("startBtn").disabled = true;
}
