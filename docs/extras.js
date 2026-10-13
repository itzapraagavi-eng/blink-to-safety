// extras.js - user interface for the prevention features (see features.js):
// fit-to-drive check, camera heart rate, personal profile, early warning
// and the rest-stop finder.
import { PVT, pvtStats, estimateHeartRate, usualValues, compareWithUsual, forecast } from "./features.js";

const FOREHEAD = { top: 10, browR: 105, browL: 334 };
const median = (a) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);

export function initExtras(api) {
  const { $, store } = api;
  const testSec = Number(new URLSearchParams(location.search).get("pvtsec"));   // shorter test, for automated checks only
  if (testSec > 0) PVT.durationSec = testSec;

  // ============================================================ 1. fit-to-drive check
  let pvt = null;                 // running test state
  let lastPvt = null;
  try { lastPvt = JSON.parse(store.get("bts-pvt") || "null"); } catch { lastPvt = null; }
  const pvtToday = () => (lastPvt && Date.now() - lastPvt.when < 6 * 3600 * 1000 ? lastPvt : null);   // valid for 6 h
  const pvtRt = () => { const p = pvtToday(); return p && p.verdict !== "INCOMPLETE" && p.median ? p.median : null; };

  const show = (part) => ["pvtIntro", "pvtRun", "pvtResult"].forEach((id) => ($(id).hidden = id !== part));
  function openPvt() { $("pvt").hidden = false; show("pvtIntro"); $("pvtBegin").focus(); }
  function closePvt() { stopPvt(); $("pvt").hidden = true; }

  function beginPvt() {
    api.unlockAudio();
    show("pvtRun");
    pvt = { t0: performance.now(), rts: [], falseStarts: 0, stimOn: false, stimT0: 0, timer: null, raf: 0, done: false };
    $("pvtCounter").textContent = ""; $("pvtHint").textContent = "Wait for the counter…";
    $("pvtBox").focus();
    schedule();
    tickProgress();
  }
  function schedule() {
    if (!pvt) return;
    const gap = (PVT.minGapSec + Math.random() * (PVT.maxGapSec - PVT.minGapSec)) * 1000;
    if (performance.now() - pvt.t0 + gap > PVT.durationSec * 1000) { pvt.timer = setTimeout(finishPvt, Math.max(0, PVT.durationSec * 1000 - (performance.now() - pvt.t0))); return; }
    pvt.timer = setTimeout(stimulus, gap);
  }
  function stimulus() {
    if (!pvt) return;
    pvt.stimOn = true; pvt.stimT0 = performance.now();
    $("pvtHint").textContent = "TAP NOW";
    const run = () => {
      if (!pvt || !pvt.stimOn) return;
      const ms = performance.now() - pvt.stimT0;
      $("pvtCounter").textContent = Math.floor(ms);
      if (ms > 3000) { respond(performance.now(), true); return; }      // no reaction in 3 s = lapse
      pvt.raf = requestAnimationFrame(run);
    };
    run();
  }
  function respond(ts, timedOut = false) {
    if (!pvt || pvt.done) return;
    if (!pvt.stimOn) {                                   // pressed before the counter appeared
      pvt.falseStarts++;
      $("pvtBox").classList.add("early"); $("pvtHint").textContent = "Too early – wait for the counter";
      setTimeout(() => $("pvtBox").classList.remove("early"), 500);
      clearTimeout(pvt.timer); schedule();
      return;
    }
    const rt = ts - pvt.stimT0;
    pvt.stimOn = false; cancelAnimationFrame(pvt.raf);
    if (!timedOut && rt < PVT.falseStartMs) pvt.falseStarts++;
    else pvt.rts.push(Math.min(rt, 3000));
    $("pvtCounter").textContent = timedOut ? "MISSED" : Math.round(rt) + " ms";
    $("pvtHint").textContent = "Wait for the next one…";
    setTimeout(() => { if (pvt && !pvt.stimOn) $("pvtCounter").textContent = ""; }, 600);
    schedule();
  }
  function tickProgress() {
    if (!pvt) return;
    $("pvtFill").style.width = Math.min(100, (performance.now() - pvt.t0) / (PVT.durationSec * 10)) + "%";
    if (!pvt.done) requestAnimationFrame(tickProgress);
  }
  function stopPvt() { if (pvt) { clearTimeout(pvt.timer); cancelAnimationFrame(pvt.raf); pvt.done = true; } pvt = null; }
  function finishPvt() {
    if (!pvt) return;
    if (pvt.stimOn) { pvt.timer = setTimeout(finishPvt, 300); return; }   // let the last reaction finish
    const r = pvtStats(pvt.rts, pvt.falseStarts);
    stopPvt();
    lastPvt = { when: Date.now(), median: r.median, mean: r.mean, lapses: r.lapses, falseStarts: r.falseStarts, n: r.n, verdict: r.verdict };
    store.set("bts-pvt", JSON.stringify(lastPvt));
    if (r.median) saveProfileTest(r.median);
    show("pvtResult");
    const v = $("pvtVerdict"); v.dataset.v = r.verdict; v.textContent = r.verdict;
    $("pvtAdvice").textContent = r.advice;
    $("pvtStats").innerHTML = [["Median reaction", r.median ? Math.round(r.median) + " ms" : "–"], ["Responses", r.n],
      ["Lapses (≥ 0.5 s)", r.lapses], ["Too early", r.falseStarts]].map(([k, val]) => `<div><dt>${k}</dt><dd>${val}</dd></div>`).join("");
    $("pvtStart").textContent = r.verdict === "NOT FIT" ? "Start trip anyway" : "Start trip";
    api.chime(r.verdict === "FIT" ? [523, 659, 784] : [440, 349]);
    showReaction();
    window.__bts.pvt = lastPvt;
  }
  function showReaction() {
    const p = pvtToday();
    $("mRt").textContent = p && p.median ? Math.round(p.median) + " ms" : "–";
    $("mRtV").textContent = p ? p.verdict.toLowerCase() + " · today" : "fit-to-drive check";
  }

  $("pvtOpen").addEventListener("click", openPvt);
  $("pvtBegin").addEventListener("click", beginPvt);
  $("pvtCancel").addEventListener("click", closePvt);
  $("pvtClose").addEventListener("click", closePvt);
  $("pvtAgain").addEventListener("click", beginPvt);
  $("pvtStart").addEventListener("click", () => { closePvt(); api.start(); });
  $("pvtBox").addEventListener("pointerdown", (e) => { e.preventDefault(); respond(e.timeStamp || performance.now()); });
  document.addEventListener("keydown", (e) => {
    if ($("pvt").hidden || $("pvtRun").hidden || (e.code !== "Space" && e.key !== " ")) return;
    e.preventDefault(); if (!e.repeat) respond(e.timeStamp || performance.now());
  });
  showReaction();

  // ============================================================ 2. camera heart rate
  const probe = document.createElement("canvas"); probe.width = 8; probe.height = 4;
  const pctx = probe.getContext("2d", { willReadFrequently: true });
  let hr = null;
  function resetHr() { hr = { samples: [], est: [], good: [], base: null, shown: null, bonus: 0, lastEst: 0, warned: false, roi: null }; }
  resetHr();

  function sampleForehead(face, st, now) {
    const P = face.pts;
    const top = P[FOREHEAD.top], bR = P[FOREHEAD.browR], bL = P[FOREHEAD.browL];
    const browY = Math.min(bR[1], bL[1]), height = browY - top[1];
    let x1 = Math.min(bR[0], bL[0]), x2 = Math.max(bR[0], bL[0]);
    const shrink = (x2 - x1) * 0.1; x1 += shrink; x2 -= shrink;
    const y1 = top[1] + 0.15 * height, y2 = browY - 0.1 * height;
    hr.roi = null;
    if (x2 - x1 < 8 || y2 - y1 < 4) return;
    const yaw = st.head && st.head.yawDelta;
    if (yaw != null && Math.abs(yaw) > 20) return;          // turned head: skin patch not reliable
    hr.roi = [x1, y1, x2 - x1, y2 - y1];
    window.__bts.roi = hr.roi;
    pctx.drawImage(api.video, x1, y1, x2 - x1, y2 - y1, 0, 0, 8, 4);
    const d = pctx.getImageData(0, 0, 8, 4).data;
    let r = 0, g = 0, b = 0;
    for (let i = 0; i < d.length; i += 4) { r += d[i]; g += d[i + 1]; b += d[i + 2]; }
    const n = d.length / 4;
    hr.samples.push([now, r / n, g / n, b / n]);
    while (hr.samples.length && now - hr.samples[0][0] > 16) hr.samples.shift();
  }

  function updateHr(now, fps) {
    if (now - hr.lastEst < 1) return;
    hr.lastEst = now;
    const e = estimateHeartRate(hr.samples);
    const q = e ? e.quality : 0;
    if (e && q >= 0.4) {
      hr.good.push([now, e.bpm]);
      while (hr.good.length && now - hr.good[0][0] > 600) hr.good.shift();
      const recent = hr.good.filter((p) => now - p[0] <= 8).map((p) => p[1]);
      hr.shown = median(recent);
      // the driver's own start value: median of the first 60 good readings
      if (!hr.base) { hr.est.push(e.bpm); if (hr.est.length >= 60) hr.base = median(hr.est); }
    }
    const el = $("mHr"), sub = $("mHrQ");
    if (fps && fps < 9) { el.textContent = "–"; sub.textContent = "needs ≥ 10 frames/s"; }
    else if (hr.shown && q >= 0.3) { el.textContent = Math.round(hr.shown) + " bpm"; sub.textContent = q >= 0.4 ? (hr.base ? "start " + Math.round(hr.base) + " bpm" : "learning your normal") : "weak signal – keep still"; }
    else { el.textContent = "–"; sub.textContent = hr.samples.length < 60 ? "measuring… keep still" : "keep still, face the light"; }

    // a clear, steady drop below the start value adds to the fatigue score
    hr.bonus = 0;
    const last60 = hr.good.filter((p) => now - p[0] <= 60).map((p) => p[1]);
    if (hr.base && last60.length >= 20) {
      const drop = (hr.base - median(last60)) / hr.base;
      hr.bonus = drop >= 0.15 ? 10 : drop >= 0.08 ? 5 : 0;
      if (hr.bonus && !hr.warned) {
        hr.warned = true;
        api.addEvent(now, "info", "PULSE", `Heart rate ${Math.round(drop * 100)}% below your start value`);
      }
      if (!hr.bonus && drop < 0.04) hr.warned = false;
    }
  }

  // ============================================================ 3. personal profile
  const driverKey = () => "bts-profile:" + (($("driverName").value || "Driver").trim().toLowerCase() || "driver");
  function loadProfile() { try { return JSON.parse(store.get(driverKey()) || '{"trips":[],"tests":[]}'); } catch { return { trips: [], tests: [] }; } }
  function saveProfile(p) { store.set(driverKey(), JSON.stringify(p)); }
  function saveProfileTest(rt) { const p = loadProfile(); p.tests = (p.tests || []).concat([{ when: Date.now(), rt }]).slice(-20); saveProfile(p); }
  function profileNote() {
    const p = loadProfile();
    $("profileNote").textContent = p.trips.length ? `${p.trips.length} saved trip(s) – today is compared with them` : "No saved trips yet – your first trip becomes your normal";
  }
  $("driverName").value = store.get("bts-driver") || "";
  $("driverName").addEventListener("change", () => { store.set("bts-driver", $("driverName").value.trim()); profileNote(); });
  profileNote();

  const blinks = [];                      // [time, duration] of recent blinks
  let usual = null, lastCompare = 0, lastPersonalWarn = -1e9;
  function currentValues(st, now) {
    const recent = blinks.filter((b) => now - b[0] <= 120).map((b) => b[1]);
    return {
      perclos: st.perclos > 0 ? st.perclos : null,
      blinkRate: api.blinksPerMinute(now) || null,
      blinkDur: recent.length >= 3 ? mean(recent) : null,
      hr: hr.shown || null,
      rt: pvtRt(),
    };
  }
  function updatePersonal(st, now, trip) {
    if (now - lastCompare < 3) return;
    lastCompare = now;
    const recent = blinks.filter((b) => now - b[0] <= 120).map((b) => b[1]);
    $("mBlinkDur").textContent = recent.length >= 3 ? Math.round(mean(recent) * 1000) : "–";
    if (!usual || usual.trips < 1 || !trip.monitorStart || now - trip.monitorStart < 60) { $("usualCard").hidden = true; return; }
    const cmp = compareWithUsual(currentValues(st, now), usual);
    if (!cmp.rows.length) return;
    $("usualCard").hidden = false;
    $("usualNote").textContent = `from ${usual.trips} earlier trip(s)`;
    $("usualBody").innerHTML = cmp.rows.map((r) => `<tr><td>${r.label}</td><td>${r.now}${r.unit ? " " + r.unit : ""}</td><td>${r.usual}${r.unit ? " " + r.unit : ""}</td>` +
      `<td>${r.worse ? `<span class="flag">${r.change > 0 ? "+" : ""}${Math.round(r.change * 100)}%</span>` : '<span class="ok">normal</span>'}</td></tr>`).join("");
    trip.personalWorse = cmp.rows.filter((r) => r.worse).map((r) => r.label);
    if (cmp.worseCount >= 2 && now - lastPersonalWarn > 300) {
      lastPersonalWarn = now;
      api.addEvent(now, "info", "PERSONAL", "More tired than your usual: " + trip.personalWorse.join(", ").toLowerCase());
      api.chime([523, 659]); api.say("tired", false);
    }
  }
  function saveTrip(trip) {
    if (!trip.monitorStart || trip.last - trip.monitorStart < 60) return false;
    const per = mean(trip.perclos.filter((x) => x > 0));
    const entry = {
      when: Date.now(), minutes: (trip.last - trip.monitorStart) / 60,
      perclos: per, blinkRate: (trip.blinks || 0) / ((trip.last - trip.monitorStart) / 60),
      blinkDur: trip.blinkDurs.length ? mean(trip.blinkDurs) : null,
      hr: hr.good.length ? median(hr.good.map((x) => x[1])) : null,
      rt: pvtRt(), alarms: trip.alarms || 0,
    };
    const prof = loadProfile();
    prof.trips = prof.trips.concat([entry]).slice(-10);
    saveProfile(prof);
    profileNote();
    return true;
  }

  // ============================================================ 4. early warning
  let lastForecast = 0, lastForecastWarn = -1e9;
  function updateForecast(st, now, trip) {
    if (now - lastForecast < 5) return;
    lastForecast = now;
    const el = $("forecast");
    const fc = forecast(trip.series);
    trip.forecast = fc;
    if (!fc || st.level >= 2 || fc.perMin <= 0.3) { el.hidden = true; return; }
    if (fc.etaMin != null && fc.etaMin <= 20) {
      const m = Math.max(1, Math.round(fc.etaMin));
      el.hidden = false;
      el.textContent = `Fatigue rising ${fc.perMin.toFixed(1)}/min – "very tired" in about ${m} min. Plan a stop now.`;
      if (now - lastForecastWarn > 300) {
        lastForecastWarn = now;
        trip.forecastWarnings = (trip.forecastWarnings || 0) + 1;
        api.addEvent(now, "info", "FORECAST", `Very tired in about ${m} min at this rate`);
        api.chime([587, 698]);
        api.sayText(`Your tiredness is rising. Please plan a stop within ${m} minutes.`, "tired");
      }
    } else el.hidden = true;
  }

  // ============================================================ 6. rest-stop finder
  function findRestStop() {
    const q = encodeURIComponent("petrol pump OR dhaba OR rest area near me");
    window.open(`https://www.google.com/maps/search/?api=1&query=${q}`, "_blank", "noopener");
  }
  $("restBtn").addEventListener("click", findRestStop);
  $("sosRest").addEventListener("click", findRestStop);

  // ============================================================ hooks used by app.js
  return {
    hrBonus: () => hr.bonus,
    onTripStart(trip) {
      resetHr(); blinks.length = 0; lastCompare = 0; lastForecast = 0;
      trip.blinkDurs = []; trip.pvt = pvtToday();
      usual = usualValues(loadProfile().trips);
      $("usualCard").hidden = true; $("forecast").hidden = true; $("restBtn").hidden = true;
      trip.hrStart = null;
    },
    onFrame(face, st, now, trip, fps) {
      if (face) sampleForehead(face, st, now); else hr.roi = null;
      updateHr(now, fps);
      if (st.blinkDuration != null) { blinks.push([now, st.blinkDuration]); trip.blinkDurs.push(st.blinkDuration); while (blinks.length && now - blinks[0][0] > 120) blinks.shift(); }
      if (st.status === "CALIBRATING") return;
      updatePersonal(st, now, trip);
      updateForecast(st, now, trip);
      $("restBtn").hidden = !(st.level >= 1 || st.drowsyEvents > 0);
      trip.hrBase = hr.base; trip.hrNow = hr.shown;
      if (hr.good.length) { const v = hr.good.map((x) => x[1]); trip.hrMin = Math.min(...v); trip.hrMed = median(v); }
    },
    drawRoi(octx) {
      if (!hr.roi) return;
      octx.save(); octx.strokeStyle = "rgba(255,120,150,.8)"; octx.setLineDash([4, 3]); octx.lineWidth = 1.5;
      octx.strokeRect(...hr.roi); octx.restore();
    },
    onTripEnd(trip) { trip.savedToProfile = saveTrip(trip); },
    reportLines(trip) {
      const lines = [];
      const p = trip.pvt;
      lines.push(p ? `Fit-to-drive check: ${p.verdict} – median reaction ${Math.round(p.median || 0)} ms, ${p.lapses} lapse(s), ${p.falseStarts} too early.`
        : "Fit-to-drive check: not taken before this trip.");
      lines.push(trip.hrMed ? `Camera heart rate: start ${trip.hrBase ? Math.round(trip.hrBase) : "–"} bpm, typical ${Math.round(trip.hrMed)} bpm, lowest ${Math.round(trip.hrMin)} bpm.`
        : "Camera heart rate: not enough steady signal (keep the face still, in good light, at 10+ frames/s).");
      lines.push(usual && usual.trips ? (trip.personalWorse && trip.personalWorse.length ? `Compared with your usual (${usual.trips} trip(s)): worse ${trip.personalWorse.join(", ").toLowerCase()}.` : `Compared with your usual (${usual.trips} trip(s)): no clear difference.`)
        : "Personal profile: first trip for this driver" + (trip.savedToProfile ? " – saved as your normal." : "."));
      lines.push(`Early warnings: ${trip.forecastWarnings || 0}.`);
      return lines;
    },
  };
}
