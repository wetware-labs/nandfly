// Top-down vector fly renderer for the live layer + swat verdict animation.
//
// Adapted from FlyMarket's arena-replay fly (drawFly() in
// a local FlyMarket checkout's site/js/replay.js -- same body/
// wing/leg vector-drawing technique and rim-light paint trick, credited here
// as the heritage this was adapted from (NOT imported; FlyMarket has no
// runtime dependency on this project or vice versa). Reworked for a
// stationary "specimen in a dish" presentation instead of an arena walk: no
// trajectory, no decision zones -- just idle breathing, ambient twitches
// (chain blocks), looming flinches (large pending stimulus), and a jump
// burst (reflex fired).
//
// Polish pass (post-launch design review): the fly reads as a small icon at
// FlyMarket's own screenshot-distance lesson ("the fly must be unmistakably
// an insect at full-page screenshot distance" -- see replay.js's FLY_SCALE
// comment). This pass (1) roughly doubles FLY_SCALE, (2) adds several
// independent-frequency idle-life oscillators so the organism is never
// caught frozen in a screenshot, (3) draws a faint circuit-trace + vignette
// environment inside the canvas with a glow that travels outward from the
// fly on every evaluation (pulse()), tying "organism" to "circuit", and
// (4) turns jump() into a crouch -> leap -> settle burst with motion
// streaks and canvas screen-shake, scaled by an intensity argument so a
// bigger whale produces a visibly bigger jump.
//
// Exposes a single Fly class: new Fly(canvas) then .start()/.stop(),
// .twitch(strength), .loom(strength), .jump(intensity), .pulse(fired).

const WALK_EPS = 0.03;
const FLY_SCALE = 92; // local body units -> canvas pixel units (~2x the original 48; tuned so a ~2.9-unit-long body reads as an unmistakable insect in a full-page screenshot, not an icon)

const FLY_LEGS = [
  { xBase: 0.68, side: 1, baseAngle: -0.55, group: "A" },
  { xBase: 0.68, side: -1, baseAngle: -0.55, group: "B" },
  { xBase: 0.18, side: 1, baseAngle: 0, group: "B" },
  { xBase: 0.18, side: -1, baseAngle: 0, group: "A" },
  { xBase: -0.32, side: 1, baseAngle: 0.55, group: "A" },
  { xBase: -0.32, side: -1, baseAngle: 0.55, group: "B" },
];

function hexToRgba(hex, alpha) {
  const v = hex.replace("#", "");
  const r = parseInt(v.substring(0, 2), 16);
  const g = parseInt(v.substring(2, 4), 16);
  const b = parseInt(v.substring(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function paintRimmed(ctx, fillColor, rimColor) {
  ctx.lineWidth = 0.22;
  ctx.strokeStyle = rimColor || "rgba(255,247,222,0.55)";
  ctx.stroke();
  ctx.fillStyle = fillColor;
  ctx.fill();
  ctx.lineWidth = 0.05;
  ctx.strokeStyle = "rgba(6,4,10,0.6)";
  ctx.stroke();
}

/** t in [0,1] -> a crouch(-anticipation) -> leap -> hold pose used by both
 * the lateral hop distance and the body-scale "squash and stretch". Kept as
 * one function so hop distance and scale pop stay in phase with each other
 * (a real jump squats exactly as it winds up, not on some unrelated clock). */
const CROUCH_END = 0.16;
function jumpPhase(t) {
  if (t < CROUCH_END) {
    // Anticipation: brief pull-back + squash before the leap fires.
    const c = t / CROUCH_END;
    return { hop: -0.04 * Math.sin(c * Math.PI), squash: 1 - 0.24 * Math.sin(c * Math.PI) };
  }
  const t2 = Math.min(1, (t - CROUCH_END) / (1 - CROUCH_END));
  const hop = 1 - Math.pow(1 - t2, 2); // ease-out: fast off the line, decelerating
  const pop = Math.sin(Math.min(t2 * 1.6, 1) * (Math.PI / 2)) * (1 - t2 * 0.55);
  return { hop, squash: 1 + pop * 0.32 };
}

export class Fly {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} [opts]
   * @param {string} [opts.accent] - rim-light accent color (hex)
   */
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.accent = opts.accent || "#F0B90B";
    this.ctx = canvas.getContext("2d");
    this._raf = null;
    this._tick = 0;
    this._lastTs = null;

    // Twitch state: quick jitter offset, decays to 0.
    this._twitchMag = 0;
    this._twitchSeed = Math.random() * 1000;

    // Loom state: sustained flinch intensity 0..1, decays slowly.
    this._loomMag = 0;

    // Jump burst state: 0..1, drives the crouch/leap/settle pose. `_jumpMag`
    // scales the whole burst (bigger whale -> bigger jump); defaults to 1
    // (full drama) for callers that don't pass an intensity, e.g. the swat
    // verdict.
    this._jumpT = 0;
    this._jumping = false;
    this._jumpDir = 1;
    this._jumpMag = 1;

    // Idle-life oscillators: independent periods/phases so the organism
    // never lands on the exact same pose twice, and so two screenshots
    // taken seconds apart always differ (design review requirement: "must
    // NEVER look frozen"). Each is a plain function of elapsed time, which
    // is effectively an independent free-running timer since none of their
    // periods share a common short cycle.
    this._wanderSeedX = Math.random() * 1000;
    this._wanderSeedY = Math.random() * 1000;
    this._nextFlickAt = 1500 + Math.random() * 3000;
    this._flickMag = 0;
    this._legPhaseSeed = FLY_LEGS.map(() => Math.random() * Math.PI * 2);

    // Evaluation glow pulses that travel outward from the fly along the
    // background circuit traces -- see pulse().
    this._pulses = [];
    // Motion-streak trail sampled while leaping.
    this._trail = [];
    // Screen-shake-lite offset, decays independently of the jump pose.
    this._shakeMag = 0;

    this._resize();
    this._onResize = () => this._resize();
    window.addEventListener("resize", this._onResize);
  }

  _resize() {
    const canvas = this.canvas;
    const parent = canvas.parentElement;
    const cssWidth = parent ? parent.clientWidth : canvas.clientWidth || 300;
    // Prefer the wrapping element's own CSS-defined height (the hero stage
    // sizes its canvas wrap via viewport-relative CSS so the fly reads as a
    // tall, full-width hero) over a fixed aspect ratio; fall back to the
    // original 0.62 aspect ratio for any box that doesn't set an explicit
    // height (shrink-to-fit).
    const parentHeight = parent ? parent.clientHeight : 0;
    const cssHeight = parentHeight > 0 ? parentHeight : Math.round(cssWidth * 0.62);
    const dpr = window.devicePixelRatio || 1;
    canvas.style.width = cssWidth + "px";
    canvas.style.height = cssHeight + "px";
    canvas.width = Math.round(cssWidth * dpr);
    canvas.height = Math.round(cssHeight * dpr);
    this._w = cssWidth;
    this._h = cssHeight;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this._traces = this._buildTraces(cssWidth, cssHeight);
  }

  /** Procedural faint PCB-style trace motif: a handful of orthogonal
   * polylines running from the stage edges toward the center, regenerated
   * whenever the canvas resizes. Purely decorative background texture --
   * never touches evaluation state -- drawn at very low contrast so it
   * reads as "circuit" without competing with the fly or the feed. */
  _buildTraces(w, h) {
    const traces = [];
    const cx = w / 2;
    const cy = h / 2;
    const n = 9;
    for (let i = 0; i < n; i++) {
      const angle = (i / n) * Math.PI * 2 + Math.random() * 0.4;
      const startR = Math.max(w, h) * 0.65;
      let x = cx + Math.cos(angle) * startR;
      let y = cy + Math.sin(angle) * startR;
      const pts = [[x, y]];
      const hops = 2 + Math.floor(Math.random() * 3);
      for (let j = 0; j < hops; j++) {
        const towardCenter = j === hops - 1;
        if (towardCenter) {
          x = cx + Math.cos(angle) * (30 + Math.random() * 40);
          y = cy + Math.sin(angle) * (30 + Math.random() * 40);
        } else if (Math.random() < 0.5) {
          x += (cx - x) * (0.2 + Math.random() * 0.25);
        } else {
          y += (cy - y) * (0.2 + Math.random() * 0.25);
        }
        pts.push([x, y]);
      }
      traces.push(pts);
    }
    return traces;
  }

  /** Ambient micro-stimulus: a quick, small jitter. strength in [0,1]. */
  twitch(strength = 0.35) {
    this._twitchMag = Math.max(this._twitchMag, strength);
  }

  /** Looming stimulus building: sustained flinch intensity, strength in
   * [0,1] (0 = none, 1 = as large as the fly gets before a jump verdict). */
  loom(strength) {
    this._loomMag = Math.max(0, Math.min(1, strength));
  }

  /** Reflex fired: full jump burst (crouch -> leap -> settle), with motion
   * streaks and a canvas screen-shake. `intensity` in [0,1] scales the whole
   * burst -- pass the same whale-size fraction live-layer.js uses to pick
   * the stimulus bit count so a bigger whale visibly produces a bigger
   * jump. Defaults to 1 (full drama) for callers with no size context (the
   * swat verdict button). */
  jump(intensity = 1) {
    this._jumping = true;
    this._jumpT = 0;
    this._jumpDir = Math.random() < 0.5 ? -1 : 1;
    this._jumpMag = Math.max(0.35, Math.min(1, intensity));
    this._shakeMag = 1;
    this._trail = [];
  }

  /** Every real evaluateStimulus() call (ambient, looming, or a swat) fires
   * this so the environment glow travels outward from the fly along the
   * circuit traces -- the visual link between "organism" and "circuit".
   * `fired` (bool) makes a jump's pulse brighter/wider than a survived one. */
  pulse(fired = false) {
    this._pulses.push({ t0: this._tick, fired: !!fired });
    if (this._pulses.length > 6) this._pulses.shift();
  }

  start() {
    if (this._raf) return;
    const loop = (ts) => {
      const dt = this._lastTs ? ts - this._lastTs : 16;
      this._lastTs = ts;
      this._tick += dt;
      this._step(dt);
      this._draw();
      this._raf = requestAnimationFrame(loop);
    };
    this._raf = requestAnimationFrame(loop);
  }

  stop() {
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
    window.removeEventListener("resize", this._onResize);
  }

  _step(dt) {
    // Decay twitch quickly (it's a flicker, not a mood).
    this._twitchMag *= Math.exp(-dt / 140);
    if (this._twitchMag < 0.01) this._twitchMag = 0;

    // Loom decays slowly if not being re-driven by the caller each frame.
    this._loomMag *= Math.exp(-dt / 900);

    if (this._jumping) {
      this._jumpT += dt / 900; // crouch + leap + settle
      if (this._jumpT >= 1) {
        this._jumpT = 1;
        this._jumping = false;
      }
    } else if (this._jumpT > 0) {
      this._jumpT = Math.max(0, this._jumpT - dt / 420);
    }

    // Screen-shake decays independently and fast -- it's a jolt, not a mood.
    this._shakeMag *= Math.exp(-dt / 260);
    if (this._shakeMag < 0.01) this._shakeMag = 0;

    // Occasional wing flick: an independent free-running timer, unrelated
    // to twitch/loom/jump, so the wings do *something* on their own even
    // during a long idle stretch between chain blocks.
    if (this._tick >= this._nextFlickAt) {
      this._flickMag = 1;
      this._nextFlickAt = this._tick + 2200 + Math.random() * 3600;
    }
    this._flickMag *= Math.exp(-dt / 180);
    if (this._flickMag < 0.01) this._flickMag = 0;

    // Prune spent evaluation-glow pulses.
    if (this._pulses.length) {
      this._pulses = this._pulses.filter((p) => this._tick - p.t0 < 1100);
    }
  }

  _draw() {
    const ctx = this.ctx;
    const w = this._w;
    const h = this._h;
    ctx.clearRect(0, 0, w, h);

    const cx = w / 2;
    const cy = h / 2;

    // Screen-shake-lite: jolt the whole scene (background + fly) briefly
    // right as a jump fires, then settle. Pure jitter (not smoothed) reads
    // as impact rather than drift.
    let shakeX = 0;
    let shakeY = 0;
    if (this._shakeMag > 0) {
      const amp = this._shakeMag * this._jumpMag * 6;
      shakeX = (Math.random() - 0.5) * amp;
      shakeY = (Math.random() - 0.5) * amp;
    }
    ctx.save();
    ctx.translate(shakeX, shakeY);

    this._drawEnvironment(ctx, w, h, cx, cy);

    // Slow, always-on wander within a bounded region -- independent
    // low-frequency oscillators so the fly's resting position drifts
    // without ever leaving the stage. Runs regardless of twitch/loom/jump
    // state (small enough not to fight them).
    const wanderX = Math.sin(this._tick * 0.00023 + this._wanderSeedX) * Math.min(w, h) * 0.05;
    const wanderY = Math.cos(this._tick * 0.00017 + this._wanderSeedY) * Math.min(w, h) * 0.035;
    // Slow body bob, a different period again so it never phase-locks with
    // the wander drift.
    const bobY = Math.sin(this._tick * 0.0009) * 2.4;

    // Jump hop arc: lateral dash + a vertical "lift" (simulated by scale
    // pop) + settle. jumpT goes 0->1 through crouch/leap, then eases back.
    let hopX = 0;
    let hopScale = 1;
    if (this._jumpT > 0) {
      const pose = jumpPhase(this._jumpT);
      hopX = this._jumpDir * pose.hop * Math.min(w, h) * 0.32 * this._jumpMag;
      hopScale = 1 + (pose.squash - 1) * (0.6 + this._jumpMag * 0.4);
    }

    // Twitch jitter: small random-walk-ish offset seeded by tick.
    const tw = this._twitchMag;
    const jitterX = tw > 0 ? Math.sin((this._tick + this._twitchSeed) * 0.09) * tw * 5 : 0;
    const jitterY = tw > 0 ? Math.cos((this._tick + this._twitchSeed) * 0.11) * tw * 3 : 0;

    // Idle breathing tremor, layered on top of the wander/bob above --
    // slightly stronger under loom (the fly is tense).
    const tremorX = Math.sin(this._tick * 0.0018) * (0.6 + this._loomMag * 0.8);
    const tremorY = Math.cos(this._tick * 0.0015) * (0.5 + this._loomMag * 0.6);

    const x = cx + wanderX + hopX + jitterX + tremorX;
    const y = cy + wanderY + bobY + jitterY + tremorY;

    // Motion-streak trail: sample recent positions while actively leaping
    // so the burst reads as fast motion, not a teleport.
    const leaping = this._jumping && this._jumpT > CROUCH_END;
    if (leaping) {
      this._trail.push({ x, y, t: this._tick });
      if (this._trail.length > 7) this._trail.shift();
    }
    this._drawTrail(ctx);

    // Slight heading wobble under loom (fly angles away from the threat).
    const heading = this._loomMag * 0.12 * Math.sin(this._tick * 0.01) - (this._jumpDir * this._jumpT * 0.35);

    this._drawFly(ctx, x, y, heading, hopScale, this._loomMag, this._jumpT > 0.05 ? Math.sin(this._jumpT * Math.PI) : 0);

    this._drawPulses(ctx, x, y);

    ctx.restore();
  }

  /** Faint PCB traces + a soft vignette -- the "specimen in a dish sitting
   * inside a circuit" environment. Drawn every frame but at very low
   * contrast (alpha <= 0.12) so it never competes with the fly itself. */
  _drawEnvironment(ctx, w, h, cx, cy) {
    ctx.save();
    ctx.strokeStyle = hexToRgba(this.accent, 0.07);
    ctx.lineWidth = 1;
    ctx.lineJoin = "round";
    for (const trace of this._traces || []) {
      ctx.beginPath();
      ctx.moveTo(trace[0][0], trace[0][1]);
      for (let i = 1; i < trace.length; i++) ctx.lineTo(trace[i][0], trace[i][1]);
      ctx.stroke();
      // Via dot at each trace's inner end -- reads as a circuit pad.
      const last = trace[trace.length - 1];
      ctx.beginPath();
      ctx.arc(last[0], last[1], 1.6, 0, Math.PI * 2);
      ctx.fillStyle = hexToRgba(this.accent, 0.1);
      ctx.fill();
    }

    const vignette = ctx.createRadialGradient(cx, cy, Math.min(w, h) * 0.2, cx, cy, Math.max(w, h) * 0.75);
    vignette.addColorStop(0, "rgba(0,0,0,0)");
    vignette.addColorStop(1, "rgba(0,0,0,0.38)");
    ctx.fillStyle = vignette;
    ctx.fillRect(0, 0, w, h);
    ctx.restore();
  }

  _drawTrail(ctx) {
    if (this._trail.length < 2) return;
    ctx.save();
    ctx.lineCap = "round";
    for (let i = 1; i < this._trail.length; i++) {
      const a = this._trail[i - 1];
      const b = this._trail[i];
      const age = i / this._trail.length; // 0 (oldest) .. 1 (newest)
      ctx.strokeStyle = hexToRgba(this.accent, 0.05 + age * 0.22);
      ctx.lineWidth = 1 + age * 3;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
    ctx.restore();
  }

  /** Rings that expand outward from the fly's current position on every
   * evaluation, brightening any circuit trace they sweep past -- the visual
   * "organism wired into the circuit" link. */
  _drawPulses(ctx, originX, originY) {
    if (!this._pulses.length) return;
    const maxRadius = Math.min(this._w, this._h) * 0.7;
    for (const p of this._pulses) {
      const age = this._tick - p.t0;
      const duration = p.fired ? 950 : 650;
      if (age >= duration) continue;
      const t = age / duration;
      const radius = t * maxRadius;
      const alpha = (1 - t) * (p.fired ? 0.5 : 0.22);

      ctx.save();
      ctx.strokeStyle = hexToRgba(this.accent, alpha);
      ctx.lineWidth = p.fired ? 2.4 : 1.4;
      ctx.beginPath();
      ctx.arc(originX, originY, radius, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();

      // Brighten trace segments the ring is currently sweeping through.
      const band = 26;
      for (const trace of this._traces || []) {
        for (let i = 1; i < trace.length; i++) {
          const mx = (trace[i - 1][0] + trace[i][0]) / 2;
          const my = (trace[i - 1][1] + trace[i][1]) / 2;
          const d = Math.hypot(mx - originX, my - originY);
          if (Math.abs(d - radius) > band) continue;
          const close = 1 - Math.abs(d - radius) / band;
          ctx.save();
          ctx.strokeStyle = hexToRgba(this.accent, alpha * close * 0.9);
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.moveTo(trace[i - 1][0], trace[i - 1][1]);
          ctx.lineTo(trace[i][0], trace[i][1]);
          ctx.stroke();
          ctx.restore();
        }
      }
    }
  }

  _drawFly(ctx, x, y, heading, extraScale, loom, burst) {
    const scale = FLY_SCALE * extraScale * (1 + loom * 0.08);
    const tick = this._tick;
    const speed = burst > 0 ? 1 : 0; // drives walking-gait leg pose during a jump

    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(heading);
    ctx.scale(scale, scale);

    // --- Legs ---
    // Real fly legs are hair-thin relative to the body no matter how big
    // the fly is drawn, so the stroke width is expressed as a constant
    // *screen*-pixel width (divided by `scale` here, since ctx is already
    // scaled by FLY_SCALE below this point) rather than a local-unit width
    // that would grow along with FLY_SCALE and turn into thick zigzag bars
    // (that's exactly what happened when this pass first doubled FLY_SCALE
    // -- legs became the dominant, ugly shape instead of a background
    // detail). LEG_REACH likewise pulls the leg geometry in closer to the
    // body than a naive uniform scale-up would, so legs read as legs, not
    // as a chevron crossing the wings.
    const LEG_REACH = 0.62;
    ctx.strokeStyle = "rgba(196,192,200,0.85)";
    ctx.lineWidth = 2.3 / scale;
    ctx.lineCap = "round";
    const walking = speed > WALK_EPS;
    const gaitPhase = tick * (0.012 + Math.min(speed, 1) * 0.03);
    for (let i = 0; i < FLY_LEGS.length; i++) {
      const leg = FLY_LEGS[i];
      let sweep;
      let reach = 1;
      if (walking) {
        const groupOffset = leg.group === "A" ? 0 : Math.PI;
        const s = Math.sin(gaitPhase + groupOffset);
        sweep = s * 0.32;
        reach = 0.85 + 0.15 * Math.cos(gaitPhase + groupOffset);
      } else {
        // Micro leg tremor: each leg on its own slightly-detuned frequency
        // and phase (this._legPhaseSeed) so the legs never move in
        // lockstep -- reads as organic fidgeting, not a synced animation.
        const freq = 0.0026 + i * 0.00035;
        sweep = Math.sin(tick * freq + this._legPhaseSeed[i]) * (0.045 + loom * 0.05);
      }
      const angle = leg.baseAngle + sweep;
      const legLen = 1.05 * LEG_REACH * reach;
      const footX = leg.xBase + Math.sin(angle) * legLen;
      const footY = leg.side * Math.cos(angle) * legLen;
      const kneeX = leg.xBase + Math.sin(angle) * legLen * 0.5;
      const kneeY = leg.side * (0.5 + Math.cos(angle) * legLen * 0.72);
      ctx.beginPath();
      ctx.moveTo(leg.xBase, leg.side * 0.32);
      ctx.lineTo(kneeX, kneeY);
      ctx.lineTo(footX, footY);
      ctx.stroke();
    }
    ctx.lineCap = "butt";

    // --- Wings ---
    const wingRoot = { x: 0.25, y: 0.28 };
    const idleAngle = 0.18 + loom * 0.15 + this._flickMag * 0.38;
    const flightAngle = 0.62 + burst * 0.35;
    for (let side = -1; side <= 1; side += 2) {
      const angle =
        walking || burst > 0
          ? flightAngle + Math.sin(tick * 0.09 + (side > 0 ? 0 : Math.PI)) * (0.22 + burst * 0.15)
          : idleAngle;
      const alpha =
        walking || burst > 0
          ? 0.16 + 0.14 * Math.abs(Math.cos(tick * 0.09 + (side > 0 ? 0 : Math.PI)))
          : 0.12 + loom * 0.06 + this._flickMag * 0.18;
      ctx.save();
      ctx.translate(wingRoot.x, side * wingRoot.y);
      ctx.rotate(side * angle);
      ctx.fillStyle = `rgba(210,230,255,${(alpha + burst * 0.1).toFixed(3)})`;
      ctx.beginPath();
      ctx.ellipse(0.55, side * 0.42, 0.85, 0.42, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    const accentRim = hexToRgba(this.accent, 0.4 + loom * 0.3 + burst * 0.3);

    // --- Abdomen ---
    ctx.beginPath();
    ctx.moveTo(-0.02, 0.32);
    ctx.bezierCurveTo(-0.35, 0.4, -0.72, 0.5, -1.5, 0.02);
    ctx.bezierCurveTo(-0.72, -0.5, -0.35, -0.4, -0.02, -0.32);
    ctx.closePath();
    paintRimmed(ctx, "#26232a", accentRim);
    ctx.fillStyle = "rgba(255,255,255,0.06)";
    ctx.beginPath();
    ctx.ellipse(-0.45, -0.08, 0.4, 0.13, 0.15, 0, Math.PI * 2);
    ctx.fill();

    // --- Thorax ---
    ctx.beginPath();
    ctx.ellipse(0.35, 0, 0.42, 0.4, 0, 0, Math.PI * 2);
    paintRimmed(ctx, "#2d2a30", accentRim);

    // --- Head ---
    ctx.beginPath();
    ctx.ellipse(1.05, 0, 0.34, 0.27, 0, 0, Math.PI * 2);
    paintRimmed(ctx, "#18161a", accentRim);

    // Eyes -- glow with accent under loom/burst (looking at the threat).
    ctx.fillStyle = burst > 0 || loom > 0.3 ? this.accent : "#0c0c0e";
    ctx.beginPath();
    ctx.arc(1.12, 0.16, 0.09, 0, Math.PI * 2);
    ctx.arc(1.12, -0.16, 0.09, 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
  }
}
