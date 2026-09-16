// Circuit viewer: renders the 661-gate netlist as 16 neuron-grouped blocks
// (12 visual + GF L/R + TTMn L/R, per circuit/SCHEMA.md's neuron_gate_map)
// with real gate counts computed from the actual netlist graph (not
// hand-estimated), plus a simplified two-hemisphere signal-flow diagram that
// both the live layer and the swat UI pulse during evaluation.
//
// "Gate count" per neuron is a real, computed closure over the netlist's own
// dependency graph (see site/js/netlist.js forwardClosure/backwardClosure):
// a visual-input neuron's count is every gate downstream of its spike pin;
// a GF/TTMn neuron's count is every gate its own comparator/latch depends on
// upstream. These overlap between neurons on the same hemisphere (the adder
// tree is shared) -- that's an honest property of the real circuit, not a
// display bug.

import { forwardClosure, backwardClosure, buildForwardMap } from "./netlist.js";

const GROUP_ORDER = ["LC4-L", "LPLC2-L", "LC4-R", "LPLC2-R", "GF-L", "GF-R", "TTMn-L", "TTMn-R"];

function neuronGroupKey(n) {
  if (n.role === "visual_input") return `${n.type}-${n.side}`;
  if (n.role === "gf") return `GF-${n.side}`;
  if (n.role === "jump_motor") return `TTMn-${n.side}`;
  return `${n.type}-${n.side}`;
}

export class CircuitViewer {
  constructor(container, netlist) {
    this.container = container;
    this.netlist = netlist;
    this.forwardMap = buildForwardMap(netlist);
    this.selected = null;
    this.onSelect = null;
    this._closureCache = new Map();
    this._buildGroups();
    this._render();
  }

  _buildGroups() {
    this.groups = new Map();
    for (const n of this.netlist.neuron_gate_map) {
      const key = neuronGroupKey(n);
      if (!this.groups.has(key)) this.groups.set(key, []);
      this.groups.get(key).push(n);
    }
  }

  _highlightSetFor(neuron) {
    const cacheKey = neuron.neuron_id;
    if (this._closureCache.has(cacheKey)) return this._closureCache.get(cacheKey);
    const set =
      neuron.role === "visual_input"
        ? forwardClosure(this.netlist, neuron.signal, this.forwardMap)
        : backwardClosure(this.netlist, neuron.signal);
    this._closureCache.set(cacheKey, set);
    return set;
  }

  _render() {
    this.container.innerHTML = "";

    const wrap = document.createElement("div");
    wrap.className = "circuit-groups";
    for (const key of GROUP_ORDER) {
      const neurons = this.groups.get(key);
      if (!neurons) continue;
      const section = document.createElement("div");
      section.className = "circuit-group";
      const title = document.createElement("h4");
      title.textContent = key;
      section.appendChild(title);
      const cardsWrap = document.createElement("div");
      cardsWrap.className = "circuit-cards";
      for (const n of neurons) {
        const gateCount = this._highlightSetFor(n).size;
        const card = document.createElement("button");
        card.type = "button";
        card.className = "circuit-card";
        card.setAttribute("data-neuron-id", String(n.neuron_id));
        const extra =
          n.role === "visual_input"
            ? `<div class="circuit-card-gates">${gateCount} downstream gates</div>`
            : `<div class="circuit-card-gates">${gateCount} upstream gates &middot; threshold ${n.threshold}/${n.max_possible_sum}</div>`;
        card.innerHTML = `
          <div class="circuit-card-id">body #${n.neuron_id}</div>
          <div class="circuit-card-type">${n.type} &middot; ${n.side}</div>
          ${extra}
        `;
        card.addEventListener("click", () => this._select(n, card));
        cardsWrap.appendChild(card);
      }
      section.appendChild(cardsWrap);
      wrap.appendChild(section);
    }
    this.container.appendChild(wrap);

    const nandCount = this.netlist.gates.filter((g) => g.type === "NAND").length;
    const latchCount = this.netlist.gates.filter((g) => g.type === "LATCH").length;
    const totalLine = document.createElement("p");
    totalLine.className = "circuit-total";
    totalLine.textContent = `${this.netlist.gates.length} gates total (${nandCount} NAND + ${latchCount} LATCH). Click a neuron to see how many gates its signal touches.`;
    this.container.appendChild(totalLine);

    this._renderFlowDiagram();
  }

  _renderFlowDiagram() {
    const flow = document.createElement("div");
    flow.className = "circuit-flow";
    flow.innerHTML = `
      <div class="flow-row" data-side="L">
        <div class="flow-box" data-stage="visual">visual input L</div>
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-box" data-stage="gf">GF (DNp01) L</div>
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-box" data-stage="latch">jump_left LATCH</div>
      </div>
      <div class="flow-row" data-side="R">
        <div class="flow-box" data-stage="visual">visual input R</div>
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-box" data-stage="gf">GF (DNp01) R</div>
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-box" data-stage="latch">jump_right LATCH</div>
      </div>
      <div class="flow-merge">
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-box flow-box-out" data-stage="jump">jump (OR)</div>
      </div>
    `;
    this.container.appendChild(flow);
    this._flowEl = flow;
  }

  _select(neuron, card) {
    for (const el of this.container.querySelectorAll(".circuit-card.selected")) {
      el.classList.remove("selected");
    }
    card.classList.add("selected");
    this.selected = neuron;
    const gateSet = this._highlightSetFor(neuron);
    this._highlightFlowForNeuron(neuron);
    if (this.onSelect) this.onSelect(neuron, gateSet);
  }

  /** Visually highlight the signal-flow diagram boxes this neuron's gates
   * belong to (its hemisphere's stages), as the closest honest stand-in for
   * "highlight the 219+ individual gates" at this zoom level -- the exact
   * gate SET is what the neuron card's count + onSelect callback expose. */
  _highlightFlowForNeuron(neuron) {
    if (!this._flowEl) return;
    for (const box of this._flowEl.querySelectorAll(".flow-box")) box.classList.remove("selected-neuron");
    const side = neuron.side;
    const row = this._flowEl.querySelector(`.flow-row[data-side="${side}"]`);
    if (row) {
      for (const box of row.querySelectorAll(".flow-box")) box.classList.add("selected-neuron");
    }
    if (neuron.role !== "visual_input") {
      const jumpBox = this._flowEl.querySelector('[data-stage="jump"]');
      if (jumpBox) jumpBox.classList.add("selected-neuron");
    }
  }

  /** Pulse the signal-flow diagram to reflect one evaluation result, shared
   * by both the live layer and the swat UI (spec: "signal flow animates
   * during any evaluation"). `result` is evaluateStimulus()'s return value;
   * `spikeActive` (optional bool) marks whether any visual input fired at
   * all, for the "visual" stage boxes. */
  pulseEvaluation(result, spikeActive) {
    if (!this._flowEl) return;
    const setActive = (side, stage, active) => {
      const row = this._flowEl.querySelector(`.flow-row[data-side="${side}"]`);
      if (!row) return;
      const box = row.querySelector(`.flow-box[data-stage="${stage}"]`);
      if (!box) return;
      box.classList.remove("pulse");
      // Force reflow so re-triggering the animation on repeated identical
      // results still restarts it.
      void box.offsetWidth;
      if (active) box.classList.add("pulse");
    };
    setActive("L", "visual", !!spikeActive);
    setActive("R", "visual", !!spikeActive);
    setActive("L", "gf", result.jumpLeft || !!spikeActive);
    setActive("R", "gf", result.jumpRight || !!spikeActive);
    setActive("L", "latch", result.jumpLeft);
    setActive("R", "latch", result.jumpRight);
    const jumpBox = this._flowEl.querySelector('[data-stage="jump"]');
    if (jumpBox) {
      jumpBox.classList.remove("pulse");
      void jumpBox.offsetWidth;
      if (result.jumped) jumpBox.classList.add("pulse");
    }
  }
}
