// Chain-as-environment live layer (design spec section 9).
//
// No network TRANSACTIONS are ever made here -- only free, public, read-only
// JSON-RPC calls (eth_blockNumber / eth_getBlockByNumber) against BSC's
// public endpoints (site/config.js's rpcUrls), polled over plain HTTPS
// fetch() (no `wss://`, no server component, works from a static host).
//
// Every new block is ambient micro-stimulus (1-2 low bits flicker -> the fly
// twitches). Any transaction in that block at/above config.live.whaleThresholdBnb
// is a looming stimulus, scaled by size, run through the SAME netlist
// evaluator that powers the swat demo (site/js/netlist.js) -- if the reflex
// fires, the fly jumps and an event is logged. Nothing here fabricates a
// verdict: every jump/survive outcome shown is a real evaluateStimulus()
// call against the real 661-gate netlist.
//
// Honest labeling (per house style, spec section 9): this is a real-time
// SIMULATED MIRROR of the identical netlist, fed by real chain data -- the
// BSC contract (once deployed) remains the source of truth for official
// swats. See the "Live simulation..." label rendered under the canvas in
// index.html.

import { evaluateStimulus, spikePinOrder } from "./netlist.js";
import { CONFIG } from "../config.js";

export class LiveLayer {
  /**
   * @param {object} opts
   * @param {object} opts.netlist - parsed full.json
   * @param {import("./fly.js").Fly} opts.fly
   * @param {import("./circuit-viewer.js").CircuitViewer} [opts.circuitViewer]
   * @param {(evt: object) => void} [opts.onEvent] - jump/loom-survived/rpc-error events
   * @param {(info: object) => void} [opts.onBlock] - every observed block (real or synthetic)
   */
  constructor({ netlist, fly, circuitViewer, onEvent, onBlock }) {
    this.netlist = netlist;
    this.fly = fly;
    this.circuitViewer = circuitViewer || null;
    this.onEvent = onEvent || (() => {});
    this.onBlock = onBlock || (() => {});
    this.spikePins = spikePinOrder(netlist);
    this.lastBlockNumber = null;
    this._timer = null;
    this._rpcIndex = 0;
    this._running = false;

    // Playwright / manual test hook: inject a synthetic block without
    // needing a real whale transaction to show up during a test run. Never
    // used by normal site code paths -- see task brief's E2E requirement
    // ("if no whale appears during test, inject a synthetic block via a
    // test hook").
    window.__nandflyTestHook = window.__nandflyTestHook || {};
    window.__nandflyTestHook.injectBlock = (info) => this._handleBlock(info);
    window.__nandflyTestHook.injectWhale = (bnb) =>
      this._handleBlock({
        blockNumber: (this.lastBlockNumber || 0) + 1,
        txCount: 1,
        maxBnb: bnb,
        synthetic: true,
      });
  }

  start() {
    if (this._running) return;
    this._running = true;
    this._poll();
    this._timer = setInterval(() => this._poll(), CONFIG.live.pollIntervalMs);
  }

  stop() {
    this._running = false;
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  }

  async _rpcCall(method, params) {
    const urls = CONFIG.rpcUrls;
    let lastErr;
    for (let i = 0; i < urls.length; i++) {
      const url = urls[(this._rpcIndex + i) % urls.length];
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (json.error) throw new Error(json.error.message || "RPC error");
        this._rpcIndex = (this._rpcIndex + i) % urls.length;
        return json.result;
      } catch (e) {
        lastErr = e;
      }
    }
    throw lastErr || new Error("all RPC endpoints failed");
  }

  async _poll() {
    try {
      const hexNum = await this._rpcCall("eth_blockNumber", []);
      const blockNumber = parseInt(hexNum, 16);
      if (this.lastBlockNumber !== null && blockNumber <= this.lastBlockNumber) return;

      const block = await this._rpcCall("eth_getBlockByNumber", [hexNum, true]);
      if (!block) return;
      this.lastBlockNumber = blockNumber;
      this._handleRealBlock(block);
    } catch (e) {
      this.onEvent({ type: "rpc-error", message: String((e && e.message) || e) });
    }
  }

  _handleRealBlock(block) {
    const txs = block.transactions || [];
    let maxBnb = 0;
    for (const tx of txs) {
      try {
        const wei = BigInt(tx.value || "0x0");
        const bnb = Number(wei) / 1e18;
        if (bnb > maxBnb) maxBnb = bnb;
      } catch {
        // malformed value field on some node responses -- skip that tx
      }
    }
    this._handleBlock({
      blockNumber: parseInt(block.number, 16),
      txCount: txs.length,
      maxBnb,
      synthetic: false,
    });
  }

  _handleBlock({ blockNumber, txCount, maxBnb, synthetic }) {
    this.onBlock({ blockNumber, txCount, maxBnb, synthetic });
    const { whaleThresholdBnb } = CONFIG.live;
    if (maxBnb >= whaleThresholdBnb) {
      this._loomingStimulus(blockNumber, maxBnb, synthetic);
    } else {
      this._ambientStimulus();
    }
  }

  _ambientStimulus() {
    // 1-2 random low bits flicker. Still run through the real evaluator
    // (usually sub-threshold, occasionally not) rather than faking the
    // signal-flow diagram's pulse -- every pulse shown is a genuine
    // evaluateStimulus() result.
    const bits = 1 + (Math.random() < 0.3 ? 1 : 0);
    let stim = 0;
    for (let i = 0; i < bits; i++) {
      stim |= 1 << Math.floor(Math.random() * this.spikePins.length);
    }
    const result = evaluateStimulus(this.netlist, stim);
    this.fly.twitch(0.3 + Math.random() * 0.3);
    if (this.circuitViewer) this.circuitViewer.pulseEvaluation(result, stim !== 0);
    if (result.jumped) {
      this.fly.jump();
      this.onEvent({ type: "jump", source: "ambient", stimulus: stim });
    }
  }

  _loomingStimulus(blockNumber, bnb, synthetic) {
    const { whaleThresholdBnb, maxLoomBnb } = CONFIG.live;
    const frac = Math.max(
      0,
      Math.min(1, (bnb - whaleThresholdBnb) / Math.max(1, maxLoomBnb - whaleThresholdBnb))
    );
    const numBits = Math.max(1, Math.round(frac * this.spikePins.length));
    // Evenly-spaced bit selection so the pattern scales readably with size
    // (we have no per-neuron synaptic-weight metadata at this layer to pick
    // "strongest" bits by; evenly spaced is a simple, honest, reproducible
    // choice, not a claim about which real neurons a whale tx maps to).
    let stim = 0;
    const step = this.spikePins.length / numBits;
    for (let i = 0; i < numBits; i++) {
      stim |= 1 << Math.floor(i * step);
    }
    const result = evaluateStimulus(this.netlist, stim);
    this.fly.loom(frac);
    if (this.circuitViewer) this.circuitViewer.pulseEvaluation(result, true);
    if (result.jumped) this.fly.jump();
    this.onEvent({
      type: result.jumped ? "jump" : "loom-survived",
      source: synthetic ? "synthetic" : "chain",
      blockNumber,
      bnb,
      stimulus: stim,
    });
  }
}
