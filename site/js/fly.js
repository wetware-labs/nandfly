// Top-down vector fly renderer for the live layer + swat verdict animation.
//
// Adapted from FlyMarket's arena-replay fly (drawFly() in
// C:\Users\gmldn\Documents\Codex\flymarket\site\js\replay.js) -- same body/
// wing/leg vector-drawing technique and rim-light paint trick, credited here
// as the heritage this was adapted from (NOT imported; FlyMarket has no
// runtime dependency on this project or vice versa). Reworked for a
// stationary "specimen in a dish" presentation instead of an arena walk: no
// trajectory, no decision zones -- just idle breathing, ambient twitches
// (chain blocks), looming flinches (large pending stimulus), and a jump
// burst (reflex fired).
//
// Exposes a single Fly class: new Fly(canvas) then .start()/.stop(),
// .twitch(strength), .loom(strength), .jump().

const WALK_EPS = 0.03;
const FLY_SCALE = 48; // local body units -> canvas pixel units (tuned for a ~600px-wide stage)

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

export class Fly {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} [opts]
   * @param {string} [opts.accent] - rim-light accent color (hex)
   */
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.accent = opts.accent || "#8b7cff";
    this.ctx = canvas.getContext("2d");
    this._raf = null;
    this._tick = 0;
    this._lastTs = null;

    // Twitch state: quick jitter offset, decays to 0.
    this._twitchMag = 0;
    this._twitchSeed = Math.random() * 1000;

    // Loom state: sustained flinch intensity 0..1, decays slowly.
    this._loomMag = 0;

    // Jump burst state: 0..1, drives the hop + wing flutter.
    this._jumpT = 0;
    this._jumping = false;
    this._jumpDir = 1;

    this._resize();
    this._onResize = () => this._resize();
    window.addEventListener("resize", this._onResize);
  }

  _resize() {
    const canvas = this.canvas;
    const cssWidth = canvas.parentElement ? canvas.parentElement.clientWidth : canvas.clientWidth || 300;
    const cssHeight = Math.round(cssWidth * 0.62);
    const dpr = window.devicePixelRatio || 1;
    canvas.style.width = cssWidth + "px";
    canvas.style.height = cssHeight + "px";
    canvas.width = Math.round(cssWidth * dpr);
    canvas.height = Math.round(cssHeight * dpr);
    this._w = cssWidth;
    this._h = cssHeight;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
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

  /** Reflex fired: full jump animation burst. */
  jump() {
    this._jumping = true;
    this._jumpT = 0;
    this._jumpDir = Math.random() < 0.5 ? -1 : 1;
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
      this._jumpT += dt / 650; // ~650ms hop
      if (this._jumpT >= 1) {
        this._jumpT = 1;
        this._jumping = false;
      }
    } else if (this._jumpT > 0) {
      this._jumpT = Math.max(0, this._jumpT - dt / 400);
    }
  }

  _draw() {
    const ctx = this.ctx;
    const w = this._w;
    const h = this._h;
    ctx.clearRect(0, 0, w, h);

    const cx = w / 2;
    const cy = h / 2;

    // Jump hop arc: lateral dash + a vertical "lift" (simulated by scale
    // pop) + settle. jumpT goes 0->1 during the hop, then eases back.
    let hopX = 0;
    let hopScale = 1;
    if (this._jumpT > 0) {
      const t = this._jumpT;
      // Fast out, slow settle: ease-out-back-ish curve.
      const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      hopX = this._jumpDir * ease * Math.min(w, h) * 0.28;
      hopScale = 1 + Math.sin(t * Math.PI) * 0.22;
    }

    // Twitch jitter: small random-walk-ish offset seeded by tick.
    const tw = this._twitchMag;
    const jitterX = tw > 0 ? Math.sin((this._tick + this._twitchSeed) * 0.09) * tw * 5 : 0;
    const jitterY = tw > 0 ? Math.cos((this._tick + this._twitchSeed) * 0.11) * tw * 3 : 0;

    // Idle breathing tremor when fully calm.
    const calm = tw === 0 && this._loomMag < 0.02 && this._jumpT === 0;
    const tremorX = calm ? Math.sin(this._tick * 0.0018) * 0.6 : 0;
    const tremorY = calm ? Math.cos(this._tick * 0.0015) * 0.5 : 0;

    const x = cx + hopX + jitterX + tremorX;
    const y = cy + jitterY + tremorY;

    // Slight heading wobble under loom (fly angles away from the threat).
    const heading = this._loomMag * 0.12 * Math.sin(this._tick * 0.01) - (this._jumpDir * this._jumpT * 0.35);

    this._drawFly(ctx, x, y, heading, hopScale, this._loomMag, this._jumpT > 0.05 ? Math.sin(this._jumpT * Math.PI) : 0);
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
    ctx.strokeStyle = "rgba(180,168,220,0.85)";
    ctx.lineWidth = 0.13;
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
        sweep = Math.sin(tick * 0.003 + i) * (0.02 + loom * 0.04);
      }
      const angle = leg.baseAngle + sweep;
      const legLen = 1.05 * reach;
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
    const idleAngle = 0.18 + loom * 0.15;
    const flightAngle = 0.62 + burst * 0.35;
    for (let side = -1; side <= 1; side += 2) {
      const angle =
        walking || burst > 0
          ? flightAngle + Math.sin(tick * 0.09 + (side > 0 ? 0 : Math.PI)) * (0.22 + burst * 0.15)
          : idleAngle;
      const alpha =
        walking || burst > 0
          ? 0.16 + 0.14 * Math.abs(Math.cos(tick * 0.09 + (side > 0 ? 0 : Math.PI)))
          : 0.12 + loom * 0.06;
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
    paintRimmed(ctx, "#2b2438", accentRim);
    ctx.fillStyle = "rgba(255,255,255,0.06)";
    ctx.beginPath();
    ctx.ellipse(-0.45, -0.08, 0.4, 0.13, 0.15, 0, Math.PI * 2);
    ctx.fill();

    // --- Thorax ---
    ctx.beginPath();
    ctx.ellipse(0.35, 0, 0.42, 0.4, 0, 0, Math.PI * 2);
    paintRimmed(ctx, "#332b44", accentRim);

    // --- Head ---
    ctx.beginPath();
    ctx.ellipse(1.05, 0, 0.34, 0.27, 0, 0, Math.PI * 2);
    paintRimmed(ctx, "#1c1726", accentRim);

    // Eyes -- glow with accent under loom/burst (looking at the threat).
    ctx.fillStyle = burst > 0 || loom > 0.3 ? this.accent : "#0c0910";
    ctx.beginPath();
    ctx.arc(1.12, 0.16, 0.09, 0, Math.PI * 2);
    ctx.arc(1.12, -0.16, 0.09, 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
  }
}
