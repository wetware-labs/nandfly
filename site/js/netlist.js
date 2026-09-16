// NANDFLY client-side netlist evaluator.
//
// This is a line-for-line port of circuit/gates.py::evaluate_netlist plus the
// two-tick evaluation protocol documented in circuit/SCHEMA.md ("Evaluation
// protocol") and implemented identically by contract/gen_parity_fixture.py
// (the Python oracle) and NandFly.sol's `_evaluate()` (the on-chain oracle).
// All three (this file, the Python reference, and the Solidity contract) MUST
// agree on every one of the 4096 possible 12-bit stimulus patterns -- that is
// exactly what tests/site-netlist-parity.test.mjs checks, against
// contract/fixtures/parity_4096.json (itself generated straight from
// circuit/gates.py, not reimplemented).
//
// This evaluator powers BOTH the live layer (site/js/live-layer.js, fed by
// real BSC blocks) and the pre-deploy swat demo (site/js/swat.js). It never
// makes a network request itself -- it is pure data-in, data-out.

export const NAND = "NAND";
export const LATCH = "LATCH";

/**
 * Evaluate every gate in netlist.gates once, in list order (a valid
 * topological order by construction -- see circuit/gates.py's GateBuilder
 * docstring). Returns a Map-like plain object {signalId: 0|1} covering every
 * input pin and every gate output, plus a `_latch_state` sub-object of
 * {latchId: 0|1} for the caller to feed into the next tick.
 *
 * @param {object} netlist - parsed full.json (or seed.json)
 * @param {object} inputValues - {pinName: 0|1}; any input pin not present
 *   here MUST be `const_0`/`const_1` (auto-filled) or this throws, exactly
 *   like circuit/gates.py's evaluate_netlist.
 * @param {object} [prevState] - {latchId: 0|1} previous-tick LATCH outputs
 *   (defaults to 0 for any LATCH not present, same as Python's prev_state).
 */
export function evaluateNetlist(netlist, inputValues, prevState) {
  prevState = prevState || {};
  const values = Object.assign({}, inputValues);

  for (const pin of netlist.input_pins || []) {
    if (!(pin in values)) {
      if (pin === "const_0") {
        values[pin] = 0;
      } else if (pin === "const_1") {
        values[pin] = 1;
      } else {
        throw new Error(`missing value for input pin ${JSON.stringify(pin)}`);
      }
    }
  }

  const latchState = {};
  for (const gate of netlist.gates) {
    const { id, type, inputs } = gate;
    if (type === NAND) {
      const a = values[inputs[0]];
      const b = values[inputs[1]];
      if (a === undefined || b === undefined) {
        throw new Error(`gate ${id}: unresolved input (${inputs[0]}=${a}, ${inputs[1]}=${b})`);
      }
      values[id] = a && b ? 0 : 1;
    } else if (type === LATCH) {
      const setN = values[inputs[0]];
      const resetN = values[inputs[1]];
      const prevQ = prevState[id] ?? 0;
      let q;
      if (setN === 0 && resetN === 1) {
        q = 1;
      } else if (setN === 1 && resetN === 0) {
        q = 0;
      } else if (setN === 1 && resetN === 1) {
        q = prevQ;
      } else {
        // setN === 0 && resetN === 0 -- reset-dominant convention, see
        // circuit/SCHEMA.md's LATCH truth table.
        q = 0;
      }
      values[id] = q;
      latchState[id] = q;
    } else {
      throw new Error(`unknown gate type ${JSON.stringify(type)}`);
    }
  }
  values._latch_state = latchState;
  return values;
}

/** The ordered list of `spike_<body_id>` input pins, in the exact order used
 * everywhere else in the project (contract/gen_netlist_sol.py's stimulus bit
 * order, contract/gen_parity_fixture.py's fixture, NandFlyNetlist.sol's
 * spikeSignalIndices()): bit i of a 12-bit stimulus <-> the i-th spike_* pin
 * in full.json's own input_pins array order. */
export function spikePinOrder(netlist) {
  return netlist.input_pins.filter((p) => p.startsWith("spike_"));
}

/**
 * Run the documented two-tick protocol once (reset tick, then stimulus tick)
 * and return the jump/jumpLeft/jumpRight verdict, exactly mirroring
 * contract/gen_parity_fixture.py::eval_stimulus.
 *
 * @param {object} netlist
 * @param {number|object} stimulus - either a 12-bit integer (bit i = the i-th
 *   spike pin in spikePinOrder(netlist)) or an object {spike_<id>: 0|1} for
 *   direct per-neuron control (used by the swat UI's toggle builder).
 */
export function evaluateStimulus(netlist, stimulus) {
  const spikePins = spikePinOrder(netlist);
  const outputPins = netlist.output_pins;

  let spikeValues;
  if (typeof stimulus === "number") {
    spikeValues = {};
    spikePins.forEach((pin, i) => {
      spikeValues[pin] = (stimulus >> i) & 1;
    });
  } else {
    spikeValues = stimulus || {};
  }

  // Tick 1: reset tick -- clears both hemispheres' LATCHes to 0.
  const tick1Inputs = { reset: 1 };
  for (const pin of spikePins) tick1Inputs[pin] = 0;
  const tick1 = evaluateNetlist(netlist, tick1Inputs, null);

  // Tick 2: stimulus tick, fed tick 1's latch outputs as previous state.
  const tick2Inputs = { reset: 0 };
  for (const pin of spikePins) tick2Inputs[pin] = spikeValues[pin] ? 1 : 0;
  const tick2 = evaluateNetlist(netlist, tick2Inputs, tick1._latch_state);

  const jumpLeft = tick2[outputPins.jump_left] === 1;
  const jumpRight = tick2[outputPins.jump_right] === 1;
  const jumped = tick2[outputPins.jump] === 1;

  return { jumped, jumpLeft, jumpRight, signals: tick2 };
}

/** Pack a {spike_<id>: 0|1} object into the 12-bit integer stimulus bit
 * order, the inverse of evaluateStimulus's object-form input. */
export function packStimulusBits(netlist, spikeValues) {
  const spikePins = spikePinOrder(netlist);
  let stimulus = 0;
  spikePins.forEach((pin, i) => {
    if (spikeValues[pin]) stimulus |= 1 << i;
  });
  return stimulus;
}

/** Build a forward dependency map: signalId -> [gate ids that directly read
 * that signal as one of their 2 inputs]. Used by the circuit viewer to
 * highlight everything downstream of a visual-input neuron's spike pin. */
export function buildForwardMap(netlist) {
  const forward = new Map();
  for (const gate of netlist.gates) {
    for (const inp of gate.inputs) {
      if (!forward.has(inp)) forward.set(inp, []);
      forward.get(inp).push(gate.id);
    }
  }
  return forward;
}

/** BFS forward closure from a starting signal (pin or gate id): every gate
 * id transitively downstream of it. */
export function forwardClosure(netlist, startSignal, forwardMap) {
  forwardMap = forwardMap || buildForwardMap(netlist);
  const seen = new Set();
  const queue = [startSignal];
  while (queue.length) {
    const sig = queue.pop();
    const deps = forwardMap.get(sig) || [];
    for (const gid of deps) {
      if (!seen.has(gid)) {
        seen.add(gid);
        queue.push(gid);
      }
    }
  }
  return seen;
}

/** BFS backward closure from a starting gate id: every gate id it transitively
 * depends on (its own computation), used to highlight a GF/motor neuron's
 * upstream adder tree. */
export function backwardClosure(netlist, startGateId) {
  const gateById = new Map(netlist.gates.map((g) => [g.id, g]));
  const seen = new Set();
  const queue = [startGateId];
  while (queue.length) {
    const gid = queue.pop();
    const gate = gateById.get(gid);
    if (!gate) continue; // reached a leaf input pin
    if (seen.has(gid)) continue;
    seen.add(gid);
    for (const inp of gate.inputs) {
      if (gateById.has(inp) && !seen.has(inp)) queue.push(inp);
    }
  }
  return seen;
}
