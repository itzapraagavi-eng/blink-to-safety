// features.js - the extra "prevention" features of Blink to Safety.
// Pure functions only (no browser APIs) so they can be tested in Node.
//
//   1. Fit-to-drive check   : a short reaction-time test based on the
//                             Psychomotor Vigilance Task (PVT) used in sleep research
//   2. Camera heart rate    : remote photoplethysmography (rPPG) with the POS
//                             method (Wang et al., 2017) on the forehead skin colour
//   3. Personal profile     : this driver's normal values from earlier trips
//   4. Early warning        : how fast the fatigue score is rising, and when it
//                             will reach "very tired" at this rate

// ------------------------------------------------------------ 1. fit-to-drive check
export const PVT = {
  durationSec: 60,          // quick version (the clinical PVT-B lasts 3 minutes)
  minGapSec: 2, maxGapSec: 6,
  lapseMs: 500,             // a reaction slower than 0.5 s counts as a lapse
  falseStartMs: 100,        // faster than 0.1 s = pressed before really seeing it
};

export function pvtStats(rts, falseStarts) {
  const s = [...rts].sort((a, b) => a - b);
  const n = s.length;
  const median = n ? (n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2) : null;
  const mean = n ? s.reduce((a, b) => a + b, 0) / n : null;
  const lapses = s.filter((r) => r >= PVT.lapseMs).length;
  let verdict, advice;
  if (n < 5) { verdict = "INCOMPLETE"; advice = "Too few responses. Please take the test again."; }
  else if (median >= 500 || lapses >= 3 || falseStarts >= 4) { verdict = "NOT FIT"; advice = "Your reactions are slow. Rest or sleep before you drive."; }
  else if (median >= 400 || lapses >= 2 || falseStarts >= 3) { verdict = "BORDERLINE"; advice = "Your reactions are a little slow. Drive only if you must, and take breaks."; }
  else { verdict = "FIT"; advice = "Your reactions are normal. Drive safely."; }
  return { n, median, mean, lapses, falseStarts, verdict, advice };
}

// ------------------------------------------------------------ 2. camera heart rate
// POS: project the normalised RGB colour onto the plane orthogonal to the
// skin tone, which cancels most brightness changes and keeps the pulse.
export function posSignal(rgb, fs) {
  const N = rgb.length, l = Math.max(2, Math.round(1.6 * fs));
  const H = new Float64Array(N);
  for (let m = 0; m + l <= N; m++) {
    let mr = 0, mg = 0, mb = 0;
    for (let i = m; i < m + l; i++) { mr += rgb[i][0]; mg += rgb[i][1]; mb += rgb[i][2]; }
    mr /= l; mg /= l; mb /= l;
    if (!mr || !mg || !mb) continue;
    const s1 = new Float64Array(l), s2 = new Float64Array(l);
    for (let k = 0; k < l; k++) {
      const r = rgb[m + k][0] / mr, g = rgb[m + k][1] / mg, b = rgb[m + k][2] / mb;
      s1[k] = g - b;
      s2[k] = g + b - 2 * r;
    }
    const a = std(s1) / (std(s2) || 1e-9);
    let mh = 0;
    const h = new Float64Array(l);
    for (let k = 0; k < l; k++) { h[k] = s1[k] + a * s2[k]; mh += h[k]; }
    mh /= l;
    for (let k = 0; k < l; k++) H[m + k] += h[k] - mh;
  }
  return H;
}
function std(x) { let m = 0; for (const v of x) m += v; m /= x.length; let s = 0; for (const v of x) s += (v - m) ** 2; return Math.sqrt(s / x.length); }

// samples: [[t_seconds, r, g, b], ...] from the forehead; returns
// { bpm, quality } or null when there is not enough steady signal.
export function estimateHeartRate(samples, { windowSec = 12, fs = 15, minFps = 8 } = {}) {
  if (samples.length < 10) return null;
  const tEnd = samples[samples.length - 1][0], tStart = tEnd - windowSec;
  const win = samples.filter((s) => s[0] >= tStart);
  const span = win.length ? win[win.length - 1][0] - win[0][0] : 0;
  if (span < windowSec * 0.75 || win.length / span < minFps) return null;
  // resample to an even rate (camera frames do not arrive evenly)
  const n = Math.floor(span * fs), rgb = [];
  let j = 0;
  for (let i = 0; i < n; i++) {
    const t = win[0][0] + i / fs;
    while (j < win.length - 2 && win[j + 1][0] < t) j++;
    const a = win[j], b = win[j + 1], f = b[0] > a[0] ? Math.min(1, Math.max(0, (t - a[0]) / (b[0] - a[0]))) : 0;
    rgb.push([a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f]);
  }
  const h = posSignal(rgb, fs);
  // power spectrum between 42 and 180 beats per minute (Hann window)
  let best = 0, bestBpm = 0, total = 0, count = 0;
  const powers = [];
  for (let bpm = 42; bpm <= 180; bpm += 0.5) {
    const w = 2 * Math.PI * (bpm / 60) / fs;
    let re = 0, im = 0;
    for (let k = 0; k < n; k++) {
      const hw = h[k] * (0.5 - 0.5 * Math.cos(2 * Math.PI * k / (n - 1)));
      re += hw * Math.cos(w * k); im -= hw * Math.sin(w * k);
    }
    const p = re * re + im * im;
    powers.push([bpm, p]);
    total += p; count++;
    if (p > best) { best = p; bestBpm = bpm; }
  }
  // quality: share of the power within +-6 bpm of the peak (pulse is a narrow peak)
  let near = 0;
  for (const [bpm, p] of powers) if (Math.abs(bpm - bestBpm) <= 6) near += p;
  const quality = total ? near / total : 0;
  return { bpm: bestBpm, quality };
}

// ------------------------------------------------------------ 3. personal profile
// A trip summary: { date, perclos, blinkRate, blinkDur, hr, rt, alarms, minutes }
export function usualValues(trips) {
  const keys = ["perclos", "blinkRate", "blinkDur", "hr", "rt"];
  const out = { trips: trips.length };
  for (const k of keys) {
    const v = trips.map((t) => t[k]).filter((x) => typeof x === "number" && isFinite(x) && x > 0);
    out[k] = v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  }
  return out;
}

// Compare today with the usual values. "worse" = in the tired direction by
// more than 30 % (for heart rate: more than 8 % lower).
export function compareWithUsual(now, usual) {
  const rows = [];
  const add = (key, label, unit, higherIsWorse, limit, fmt) => {
    const a = now[key], b = usual[key];
    if (a == null || b == null || !isFinite(a) || !isFinite(b) || b === 0) return;
    const change = (a - b) / b;
    const worse = higherIsWorse ? change > limit : change < -limit;
    rows.push({ key, label, now: fmt(a), usual: fmt(b), unit, change, worse });
  };
  add("perclos", "Eyes closed (PERCLOS)", "%", true, 0.3, (v) => (v * 100).toFixed(1));
  add("blinkDur", "Blink length", "ms", true, 0.3, (v) => Math.round(v * 1000));
  add("blinkRate", "Blinks per minute", "", true, 0.3, (v) => v.toFixed(0));
  add("hr", "Heart rate", "bpm", false, 0.08, (v) => v.toFixed(0));
  add("rt", "Reaction time", "ms", true, 0.15, (v) => Math.round(v));
  return { rows, worseCount: rows.filter((r) => r.worse).length };
}

// ------------------------------------------------------------ 4. early warning
// series: [[t_seconds, fatigue], ...]. Fits a straight line to the last few
// minutes; returns the rise per minute and the minutes left until `target`.
export function forecast(series, target = 65, windowSec = 180, minSec = 60) {
  if (series.length < 5) return null;
  const tEnd = series[series.length - 1][0];
  const pts = series.filter((p) => p[0] >= tEnd - windowSec);
  if (pts.length < 5 || pts[pts.length - 1][0] - pts[0][0] < minSec) return null;
  const n = pts.length;
  let sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (const [t, f] of pts) { sx += t; sy += f; sxx += t * t; sxy += t * f; }
  const slopeSec = (n * sxy - sx * sy) / (n * sxx - sx * sx || 1e-9);
  const perMin = slopeSec * 60;
  const current = pts[n - 1][1];
  const eta = perMin > 0.3 && current < target ? (target - current) / perMin : null;
  return { perMin, current, etaMin: eta };
}
