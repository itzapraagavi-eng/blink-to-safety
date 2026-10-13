/* Blink to Safety - fleet monitor dashboard.
   Polls the fleet server every 2 s. No build step, no external libraries
   except Leaflet (bundled in leaflet/). */
"use strict";

const POLL_MS = 2000;
const DETAIL_MS = 4000;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let KEY = "";
try { KEY = localStorage.getItem("blinkFleetKey") || ""; } catch (e) { /* storage blocked */ }
let soundOn = true;
try { soundOn = localStorage.getItem("blinkFleetSound") !== "off"; } catch (e) { }

const S = {
  vehicles: [], events: [], lastEventId: 0, firstEvents: true,
  selected: null, detail: null, markers: {}, fitted: false, trail: null, trailMarks: [],
  newIds: new Set(),
};

// ------------------------------------------------------------------ helpers
const COLORS = {
  green: "#0e6b4a", amber: "#e8a317", amberInk: "#8a5c00", orange: "#d4651c",
  red: "#c62f2b", violet: "#7a4db3", grey: "#9aa49e", greyInk: "#5c6862",
};

function plateText(v) {
  const m = String(v || "").toUpperCase().match(/^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{1,4})$/);
  return m ? [m[1], m[2], m[3], m[4]].filter(Boolean).join(" ") : String(v || "");
}

function ago(sec) {
  if (sec < 60) return Math.round(sec) + " s ago";
  if (sec < 3600) return Math.round(sec / 60) + " min ago";
  return Math.round(sec / 3600) + " h ago";
}

function hm(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return h + "h " + String(m).padStart(2, "0") + "m";
}

function clock(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function mapsUrl(lat, lon) {
  return "https://maps.google.com/?q=" + lat.toFixed(6) + "," + lon.toFixed(6);
}

function stateOf(v) {
  if (!v.online) return { key: "offline", color: COLORS.grey, ink: COLORS.greyInk,
    label: "Offline, last seen " + ago(v.seen_ago) };
  switch (v.status) {
    case "DROWSY": return { key: "asleep", color: COLORS.red, ink: COLORS.red,
      label: "Falling asleep" + (v.reason ? " (" + v.reason.toLowerCase() + ")" : "") };
    case "DISTRACTED": return { key: "distracted", color: COLORS.violet, ink: COLORS.violet,
      label: "Eyes off the road" };
    case "NO FACE": return { key: "noface", color: COLORS.grey, ink: COLORS.greyInk, label: "Driver not visible to camera" };
    case "CALIBRATING": return { key: "starting", color: COLORS.green, ink: COLORS.green, label: "Starting up" };
  }
  if (v.level >= 2) return { key: "verytired", color: COLORS.orange, ink: COLORS.orange, label: "Very tired" };
  if (v.level === 1) return { key: "tired", color: COLORS.amber, ink: COLORS.amberInk, label: "Tired" };
  return { key: "alert", color: COLORS.green, ink: COLORS.green, label: "Alert" };
}

const EVENT_TEXT = {
  drowsy: ["Drowsiness alarm", COLORS.red],
  emergency: ["Emergency message sent to family", COLORS.red],
  alcohol: ["Alcohol detected", COLORS.red],
  distracted: ["Eyes off the road", COLORS.violet],
  very_tired: ["Very tired: told to stop and rest", COLORS.orange],
  tired: ["Tired: early warning given", COLORS.amberInk],
  long_drive: ["2 hours without a break: reminder given", COLORS.amberInk],
  night: ["Driving in night risk hours", COLORS.greyInk],
  break_taken: ["Took a break", COLORS.green],
  yawn: ["Yawned", COLORS.greyInk],
  nod: ["Head nod", COLORS.greyInk],
  trip_start: ["Started monitoring", COLORS.green],
  trip_end: ["Stopped monitoring", COLORS.greyInk],
};
const MINOR = new Set(["yawn", "nod", "night", "trip_start", "trip_end"]);
const LOUD = new Set(["drowsy", "emergency", "alcohol"]);

// ------------------------------------------------------------------ server
async function api(path) {
  const r = await fetch(path, { headers: { "X-Fleet-Key": KEY }, cache: "no-store" });
  if (r.status === 401) throw Object.assign(new Error("key"), { auth: true });
  if (!r.ok) throw new Error("http " + r.status);
  return r.json();
}

function setConn(ok) {
  const c = $("conn");
  c.textContent = ok ? "Live" : "Server not reachable, retrying";
  c.classList.toggle("bad", !ok);
}

// ------------------------------------------------------------------ sound
let audioCtx = null;
function beep() {
  if (!soundOn) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const t = audioCtx.currentTime;
    [0, 0.28, 0.56].forEach((d, i) => {
      const o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.type = "square"; o.frequency.value = i % 2 ? 1300 : 950;
      g.gain.setValueAtTime(0.0001, t + d);
      g.gain.exponentialRampToValueAtTime(0.18, t + d + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + d + 0.22);
      o.connect(g); g.connect(audioCtx.destination); o.start(t + d); o.stop(t + d + 0.24);
    });
  } catch (e) { /* audio not available */ }
}

// ------------------------------------------------------------------ map
let map = null, tileErrors = 0;
function initMap() {
  if (!window.L) { $("map").innerHTML = '<p class="empty" style="padding:16px">Map could not load.</p>'; return; }
  map = L.map("map", { zoomControl: true }).setView([11.6, 79.3], 7);
  const tiles = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  tiles.on("tileerror", () => { if (++tileErrors > 3) $("map-note").hidden = false; });
  tiles.on("tileload", () => { tileErrors = 0; $("map-note").hidden = true; });
  const far = () => $("map").classList.toggle("far", map.getZoom() < 9);
  map.on("zoomend", far); far();
}

function markerHtml(v, st) {
  return '<div class="vmark ' + st.key + (S.selected === v.vehicle ? " sel" : "") + '" style="--state:' + st.color + '">' +
    '<span class="dot"></span><span class="plate small">' + esc(plateText(v.vehicle)) + "</span></div>";
}

function updateMarkers() {
  if (!map) return;
  const seen = new Set(), pts = [];
  for (const v of S.vehicles) {
    if (v.lat == null || v.lon == null) continue;
    seen.add(v.vehicle);
    const st = stateOf(v);
    const icon = L.divIcon({ className: "", html: markerHtml(v, st), iconSize: [90, 44], iconAnchor: [45, 12] });
    let m = S.markers[v.vehicle];
    if (!m) {
      m = L.marker([v.lat, v.lon], { icon, keyboard: false, title: v.driver }).addTo(map);
      m.on("click", () => select(v.vehicle));
      S.markers[v.vehicle] = m;
    } else {
      m.setLatLng([v.lat, v.lon]);
      if (m._lastHtml !== icon.options.html) m.setIcon(icon);
    }
    m._lastHtml = icon.options.html;
    m.setZIndexOffset(st.key === "asleep" ? 1000 : st.key === "offline" ? -100 : 0);
    pts.push([v.lat, v.lon]);
  }
  for (const id of Object.keys(S.markers)) {
    if (!seen.has(id)) { map.removeLayer(S.markers[id]); delete S.markers[id]; }
  }
  if (!S.fitted && pts.length) {
    map.fitBounds(L.latLngBounds(pts).pad(0.35), { maxZoom: 10 });
    S.fitted = true;
  }
}

// ------------------------------------------------------------------ vehicles
function renderVehicles() {
  const list = $("veh-list");
  const online = S.vehicles.filter((v) => v.online).length;
  $("veh-count").textContent = online + " online of " + S.vehicles.length;
  $("veh-empty").hidden = S.vehicles.length > 0;
  list.innerHTML = S.vehicles.map((v) => {
    const st = stateOf(v);
    const fat = Math.round(v.fatigue || 0);
    const speed = v.speed_kmh != null && v.online ? Math.round(v.speed_kmh) + " km/h" : "";
    return '<li><button type="button" class="veh ' + (st.key === "asleep" ? "asleep " : "") +
      (S.selected === v.vehicle ? "sel" : "") + '" data-id="' + esc(v.vehicle) + '" style="--state:' +
      st.color + ";--state-ink:" + st.ink + '">' +
      '<span class="plate">' + esc(plateText(v.vehicle)) + "</span>" +
      '<span class="who"><span class="name">' + esc(v.driver) + (v.sim ? '<span class="sim">Simulated</span>' : "") +
      '</span><br><span class="state">' + esc(st.label) + "</span></span>" +
      '<span class="score"><b>' + fat + "</b><span>fatigue</span></span>" +
      '<span class="meter" aria-hidden="true"><i style="width:' + Math.min(100, fat) + '%"></i></span>' +
      '<span class="meta">' + (speed ? "<span>" + speed + "</span>" : "") +
      "<span>Driving " + hm(v.drive_time) + "</span>" +
      "<span>" + (v.today.drowsy || 0) + " alarm" + ((v.today.drowsy || 0) === 1 ? "" : "s") + " today</span></span>" +
      "</button></li>";
  }).join("");
}

function renderTotals() {
  const on = S.vehicles.filter((v) => v.online);
  const asleep = on.filter((v) => v.status === "DROWSY");
  const sum = (k) => S.vehicles.reduce((a, v) => a + (v.today[k] || 0), 0);
  $("t-online").textContent = on.length;
  $("t-asleep").textContent = asleep.length;
  $("t-asleep").parentElement.classList.toggle("on", asleep.length > 0);
  $("t-alarms").textContent = sum("drowsy");
  $("t-distract").textContent = sum("distracted");
  renderDanger(asleep);
}

let dangerTarget = null;
function renderDanger(asleep) {
  let text = "", target = null;
  if (asleep.length) {
    const v = asleep[0];
    text = v.driver + " (" + plateText(v.vehicle) + ") is falling asleep" +
      (v.speed_kmh != null ? " at " + Math.round(v.speed_kmh) + " km/h" : "") + ". Call the driver now." +
      (asleep.length > 1 ? " " + (asleep.length - 1) + " more vehicle" + (asleep.length > 2 ? "s" : "") + " also." : "");
    target = v;
  } else {
    const now = Date.now() / 1000;
    const em = S.events.find((e) => e.kind === "emergency" && now - e.ts < 180);
    if (em) {
      target = S.vehicles.find((v) => v.vehicle === em.vehicle) || { vehicle: em.vehicle, lat: em.lat, lon: em.lon };
      text = em.driver + " (" + plateText(em.vehicle) + ") had repeated drowsiness alarms. Emergency message sent.";
    }
  }
  dangerTarget = target;
  $("danger").hidden = !target;
  if (!target) return;
  $("danger-text").textContent = text;
  const maps = $("danger-maps");
  if (target.lat != null) { maps.hidden = false; maps.href = mapsUrl(target.lat, target.lon); }
  else maps.hidden = true;
}

// ------------------------------------------------------------------ alert feed
function eventItem(e, withVehicle) {
  const [label, color] = EVENT_TEXT[e.kind] || [e.kind, COLORS.greyInk];
  const detail = e.detail && e.kind !== "tired" && e.kind !== "very_tired" ? ": " + e.detail.toLowerCase() : "";
  const loc = e.lat != null ? '<a href="' + mapsUrl(e.lat, e.lon) + '" target="_blank" rel="noopener">Location</a>' : "";
  return '<li class="ev' + (S.newIds.has(e.id) ? " new" : "") + '" style="--kind:' + color + '">' +
    '<time datetime="' + new Date(e.ts * 1000).toISOString() + '">' + clock(e.ts) + "</time>" +
    '<span class="what">' + esc(label + detail) + "</span>" +
    '<span class="where">' + (withVehicle ? '<span class="plate small">' + esc(plateText(e.vehicle)) + "</span>" +
      "<span>" + esc(e.driver) + (e.sim ? " (simulated)" : "") + "</span>" : "") +
    (e.fatigue != null ? "<span>fatigue " + Math.round(e.fatigue) + "</span>" : "") + loc + "</span></li>";
}

function renderFeed() {
  const all = $("show-all").checked;
  const items = S.events.filter((e) => all || !MINOR.has(e.kind)).slice(0, 80);
  $("feed").innerHTML = items.map((e) => eventItem(e, true)).join("");
  $("feed-empty").hidden = items.length > 0;
}

// ------------------------------------------------------------------ detail
function select(id) {
  S.selected = id;
  S.detail = null;
  $("detail").hidden = false;
  renderVehicles();
  loadDetail();
  const v = S.vehicles.find((x) => x.vehicle === id);
  if (map && v && v.lat != null) map.setView([v.lat, v.lon], Math.max(map.getZoom(), 10));
}

function closeDetail() {
  S.selected = null; S.detail = null;
  $("detail").hidden = true;
  if (S.trail) { map.removeLayer(S.trail); S.trail = null; }
  S.trailMarks.forEach((m) => map.removeLayer(m)); S.trailMarks = [];
  renderVehicles();
}

async function loadDetail() {
  if (!S.selected) return;
  try {
    S.detail = await api("/api/vehicle?id=" + encodeURIComponent(S.selected));
    renderDetail();
  } catch (e) { /* next poll will retry */ }
}

function renderDetail() {
  const d = S.detail, v = S.vehicles.find((x) => x.vehicle === S.selected) || (d && d.state);
  if (!d || !v) return;
  const st = stateOf(v.online === undefined ? Object.assign({ online: false, seen_ago: 0 }, v) : v);
  $("det-plate").textContent = plateText(v.vehicle);
  $("det-name").textContent = v.driver + (v.sim ? " (simulated)" : "");
  const ds = $("det-status");
  ds.textContent = st.label; ds.style.setProperty("--state", st.color); ds.style.setProperty("--state-ink", st.ink);
  const t = v.today || {};
  const stats = [
    ["Fatigue now", Math.round(v.fatigue || 0)],
    ["Speed", v.speed_kmh != null ? Math.round(v.speed_kmh) + " km/h" : "-"],
    ["Driving for", hm(v.drive_time)],
    ["Alarms today", t.drowsy || 0],
    ["Eyes off road today", t.distracted || 0],
    ["Yawns / nods today", (t.yawn || 0) + " / " + (t.nod || 0)],
  ];
  $("det-stats").innerHTML = stats.map(([k, val]) => "<div><dt>" + esc(k) + "</dt><dd>" + esc(val) + "</dd></div>").join("");
  const evs = d.events.filter((e) => !MINOR.has(e.kind)).slice(0, 25);
  $("det-events").innerHTML = evs.length ? evs.map((e) => eventItem(e, false)).join("")
    : '<li class="empty" style="padding:0">No alerts for this vehicle yet.</li>';
  $("det-trips").innerHTML = d.trips.length ? d.trips.map((tr) => {
    const s = tr.summary || {};
    const when = new Date((tr.end_ts || tr.start_ts) * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    return "<li><span>" + esc(when) + ", " + hm(s.duration) + ", " + (s.alarms || 0) + " alarms" +
      (s.distance_km != null ? ", " + s.distance_km.toFixed(1) + " km" : "") + "</span>" +
      (tr.has_png ? '<a href="/api/trip_png?id=' + tr.id + "&key=" + encodeURIComponent(KEY) + '" target="_blank" rel="noopener">Open report</a>' : "") + "</li>";
  }).join("") : '<li class="empty" style="padding:0">A report appears here when the driver ends a trip.</li>';
  drawChart(d.trail, d.events);
  drawTrail(d.trail, d.events);
}

function drawTrail(trail, events) {
  if (!map) return;
  if (S.trail) map.removeLayer(S.trail);
  S.trailMarks.forEach((m) => map.removeLayer(m)); S.trailMarks = [];
  const pts = trail.filter((p) => p[1] != null).map((p) => [p[1], p[2]]);
  if (pts.length > 1) S.trail = L.polyline(pts, { color: COLORS.green, weight: 4, opacity: 0.75 }).addTo(map);
  for (const e of events) {
    if (e.lat == null || !["drowsy", "distracted", "emergency"].includes(e.kind)) continue;
    const c = EVENT_TEXT[e.kind][1];
    const m = L.circleMarker([e.lat, e.lon], { radius: 6, color: "#fff", weight: 2, fillColor: c, fillOpacity: 1 })
      .bindTooltip(clock(e.ts) + " " + EVENT_TEXT[e.kind][0]).addTo(map);
    S.trailMarks.push(m);
  }
}

function drawChart(trail, events) {
  const box = $("chart");
  const W = Math.max(280, box.clientWidth), H = 170, L0 = 34, R = 10, T = 8, B = 22;
  const now = Date.now() / 1000;
  const data = trail.filter((p) => p[4] != null);
  const spanMin = data.length ? Math.min(60, Math.max(10, Math.ceil((now - data[0][0]) / 300) * 5)) : 10;
  box.previousElementSibling.textContent = "Fatigue score, last " + spanMin + " minutes";
  const t0 = now - spanMin * 60;
  const x = (t) => L0 + (t - t0) / (now - t0) * (W - L0 - R);
  const y = (f) => T + (1 - f / 100) * (H - T - B);
  let svg = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Fatigue score over time">';
  svg += '<rect x="' + L0 + '" y="' + y(65) + '" width="' + (W - L0 - R) + '" height="' + (y(35) - y(65)) + '" fill="#e8a317" opacity="0.12"/>';
  svg += '<rect x="' + L0 + '" y="' + y(100) + '" width="' + (W - L0 - R) + '" height="' + (y(65) - y(100)) + '" fill="#c62f2b" opacity="0.08"/>';
  for (const g of [0, 35, 65, 100]) {
    svg += '<line x1="' + L0 + '" x2="' + (W - R) + '" y1="' + y(g) + '" y2="' + y(g) + '" stroke="#cdd3ce" stroke-width="1"/>';
    svg += '<text x="' + (L0 - 6) + '" y="' + (y(g) + 4) + '" text-anchor="end" font-size="11" fill="#6b7a71">' + g + "</text>";
  }
  for (let k = 0; k <= 4; k++) {
    const tt = t0 + k * (now - t0) / 4;
    svg += '<text x="' + x(tt) + '" y="' + (H - 5) + '" text-anchor="middle" font-size="11" fill="#6b7a71">' + clock(tt) + "</text>";
  }
  for (const e of events) {
    if (e.kind !== "drowsy" || e.ts < t0) continue;
    svg += '<line x1="' + x(e.ts) + '" x2="' + x(e.ts) + '" y1="' + T + '" y2="' + (H - B) + '" stroke="#c62f2b" stroke-width="2" opacity="0.55"/>';
  }
  const pts = data.filter((p) => p[0] >= t0);
  if (pts.length > 1) {
    svg += '<polyline fill="none" stroke="#0e6b4a" stroke-width="2.5" stroke-linejoin="round" points="' +
      pts.map((p) => x(p[0]).toFixed(1) + "," + y(p[4]).toFixed(1)).join(" ") + '"/>';
  }
  svg += '<line id="cx" stroke="#1f2a24" stroke-width="1" y1="' + T + '" y2="' + (H - B) + '" visibility="hidden"/>';
  svg += '<rect id="chit" x="' + L0 + '" y="0" width="' + (W - L0 - R) + '" height="' + H + '" fill="transparent"/></svg>';
  box.innerHTML = svg + '<div class="tip" hidden></div>';
  const hit = box.querySelector("#chit"), cx = box.querySelector("#cx"), tip = box.querySelector(".tip");
  hit.addEventListener("mousemove", (ev) => {
    if (!pts.length) return;
    const r = box.getBoundingClientRect(), mx = (ev.clientX - r.left) * W / r.width;
    const tt = t0 + (mx - L0) / (W - L0 - R) * (now - t0);
    let best = pts[0];
    for (const p of pts) if (Math.abs(p[0] - tt) < Math.abs(best[0] - tt)) best = p;
    cx.setAttribute("x1", x(best[0])); cx.setAttribute("x2", x(best[0])); cx.setAttribute("visibility", "visible");
    tip.hidden = false; tip.style.left = (x(best[0]) * r.width / W) + "px"; tip.style.top = (y(best[4]) * r.height / H) + "px";
    tip.textContent = clock(best[0]) + "  fatigue " + Math.round(best[4]);
  });
  hit.addEventListener("mouseleave", () => { tip.hidden = true; cx.setAttribute("visibility", "hidden"); });
}

// ------------------------------------------------------------------ polling
async function poll() {
  try {
    const f = await api("/api/fleet");
    S.vehicles = f.vehicles;
    const evs = await api("/api/events?since=" + S.lastEventId + "&limit=" + (S.firstEvents ? 120 : 100));
    if (evs.length) {
      S.lastEventId = Math.max(S.lastEventId, ...evs.map((e) => e.id));
      if (!S.firstEvents) {
        evs.forEach((e) => S.newIds.add(e.id));
        if (evs.some((e) => LOUD.has(e.kind))) beep();
      }
      S.events = evs.concat(S.events).slice(0, 300);
    }
    S.firstEvents = false;
    setConn(true);
    renderTotals(); renderVehicles(); renderFeed(); updateMarkers();
    if (S.detail) renderDetail();
    S.newIds.clear();
  } catch (e) {
    if (e.auth) { showGate("That key was not accepted. Check the key printed by fleet_server.py."); return; }
    setConn(false);
  }
  setTimeout(poll, POLL_MS);
}

function detailLoop() {
  loadDetail();
  setTimeout(detailLoop, DETAIL_MS);
}

// ------------------------------------------------------------------ key gate + wiring
let started = false;
function showGate(msg) {
  $("gate").hidden = false;
  $("gate-error").textContent = msg || "";
  $("key-input").focus();
}

$("gate-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  KEY = $("key-input").value.trim();
  try { localStorage.setItem("blinkFleetKey", KEY); } catch (e) { }
  $("gate").hidden = true;
  beepUnlock();
  start();
});

function beepUnlock() {        // browsers only allow sound after a click
  try { audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)(); audioCtx.resume(); } catch (e) { }
}

function start() {
  if (!started) { started = true; initMap(); detailLoop(); poll(); }
  else poll();
}

$("veh-list").addEventListener("click", (ev) => {
  const b = ev.target.closest(".veh");
  if (b) select(b.dataset.id);
});
$("det-close").addEventListener("click", closeDetail);
$("show-all").addEventListener("change", renderFeed);
$("danger-show").addEventListener("click", () => { if (dangerTarget) select(dangerTarget.vehicle); });
$("logout-btn").addEventListener("click", () => {
  try { localStorage.removeItem("blinkFleetKey"); } catch (e) { }
  KEY = ""; showGate("");
});
const sb = $("sound-btn");
function paintSound() { sb.textContent = soundOn ? "Sound on" : "Sound off"; sb.setAttribute("aria-pressed", soundOn); }
sb.addEventListener("click", () => {
  soundOn = !soundOn; beepUnlock(); paintSound();
  try { localStorage.setItem("blinkFleetSound", soundOn ? "on" : "off"); } catch (e) { }
});
paintSound();
document.querySelectorAll(".srv").forEach((n) => { n.textContent = location.origin; });
document.addEventListener("click", beepUnlock, { once: true });

if (KEY) start(); else showGate("");
