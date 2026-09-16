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
import { encodeUint16Call, decodeBool3, SELECTORS, SWATTED_TOPIC0 } from "./abi.js";
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

    // One-click path: only offered when the browser has an injected
    // EIP-1193 provider (MetaMask, Rabby, ...). We never bundle a wallet
    // SDK (zero deps) and never touch keys -- the wallet itself shows and
    // approves the single swatTx(uint16) transaction we construct.
    const oneClick = document.createElement("div");
    oneClick.className = "oneclick-swat";
    if (window.ethereum && CONFIG.contractAddress) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-primary oneclick-swat-btn";
      btn.textContent = "SWAT ON-CHAIN (your wallet)";
      const status = document.createElement("p");
      status.className = "oneclick-status hint";
      status.textContent =
        "One transaction, built in front of you: swatTx(uint16) with the stimulus selected above. The only cost is gas.";
      btn.addEventListener("click", () => this._oneClickSwat(btn, status));
      oneClick.appendChild(btn);
      oneClick.appendChild(status);
      this._oneClickStatus = status;
    } else {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = CONFIG.contractAddress
        ? "No browser wallet detected -- with one installed (MetaMask, Rabby, ...) this becomes a single click. The manual path below works with any wallet:"
        : "";
      oneClick.appendChild(p);
    }
    body.appendChild(oneClick);

    const info = document.createElement("div");
    this._txInfo = info;
    body.appendChild(info);
    this._renderTxCalldata();

    this.container.appendChild(panel);
  }

  _renderTxCalldata() {
    if (!this._txInfo) return;
    const stimulus = packStimulusBits(this.netlist, this.bits);
    const calldata = encodeUint16Call(SELECTORS["swatTx(uint16)"], stimulus);
    const address = CONFIG.contractAddress || "(not deployed yet -- see METHODS)";
    this._txInfo.innerHTML = `
      <p>This calls <code>swatTx(uint16)</code> -- the same evaluation as the free swat above, but as a real transaction: it emits a <code>Swatted</code> event and increments the public counters. No fee beyond gas; the contract cannot hold value (see METHODS).</p>
      <p>Target contract: <code>${address}</code></p>
      <p>Calldata (copy into your wallet's "contract interaction" / raw data field):</p>
      <pre class="calldata">${calldata}</pre>
      <p class="hint">WalletConnect / mobile deep link is a documented v2 follow-up -- this site stays zero-deps and never touches your keys.</p>
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
    // Empty stimulus is a valid input (the contract would honestly return
    // "no jump"), but a first-time visitor clicking SWAT before selecting
    // anything reads that as broken. Guide instead of evaluating -- and
    // never render it as a verdict, since no evaluation happened.
    if (stimulus === 0) {
      this.verdictEl.innerHTML = "";
      const p = document.createElement("p");
      p.className = "swat-hint";
      p.textContent =
        "You swung at nothing (stimulus 0x000) -- the fly can't see a swat that isn't there. Check some inputs above or hit a preset like \"full loom\", then SWAT.";
      this.verdictEl.appendChild(p);
      return;
    }
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
      this.fly.pulse(result.jumped);
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
    // Wording mirrors the contract's counters: a non-jump increments
    // `survivedSwats` ("it survived the swat" -- didn't even need to move).
    const verdict = result.jumped
      ? "IT JUMPED. It saw you coming and escaped."
      : "it ignored you. Survived without moving.";
    this.verdictEl.innerHTML = `
      <p class="verdict-line">${verdict}</p>
      <p class="verdict-meta">stimulus 0x${stimulus.toString(16).padStart(3, "0")} &middot; jump_left=${result.jumpLeft} &middot; jump_right=${result.jumpRight} &middot; ${mode}</p>
    `;
  }

  // --- One-click on-chain swat (injected EIP-1193 wallet) ----------------

  /** Generic JSON-RPC call against OUR public read endpoints (config.js's
   * rpcUrls, same fallback pattern as _evalOnChain) -- receipt polling goes
   * through these, NOT through the wallet's provider, so verdict rendering
   * never depends on trusting the wallet's view of the chain. */
  async _rpcCall(method, params) {
    const urls = CONFIG.rpcUrls;
    let lastErr;
    for (const url of urls) {
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (json.error) throw new Error(json.error.message || "RPC error");
        return json.result;
      } catch (e) {
        lastErr = e;
      }
    }
    throw lastErr || new Error("all RPC endpoints failed");
  }

  /** Poll for the tx receipt every ~3s for up to ~90s. Returns the receipt
   * object, or null on timeout. */
  async _waitForReceipt(txHash) {
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const receipt = await this._rpcCall("eth_getTransactionReceipt", [txHash]);
        if (receipt) return receipt;
      } catch {
        // transient RPC failure -- keep polling until the time budget runs out
      }
    }
    return null;
  }

  /** BscScan link for a tx hash -- href is only set when the hash actually
   * looks like one (the value came from the wallet, treat as untrusted). */
  _txLink(txHash) {
    const a = document.createElement("a");
    a.textContent = "view on BscScan";
    a.target = "_blank";
    a.rel = "noopener";
    if (/^0x[0-9a-fA-F]{64}$/.test(txHash)) {
      a.href = `https://bscscan.com/tx/${txHash}`;
    }
    return a;
  }

  _setOneClickStatus(el, text, txHash) {
    // Wallet/RPC strings are untrusted -- textContent only (existing rule).
    el.textContent = text;
    if (txHash) {
      el.appendChild(document.createTextNode(" -- "));
      el.appendChild(this._txLink(txHash));
    }
  }

  /** Extract `jumped` from the receipt's Swatted log. Per DEPLOY.md section
   * 7 (and abi.js's own warning): topic0 alone is never proof -- the log
   * must ALSO come from our contract address. Event layout:
   * Swatted(address indexed swatter, uint16 stimulus, bool jumped) --
   * swatter is topics[1]; stimulus and jumped are data words 0 and 1.
   * Returns true/false, or null if no matching log exists. */
  _decodeSwattedJumped(receipt) {
    const ours = CONFIG.contractAddress.toLowerCase();
    for (const log of receipt.logs || []) {
      if (!log || typeof log.address !== "string") continue;
      if (log.address.toLowerCase() !== ours) continue;
      if (!log.topics || log.topics[0] !== SWATTED_TOPIC0) continue;
      const data = (log.data || "").startsWith("0x") ? log.data.slice(2) : log.data || "";
      const jumpedWord = data.slice(64, 128);
      if (jumpedWord.length !== 64) return null;
      return BigInt("0x" + jumpedWord) === 1n;
    }
    return null;
  }

  async _oneClickSwat(btn, status) {
    const eth = window.ethereum;
    if (!eth) return;
    const stimulus = packStimulusBits(this.netlist, this.bits);
    if (stimulus === 0) {
      this._setOneClickStatus(
        status,
        'You swung at nothing (stimulus 0x000). Check some inputs above or hit a preset like "full loom" first.'
      );
      return;
    }
    btn.disabled = true;
    try {
      this._setOneClickStatus(status, "Requesting wallet account...");
      const accounts = await eth.request({ method: "eth_requestAccounts" });
      const from = Array.isArray(accounts) ? accounts[0] : null;
      if (!from) throw new Error("wallet returned no account");

      const chainIdHex = await eth.request({ method: "eth_chainId" });
      if (parseInt(chainIdHex, 16) !== CONFIG.chainId) {
        this._setOneClickStatus(status, "Switching wallet to BNB Smart Chain...");
        try {
          await eth.request({
            method: "wallet_switchEthereumChain",
            params: [{ chainId: "0x38" }],
          });
        } catch (switchErr) {
          // 4902 = chain not added to this wallet yet
          if (switchErr && switchErr.code === 4902) {
            await eth.request({
              method: "wallet_addEthereumChain",
              params: [
                {
                  chainId: "0x38",
                  chainName: "BNB Smart Chain",
                  nativeCurrency: { name: "BNB", symbol: "BNB", decimals: 18 },
                  rpcUrls: ["https://bsc-dataseed.bnbchain.org"],
                  blockExplorerUrls: ["https://bscscan.com"],
                },
              ],
            });
          } else {
            throw switchErr;
          }
        }
      }

      const data = encodeUint16Call(SELECTORS["swatTx(uint16)"], stimulus);
      this._setOneClickStatus(
        status,
        "Confirm in your wallet. One swatTx(uint16) call -- the only cost is gas; the contract cannot receive value."
      );
      const txHash = await eth.request({
        method: "eth_sendTransaction",
        params: [{ from, to: CONFIG.contractAddress, data }],
      });

      this._setOneClickStatus(status, "Transaction sent. Waiting for it to be mined...", txHash);
      const receipt = await this._waitForReceipt(txHash);
      if (!receipt) {
        this._setOneClickStatus(status, "Still pending after 90s -- check the status yourself:", txHash);
        return;
      }
      if (receipt.status && BigInt(receipt.status) === 0n) {
        this._setOneClickStatus(status, "Transaction reverted on-chain:", txHash);
        return;
      }
      const jumped = this._decodeSwattedJumped(receipt);
      if (jumped === null) {
        this._setOneClickStatus(
          status,
          "Mined, but no Swatted event from this contract was found in the receipt:",
          txHash
        );
        return;
      }

      // The Swatted event only carries the aggregate `jumped` bit. For the
      // circuit-flow animation's per-side detail, evaluate the identical
      // local netlist (parity vs the contract is exhaustively proven);
      // the VERDICT text itself is driven by the on-chain event alone.
      let sides = { jumped, jumpLeft: jumped, jumpRight: jumped };
      try {
        const local = evaluateStimulus(this.netlist, stimulus);
        if (local.jumped === jumped) sides = local;
      } catch {
        // fall back to the aggregate-only animation
      }
      if (this.circuitViewer) this.circuitViewer.pulseEvaluation(sides, true);
      if (this.fly) {
        this.fly.pulse(jumped);
        if (jumped) this.fly.jump();
        else this.fly.twitch(0.5);
      }
      this.verdictEl.textContent = "";
      const line = document.createElement("p");
      line.className = "verdict-line";
      line.textContent = jumped
        ? "IT JUMPED. It saw you coming and escaped."
        : "it ignored you. Survived without moving.";
      const meta = document.createElement("p");
      meta.className = "verdict-meta";
      meta.textContent = `stimulus 0x${stimulus.toString(16).padStart(3, "0")} · on-chain (transaction) · `;
      meta.appendChild(this._txLink(txHash));
      this.verdictEl.appendChild(line);
      this.verdictEl.appendChild(meta);
      this._setOneClickStatus(status, "Mined. Your swat is now part of the public counters.", txHash);
    } catch (e) {
      if (e && e.code === 4001) {
        this._setOneClickStatus(status, "Cancelled in wallet -- nothing was sent.");
      } else {
        this._setOneClickStatus(status, `Failed: ${String((e && e.message) || e)}`);
      }
    } finally {
      btn.disabled = false;
    }
  }
}
