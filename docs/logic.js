// logic.js - Blink to Safety detection rules (browser version).
// A direct port of detector.py and monitor.py from the Python app, so the
// demo behaves the same way: same landmarks, thresholds and timings.
// Pure functions and classes only (no browser APIs) so it can be tested in Node.

export const RIGHT_EYE = [33, 160, 158, 133, 153, 144];   // p1..p6
export const LEFT_EYE = [362, 385, 387, 263, 373, 380];
export const MOUTH_CORNERS = [78, 308];
export const MOUTH_PAIRS = [[81, 178], [13, 14], [311, 402]];
export const MOUTH_OUTLINE = [78, 81, 13, 311, 308, 402, 14, 178];

export const CFG = {
  closedSeconds: 1.5,      // eyes closed this long = drowsy
  calibSeconds: 3.0,       // learn the driver's normal face
  factor: 0.65,            // eye limit = 65% of normal open-eye EAR
  thrMin: 0.13, thrMax: 0.28,
  slowBlink: 0.5,          // closures longer than this are slow blinks
  adaptWindow: 30, adaptPct: 70,
  marThr: 0.5, yawnMin: 1.0, yawnGrace: 2.0,
  downDeg: 20, dropSec: 2.0, minNod: 0.3,
  awayDeg: 30, distractSec: 2.0, faceLostSec: 3.0, earUnreliableYaw: 45,
  tired: 35, veryTired: 65, window: 60,
  riskHours: [[0, 6]], riskClosedFactor: 0.8, riskBonus: 10,
};

export const LEVEL_NAMES = ["ALERT", "TIRED", "VERY TIRED", "DROWSY"];

// ------------------------------------------------------------ measurements
const d2 = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

export function eyeAspectRatio(p) {           // p: six [x, y] points p1..p6
  const h = d2(p[0], p[3]);
  return h === 0 ? 0 : (d2(p[1], p[5]) + d2(p[2], p[4])) / (2 * h);
}

export function mouthAspectRatio(P) {
  const w = d2(P[MOUTH_CORNERS[0]], P[MOUTH_CORNERS[1]]);
  if (w === 0) return 0;
  let v = 0;
  for (const [a, b] of MOUTH_PAIRS) v += d2(P[a], P[b]);
  return v / MOUTH_PAIRS.length / w;
}

// Head pitch / yaw from the 3-D face mesh. MediaPipe gives x right, y down and
// z away from the camera (smaller = closer). The face normal is the cross
// product of the eye line and the chin-to-forehead line; it points at the
// camera for a frontal face. Pitch > 0 when the head bends DOWN.
export function headPose(P3) {
  const a = sub(P3[263], P3[33]);              // right eye corner -> left eye corner
  const b = sub(P3[10], P3[152]);              // chin -> forehead
  const n = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const deg = 180 / Math.PI;
  return {
    pitch: Math.atan2(n[1], -n[2]) * deg,
    yaw: Math.atan2(n[0], -n[2]) * deg,
  };
}
const sub = (p, q) => [p[0] - q[0], p[1] - q[1], p[2] - q[2]];

// landmarks: MediaPipe normalised {x, y, z}; w, h: video size in pixels
export function measureFace(landmarks, w, h) {
  const P = landmarks.map((l) => [l.x * w, l.y * h]);
  const P3 = landmarks.map((l) => [l.x * w, l.y * h, l.z * w]);
  const right = RIGHT_EYE.map((i) => P[i]), left = LEFT_EYE.map((i) => P[i]);
  return {
    pts: P,
    eyes: [right, left],
    ear: (eyeAspectRatio(right) + eyeAspectRatio(left)) / 2,
    mar: mouthAspectRatio(P),
    pose: headPose(P3),
  };
}

export function percentile(values, pct) {     // same as numpy's default (linear)
  const s = [...values].sort((x, y) => x - y);
  if (!s.length) return NaN;
  const k = (s.length - 1) * pct / 100, f = Math.floor(k), c = Math.ceil(k);
  return f === c ? s[f] : s[f] + (s[c] - s[f]) * (k - f);
}
const median = (v) => percentile(v, 50);
const clip = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

// ------------------------------------------------------------ eye state
export class EyeTracker {
  constructor(cfg = CFG) {
    this.cfg = cfg;
    this.closedSeconds = cfg.closedSeconds;
    this.threshold = 0.21;
    this.calibratedThreshold = this.threshold;
    this.baselineEar = null;
    this.recent = [];
    this.lastAdapt = -1e9;
    this.startCalibration();
    this.reset();
  }
  reset() { this.closedSince = null; this.drowsy = false; this.blinks = 0; this.monitorStart = null; }
  startCalibration() { this.calibrating = true; this.samples = []; this.calibStart = null; }

  update(ear, now, thrScale = 1) {
    if (ear == null) {
      this.closedSince = null; this.drowsy = false;
      return this.state("NO FACE", ear, 0);
    }
    if (this.calibrating) {
      if (this.calibStart == null) this.calibStart = now;
      this.samples.push(ear);
      const el = now - this.calibStart;
      if (el >= this.cfg.calibSeconds && this.samples.length >= 10) {
        this.baselineEar = median(this.samples);
        this.threshold = clip(this.baselineEar * this.cfg.factor, this.cfg.thrMin, this.cfg.thrMax);
        this.calibratedThreshold = this.threshold;
        this.recent = [];
        this.calibrating = false;
        this.reset();
      }
      const st = this.state("CALIBRATING", ear, 0);
      st.progress = Math.min(1, el / this.cfg.calibSeconds);
      return st;
    }
    if (this.monitorStart == null) this.monitorStart = now;
    this.adapt(ear, now);

    const closed = ear < this.threshold * thrScale;
    if (closed) {
      if (this.closedSince == null) this.closedSince = now;
      const closedFor = now - this.closedSince;
      let started = false;
      if (closedFor >= this.closedSeconds && !this.drowsy) this.drowsy = started = true;
      const st = this.state(this.drowsy ? "DROWSY" : "EYES CLOSED", ear, closedFor);
      st.drowsyStarted = started;
      return st;
    }
    let blinkDur = null;
    if (this.closedSince != null && !this.drowsy) { this.blinks++; blinkDur = now - this.closedSince; }
    this.closedSince = null; this.drowsy = false;
    const st = this.state("AWAKE", ear, 0);
    st.blinkDuration = blinkDur;
    return st;
  }

  // keep re-learning the normal open eye (70th percentile of the last 30 s);
  // the limit may only go DOWN from the calibrated value
  adapt(ear, now) {
    this.recent.push([now, ear]);
    while (this.recent.length && now - this.recent[0][0] > this.cfg.adaptWindow) this.recent.shift();
    if (now - this.lastAdapt < 1 || this.recent.length < 50) return;
    this.lastAdapt = now;
    const open = percentile(this.recent.map((r) => r[1]), this.cfg.adaptPct);
    this.threshold = clip(Math.min(this.calibratedThreshold, open * this.cfg.factor), this.cfg.thrMin, this.cfg.thrMax);
  }

  blinksPerMinute(now) {
    if (this.monitorStart == null) return 0;
    const min = (now - this.monitorStart) / 60;
    return min > 0.25 ? this.blinks / min : 0;
  }

  state(status, ear, closedFor) {
    return {
      status, ear, threshold: this.threshold, closedFor,
      eyesClosed: status === "EYES CLOSED" || status === "DROWSY",
      drowsy: status === "DROWSY", drowsyStarted: false, blinkDuration: null, blinks: this.blinks,
    };
  }
}

// ------------------------------------------------------------ yawns
export class YawnTracker {
  constructor(cfg = CFG) { this.thr = cfg.marThr; this.min = cfg.yawnMin; this.openSince = null; this.counted = false; this.count = 0; }
  update(mar, now) {                       // -> [yawningNow, newYawn]
    if (mar == null) { this.openSince = null; this.counted = false; return [false, false]; }
    if (mar >= this.thr) {
      if (this.openSince == null) { this.openSince = now; this.counted = false; }
      if (!this.counted && now - this.openSince >= this.min) { this.counted = true; this.count++; return [true, true]; }
      return [this.counted, false];
    }
    if (mar < this.thr * 0.8) { this.openSince = null; this.counted = false; }
    return [this.counted, false];
  }
}

// ------------------------------------------------------------ head
export class HeadTracker {
  constructor(cfg = CFG) { this.cfg = cfg; this.nods = 0; this.startCalibration(); }
  startCalibration() {
    this.basePitch = null; this.baseYaw = null; this.samples = []; this.calibStart = null;
    this.downSince = null; this.dropped = false; this.awaySince = null; this.distracted = false;
  }
  update(pose, now) {
    const c = this.cfg;
    const out = { pitchDelta: null, yawDelta: null, headDown: false, headDrop: false, dropStarted: false,
      nod: false, lookingAway: false, distracted: false, distractStarted: false };
    if (!pose) {
      this.downSince = null; this.dropped = false; this.awaySince = null; this.distracted = false;
      return out;
    }
    if (this.basePitch == null) {
      if (this.calibStart == null) this.calibStart = now;
      this.samples.push([pose.pitch, pose.yaw]);
      if (now - this.calibStart >= c.calibSeconds && this.samples.length >= 10) {
        this.basePitch = median(this.samples.map((s) => s[0]));
        this.baseYaw = median(this.samples.map((s) => s[1]));
      }
      return out;
    }
    // turning sideways
    const yd = pose.yaw - this.baseYaw;
    out.yawDelta = yd;
    if (Math.abs(yd) > c.awayDeg) {
      if (this.awaySince == null) this.awaySince = now;
      out.lookingAway = true;
      if (now - this.awaySince >= c.distractSec) { out.distractStarted = !this.distracted; this.distracted = true; }
    } else if (Math.abs(yd) < c.awayDeg * 0.7) {
      this.awaySince = null; this.distracted = false;
    } else {
      out.lookingAway = this.awaySince != null;
    }
    out.distracted = this.distracted;

    // bending down: nods and head drop
    const pd = pose.pitch - this.basePitch;
    out.pitchDelta = pd;
    if (pd > c.downDeg) {
      if (this.downSince == null) this.downSince = now;
      out.headDown = true;
      if (now - this.downSince >= c.dropSec) { out.dropStarted = !this.dropped; this.dropped = true; }
      out.headDrop = this.dropped;
    } else if (pd < c.downDeg * 0.6) {
      if (this.downSince != null && !this.dropped && now - this.downSince >= c.minNod) { this.nods++; out.nod = true; }
      this.downSince = null; this.dropped = false;
    } else {
      out.headDown = this.downSince != null;
      out.headDrop = this.dropped;
    }
    return out;
  }
}

// ------------------------------------------------------------ fatigue score
export class FatigueScorer {
  constructor(cfg = CFG) {
    this.window = cfg.window;
    this.hist = [];
    this.events = { yawn: [], nod: [], slow_blink: [], drowsy: [] };
    this.smooth = 0;
  }
  add(kind, now) { this.events[kind].push(now); }
  recent(kind, now, sec) {
    const q = this.events[kind];
    while (q.length && now - q[0] > 300) q.shift();
    return q.filter((t) => now - t <= sec).length;
  }
  update(eyesClosed, now, bonus = 0, hrBonus = 0) {
    if (eyesClosed != null) this.hist.push([now, eyesClosed]);
    while (this.hist.length && now - this.hist[0][0] > this.window) this.hist.shift();
    const n = this.hist.length;
    let perclos = n ? this.hist.filter((h) => h[1]).length / n : 0;
    if (n) perclos *= Math.min(1, Math.max(now - this.hist[0][0], 1e-6) / this.window);
    const parts = {
      perclos: Math.min(50, perclos * 250),
      yawns: Math.min(30, 12 * this.recent("yawn", now, 180)),
      nods: Math.min(30, 15 * this.recent("nod", now, 180)),
      slowBlinks: Math.min(20, 5 * this.recent("slow_blink", now, 60)),
      alarms: Math.min(40, 20 * this.recent("drowsy", now, 300)),
      timeRisk: bonus,
      heartRate: hrBonus,   // camera heart rate well below this driver's start value
    };
    const raw = Math.min(100, Object.values(parts).reduce((a, b) => a + b, 0));
    this.smooth += (raw - this.smooth) * (raw < this.smooth ? 0.08 : 0.25);
    return { fatigue: this.smooth, perclos, parts };
  }
}

// ------------------------------------------------------------ drive context
export function driveContext(cfg, date, driveSeconds) {
  const h = date.getHours();
  const risk = cfg.riskHours.some(([a, b]) => h >= a && h < b);
  const longDrive = Math.min(15, 5 * Math.max(0, (driveSeconds - 7200) / 3600));   // +5 per hour beyond 2 h
  return { riskHours: risk, closedFactor: risk ? cfg.riskClosedFactor : 1, bonus: (risk ? cfg.riskBonus : 0) + longDrive };
}

// ------------------------------------------------------------ everything together
export class DriverMonitor {
  constructor(cfg = CFG) {
    this.cfg = cfg;
    this.eyes = new EyeTracker(cfg);
    this.yawn = new YawnTracker(cfg);
    this.head = new HeadTracker(cfg);
    this.scorer = new FatigueScorer(cfg);
    this.level = 0; this.drowsyEvents = 0; this.distractions = 0;
    this.wasDrowsy = false; this.wasDistracted = false; this.noFaceSince = null;
    this.hdFrames = 0; this.hdClosed = 0; this.lastMouthOpen = -1e9;
  }
  get calibrating() { return this.eyes.calibrating; }
  recalibrate() { this.eyes.startCalibration(); this.head.startCalibration(); }

  // face: result of measureFace() or null; now: seconds; ctx: driveContext()
  update(face, now, ctx = { closedFactor: 1, bonus: 0, riskHours: false }) {
    const c = this.cfg;
    this.eyes.closedSeconds = c.closedSeconds * ctx.closedFactor;
    const head = this.head.update(face ? face.pose : null, now);
    const pd = head.pitchDelta;
    const thrScale = pd != null && pd > 8 ? Math.max(0.7, 1 - 0.012 * (pd - 8)) : 1;
    const st = this.eyes.update(face ? face.ear : null, now, thrScale);
    st.thrScale = thrScale;
    const events = [];
    const [yawning, newYawn] = this.yawn.update(face ? face.mar : null, now);
    const common = { head, mar: face ? face.mar : null, yawns: this.yawn.count, nods: this.head.nods,
      drowsyEvents: this.drowsyEvents, distractions: this.distractions, riskHours: ctx.riskHours };

    if (st.status === "CALIBRATING") {
      return Object.assign(st, common, { level: 0, fatigueLevel: 0, fatigue: 0, perclos: 0, yawning: false,
        events, drowsyReason: "", distracted: false, distractReason: "", parts: {} });
    }
    if (newYawn) { events.push("yawn"); this.scorer.add("yawn", now); }
    if (head.nod) { events.push("nod"); this.scorer.add("nod", now); }
    if (st.blinkDuration != null && st.blinkDuration >= c.slowBlink) { events.push("slow_blink"); this.scorer.add("slow_blink", now); }

    // eyes squeezed shut during a yawn get extra time
    if (this.yawn.openSince != null) this.lastMouthOpen = now;
    const nearYawn = now - this.lastMouthOpen <= 1.0;
    if (st.drowsy && nearYawn && st.closedFor < this.eyes.closedSeconds + c.yawnGrace) {
      st.drowsy = false; st.status = "EYES CLOSED";
    }
    // eye shape is unreliable only with the head turned very far
    if (st.drowsy && head.yawDelta != null && Math.abs(head.yawDelta) > c.earUnreliableYaw) {
      st.drowsy = false; st.status = "EYES CLOSED";
    }

    // head down: asleep (eyes closed) or looking down (eyes open)?
    if (head.headDown) { this.hdFrames++; this.hdClosed += st.eyesClosed ? 1 : 0; }
    else { this.hdFrames = 0; this.hdClosed = 0; }
    let dropAsleep = false, dropLooking = false;
    if (head.headDrop) {
      if (this.hdClosed >= 0.5 * Math.max(1, this.hdFrames)) dropAsleep = true; else dropLooking = true;
    }

    let distractReason = "";
    if (head.distracted) distractReason = "Looking away";
    else if (dropLooking) distractReason = "Looking down";
    if (!face && st.status === "NO FACE" && !this.eyes.calibrating) {
      if (this.noFaceSince == null) this.noFaceSince = now;
      const gone = now - this.noFaceSince;
      if (gone >= c.faceLostSec && gone < 60) distractReason = "Face not visible";
    } else {
      this.noFaceSince = null;
    }
    const distracted = !!distractReason;
    if (distracted && !this.wasDistracted) { this.distractions++; events.push("distracted"); }
    this.wasDistracted = distracted;

    const reasons = [];
    if (st.drowsy) reasons.push("Eyes closed");
    if (dropAsleep) reasons.push("Head drop");
    const reason = reasons.join(" + ");
    const drowsy = !!reason;
    if (drowsy && !this.wasDrowsy) { this.drowsyEvents++; events.push("drowsy"); this.scorer.add("drowsy", now); }
    this.wasDrowsy = drowsy;
    if (drowsy) { st.status = "DROWSY"; st.drowsy = true; }
    else if (distracted) st.status = "DISTRACTED";

    const { fatigue, perclos, parts } = this.scorer.update(face ? st.eyesClosed : null, now, ctx.bonus, ctx.hrBonus || 0);
    let lvl = fatigue >= c.veryTired ? 2 : fatigue >= c.tired ? 1 : 0;
    if (lvl < this.level) {
      const limits = { 1: c.tired, 2: c.veryTired };
      if (fatigue > limits[this.level] - 5) lvl = this.level;
    }
    if (lvl > this.level) events.push("level_up");
    this.level = lvl;

    return Object.assign(st, common, { drowsyEvents: this.drowsyEvents, distractions: this.distractions,
      level: drowsy ? 3 : lvl, fatigueLevel: lvl, fatigue, perclos, yawning, events,
      drowsyReason: reason, distracted, distractReason, parts });
  }
}
