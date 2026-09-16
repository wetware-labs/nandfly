// Swat UI: the 12-bit stimulus builder, presets, [SWAT] button, verdict
// animation, and the "official tx" calldata panel (spec section 3).
//
// Free swat: eth_call against the deployed contract's swat(uint16) when
// site/config.js has a contractAddress; otherwise falls back to the local
// evaluator (site/js/netlist.js) with a visible "pre-deploy simulation"
// badge -- never silently pretends to be on-chain when it isn't.
//
// Official tx mode: never sends anything itself (zero deps -- no wallet
// SDK). Shows the exact swatTx(uint16) calldata and a copy-paste path for
// the user's own wallet. A wallet deep-link (e.g. a `bnb:` / WalletConnect
// URI) is documented as a v2 follow-up, not built here.

import { evaluateStimulus, packStimulusBits } from "./netlist.js";
import { encodeUint16Call, decodeBool3, SELECTORS } from "./abi.js";
import { CONFIG } from "../config.js";

const GROUP_ORDER = ["LC4-L", "LPLC2-L", "LC4-R", "LPLC2-R"];

const PRESETS = {
  "weak flicker": (pins) => {
    const bits = {};
    for (const p of pins) bits[p] = 0;
    bits[pins[0]] = 1;
    return bits;
  },
  "incoming swatter": (pins) => {
    const bits = {};
    pins.forEach((p, i) => {
      bits[p] = i % 2 === 0 ? 1 : 0;
    });
    return bits;
  },
  "full loom": (pins) => {
    const bits = {};
    for (const p of pins) bits[p] = 1;
    return bits;
  },
};

function neuronGroupKey(n) {
  return `${n.type}-${n.side}`;
}

export class SwatUI {
  constructor(container, netlist, opts = {}) {
    this.container = container;
    this.netlist = netlist;
    this.fly = opts.fly || null;
    this.circuitViewer = opts.circuitViewer || null;
    this.visualNeurons = netlist.neuron_gate_map.filter((n) => n.role === "visual_input");
    this.spikePins = this.visualNeurons.map((n) => n.signal);
    this.bits = {};
    for (const pin of this.spikePins) this.bits[pin] = 0;
    this._render();
  }

  _render() {
    this.container.innerHTML = "";

    const groups = new Map();
    for (const n of this.visualNeurons) {
      const key = neuronGroupKey(n);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(n);
    }

    const builder = document.createElement("div");
    builder.className = "swat-builder";
    for (const key of GROUP_ORDER) {
      const neurons = groups.get(key);
      if (!neurons) continue;
      const col = document.createElement("div");
      col.className = "swat-group";
      const h = document.createElement("h5");
      h.textContent = key;
      col.appendChild(h);
      for (const n of neurons) {
        const label = document.createElement("label");
        label.className = "swat-toggle";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.dataset.pin = n.signal;
        cb.addEventListener("change", () => {
          this.bits[n.signal] = cb.checked ? 1 : 0;
        });
        const span = document.createElement("span");
        span.textContent = `body #${n.neuron_id}`;
        label.appendChild(cb);
        label.appendChild(span);
        col.appendChild(label);
      }
      builder.appendChild(col);
    }
    this.container.appendChild(builder);

    const presetRow = document.createElement("div");
    presetRow.className = "swat-presets";
    for (const name of Object.keys(PRESETS)) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-ghost";
      btn.textContent = name;
      btn.addEventListener("click", () => this._applyPreset(name));
      presetRow.appendChild(btn);
    }
    this.container.appendChild(presetRow);

    const actionRow = document.createElement("div");
    actionRow.className = "swat-actions";
    const swatBtn = document.createElement("button");
    swatBtn.type = "button";
    swatBtn.className = "btn btn-primary swat-btn";
    swatBtn.textContent = "SWAT (free)";
    swatBtn.addEventListener("click", () => this._runSwat());
    actionRow.appendChild(swatBtn);

    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = CONFIG.contractAddress ? "on-chain (eth_call)" : "pre-deploy simulation";
    actionRow.appendChild(badge);
    this.container.appendChild(actionRow);

    this.verdictEl = document.createElement("div");
    this.verdictEl.className = "swat-verdict";
    this.container.appendChild(this.verdictEl);

    this._renderTxPanel();
  }

  _renderTxPanel() {
    const panel = document.createElement("details");
    panel.className = "swat-tx-panel";
    const summary = document.createElement("summary");
    summary.textContent = "Official tx mode (send via your wallet)";
    panel.appendChild(summary);

    const body = document.createElement("div");
    body.className = "swat-tx-body";
    this._txBody = body;
    panel.appendChild(body);
    this._renderTxCalldata();

    this.container.appendChild(panel);
  }

  _renderTxCalldata() {
    if (!this._txBody) return;
    const stimulus = packStimulusBits(this.netlist, this.bits);
    const calldata = encodeUint16Call(SELECTORS["swatTx(uint16)"], stimulus);
    const address = CONFIG.contractAddress || "(not deployed yet -- see METHODS)";
    this._txBody.innerHTML = `
      <p>This calls <code>swatTx(uint16)</code> -- the same evaluation as the free swat above, but as a real transaction: it emits a <code>Swatted</code> event and increments the public counters. No fee beyond gas; the contract cannot hold value (see METHODS).</p>
      <p>Target contract: <code>${address}</code></p>
      <p>Calldata (copy into your wallet's "contract interaction" / raw data field):</p>
      <pre class="calldata">${calldata}</pre>
      <p class="hint">Deep-link "open in wallet" (WalletConnect / mobile deep link) is a documented v2 follow-up -- this site stays zero-deps and never touches your keys.</p>
    `;
  }

  _applyPreset(name) {
    const fn = PRESETS[name];
    if (!fn) return;
    this.bits = fn(this.spikePins);
    for (const cb of this.container.querySelectorAll('input[type="checkbox"][data-pin]')) {
      cb.checked = !!this.bits[cb.dataset.pin];
    }
    this._renderTxCalldata();
  }

  async _runSwat() {
    const stimulus = packStimulusBits(this.netlist, this.bits);
    let result;
    let mode;
    try {
      if (CONFIG.contractAddress) {
        mode = "on-chain";
        result = await this._evalOnChain(stimulus);
      } else {
        mode = "pre-deploy simulation";
        result = evaluateStimulus(this.netlist, stimulus);
      }
    } catch (e) {
      // e.message may originate from a third-party RPC endpoint's eth_call
      // error response -- build via textContent, never innerHTML, so it can
      // never be treated as markup.
      this.verdictEl.textContent = "";
      const p = document.createElement("p");
      p.className = "swat-error";
      p.textContent = `Evaluation failed: ${String((e && e.message) || e)}`;
      this.verdictEl.appendChild(p);
      return;
    }

    if (this.circuitViewer) this.circuitViewer.pulseEvaluation(result, stimulus !== 0);
    if (this.fly) {
      if (result.jumped) this.fly.jump();
      else this.fly.twitch(0.5);
    }
    this._renderVerdict(result, mode, stimulus);
    this._renderTxCalldata();
  }

  async _evalOnChain(stimulus) {
    const data = encodeUint16Call(SELECTORS["swat(uint16)"], stimulus);
    // Try each configured endpoint in order (same fallback pattern as
    // live-layer.js) so a single flaky public RPC can't break the swat CTA.
    const urls = CONFIG.rpcUrls;
    let lastErr;
    for (const url of urls) {
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: 1,
            method: "eth_call",
            params: [{ to: CONFIG.contractAddress, data }, "latest"],
          }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (json.error) throw new Error(json.error.message || "eth_call failed");
        const [jumped, jumpLeft, jumpRight] = decodeBool3(json.result);
        return { jumped, jumpLeft, jumpRight };
      } catch (e) {
        lastErr = e;
      }
    }
    throw lastErr || new Error("all RPC endpoints failed");
  }

  _renderVerdict(result, mode, stimulus) {
    const verdict = result.jumped ? "IT JUMPED." : "it ignored you.";
    const survived = result.jumped ? "no" : "yes";
    this.verdictEl.innerHTML = `
      <p class="verdict-line">${verdict} survived: ${survived}</p>
      <p class="verdict-meta">stimulus 0x${stimulus.toString(16).padStart(3, "0")} &middot; jump_left=${result.jumpLeft} &middot; jump_right=${result.jumpRight} &middot; ${mode}</p>
    `;
  }
}
