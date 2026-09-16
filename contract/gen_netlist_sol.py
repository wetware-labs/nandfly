"""Generate contract/NandFlyNetlist.sol from circuit/netlists/full.json.

This is the ONLY place that decides how the 661-gate NAND/LATCH netlist is
packed into bytes for on-chain storage. Regenerate after any change to
circuit/netlists/full.json by re-running this script from the repo root:

    python contract/gen_netlist_sol.py

Output is committed (contract/contracts/NandFlyNetlist.sol) so the Solidity project
builds without a Python dependency at compile time; this script is the
provenance record for how that file was produced.

--------------------------------------------------------------------------
Signal indexing scheme (must match NandFly.sol's _run() exactly)
--------------------------------------------------------------------------
Every signal in the netlist (every input pin AND every gate output) gets one
global index in range [0, NUM_SIGNALS):

  - indices [0, NUM_INPUT_PINS)   -> input_pins[i], in full.json's own
                                      input_pins array order (unchanged).
  - indices [NUM_INPUT_PINS, NUM_SIGNALS) -> gates[k]['id'], for gate k
                                      (0-indexed position in full.json's
                                      gates array), at index
                                      NUM_INPUT_PINS + k.

Gate list order in full.json is already a valid topological (dependency-
respecting) order (see circuit/SCHEMA.md), so every gate's inputs resolve to
signals with a strictly smaller index than the gate itself. NandFly.sol
relies on this: it evaluates gates 0..N-1 in order, writing each result into
a `sig[]` array slot the gate's own consumers can then read.

--------------------------------------------------------------------------
Stimulus bit order
--------------------------------------------------------------------------
The 12 stimulus bits of `swat(uint16 stimulus)` map to the netlist's
spike_<body_id> input pins in the order those pins first appear in
full.json's input_pins array (i.e. `[p for p in input_pins if
p.startswith("spike_")]`), bit 0 = first such pin. This script and
contract/gen_parity_fixture.py both derive this order programmatically from
the same full.json, so they cannot drift from each other.

--------------------------------------------------------------------------
Gate packing (4 bytes / gate, big-endian uint32)
--------------------------------------------------------------------------
Each gate is packed as one big-endian uint32 word:

    word = (type_bit << 30) | (left_index << 15) | right_index

  - type_bit: 0 = NAND, 1 = LATCH.
  - left_index / right_index: global signal indices (see above) of the
    gate's two inputs -- for NAND, (a, b); for LATCH, (set_n, reset_n), same
    positional order as full.json's `inputs` list.
  - Both indices fit in 15 bits (max signal index for the current 661-gate
    netlist is 675 << 32767), leaving bit 31 unused (always 0).

661 gates x 4 bytes = 2644 bytes, embedded as a single `bytes constant`
hex literal (stored in contract code, read via a cheap one-time memory copy
per call -- no SLOAD).

--------------------------------------------------------------------------
LATCH slot order
--------------------------------------------------------------------------
LATCH gates are NOT given a separate hardcoded index list. NandFly.sol
assigns latch "slots" by ENCOUNTER ORDER while walking the gate list
(0-indexed: the first LATCH gate seen is slot 0, the second is slot 1, ...).
Because gate order is fixed and identical between the reset-tick and the
stimulus-tick passes of a single swat() call, encounter order is
deterministic and reproducible without needing to hardcode which gate index
is a latch. This script only emits NUM_LATCHES (asserted equal to the
netlist's actual LATCH gate count) so the contract can size its slot array.
"""
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
NETLIST_PATH = REPO_ROOT / "circuit" / "netlists" / "full.json"
OUT_PATH = REPO_ROOT / "contract" / "contracts" / "NandFlyNetlist.sol"

NAND = "NAND"
LATCH = "LATCH"


def load_netlist():
    with open(NETLIST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_signal_index(netlist):
    input_pins = netlist["input_pins"]
    gates = netlist["gates"]
    index = {}
    for i, pin in enumerate(input_pins):
        index[pin] = i
    base = len(input_pins)
    for k, gate in enumerate(gates):
        index[gate["id"]] = base + k
    return index, len(input_pins), len(gates)


def pack_gates(netlist, signal_index, num_input_pins, num_signals):
    """Pack every gate to one big-endian uint32 word, with two assertions on
    every operand (added after Task 3's opcode-level audit, I2a):

    1. `operand < num_signals` -- the operand must resolve to a signal that
       actually exists in this netlist. In practice `signal_index[...]`
       already raises KeyError for a name that isn't a known pin/gate id, so
       this mostly guards against a future signal_index bug rather than a bad
       netlist; kept as an explicit, readable assertion rather than relying
       on that side effect.
    2. `operand < num_input_pins + k` -- TOPOLOGICAL: gate k's own global
       index is `num_input_pins + k`, so every one of its inputs must be a
       signal defined strictly BEFORE it (an input pin, or an earlier gate's
       output). A violation here means full.json's gate list is not actually
       in a valid evaluation order for this encoding -- NandFly.sol's
       evaluator loop assumes gate k's inputs are already computed by the
       time it reaches k, and would silently read an all-zero uninitialized
       `sig[]` slot instead of failing if this ever didn't hold.

    Both raise ValueError (loudly, at generation time -- not deploy time) on
    violation. This is generation-time defense in depth; NandFly.sol's
    constructor additionally re-checks operand ranges ON CHAIN at deploy
    time (see NandFlyValidation.validatePackedGates) so correctness does not
    rest solely on trusting this script was run correctly.
    """
    words = []
    num_latch = 0
    for k, gate in enumerate(netlist["gates"]):
        gtype = gate["type"]
        a, b = gate["inputs"]
        left = signal_index[a]
        right = signal_index[b]
        own_index = num_input_pins + k
        for name, idx in (("left", left), ("right", right)):
            if idx >= num_signals:
                raise ValueError(
                    f"gate {gate['id']!r} ({name} operand {idx}) >= num_signals ({num_signals})"
                )
            if idx >= own_index:
                raise ValueError(
                    f"gate {gate['id']!r} ({name} operand index {idx}) is not topologically "
                    f"before its own index ({own_index}) -- full.json's gate order is not a "
                    "valid evaluation order for this encoding"
                )
            if idx > 0x7FFF:
                raise ValueError(f"signal index does not fit in 15 bits: {gate}")
        type_bit = 1 if gtype == LATCH else 0
        if gtype == LATCH:
            num_latch += 1
        elif gtype != NAND:
            raise ValueError(f"unknown gate type {gtype!r} in gate {gate}")
        word = (type_bit << 30) | (left << 15) | right
        words.append(word)
    return words, num_latch


def to_hex_bytes(words):
    out = bytearray()
    for w in words:
        out += w.to_bytes(4, "big")
    return bytes(out)


def spike_pin_order(netlist):
    return [p for p in netlist["input_pins"] if p.startswith("spike_")]


def solidity_string_array(names):
    quoted = ", ".join(f'"{n}"' for n in names)
    return f"[{quoted}]"


def generate():
    netlist = load_netlist()
    signal_index, num_input_pins, num_gates = build_signal_index(netlist)
    num_signals = num_input_pins + num_gates
    words, num_latch = pack_gates(netlist, signal_index, num_input_pins, num_signals)
    packed = to_hex_bytes(words)
    spike_pins = spike_pin_order(netlist)

    if len(spike_pins) != 12:
        raise ValueError(
            f"expected exactly 12 spike_* input pins for a uint16 stimulus, found {len(spike_pins)}"
        )
    if num_latch != 2:
        raise ValueError(f"expected exactly 2 LATCH gates, found {num_latch}")

    output_pins = netlist["output_pins"]
    jump_left_idx = signal_index[output_pins["jump_left"]]
    jump_right_idx = signal_index[output_pins["jump_right"]]
    jump_idx = signal_index[output_pins["jump"]]

    reset_idx = signal_index["reset"]
    const0_idx = signal_index["const_0"]
    const1_idx = signal_index["const_1"]
    spike_indices = [signal_index[p] for p in spike_pins]

    hex_literal = packed.hex()

    lines = []
    lines.append("// SPDX-License-Identifier: MIT")
    lines.append("pragma solidity 0.8.24;")
    lines.append("")
    lines.append("// AUTO-GENERATED by contract/gen_netlist_sol.py from circuit/netlists/full.json.")
    lines.append("// DO NOT EDIT BY HAND -- re-run the generator instead. See that script's module")
    lines.append("// docstring for the full packing/indexing scheme this file assumes.")
    lines.append("//")
    lines.append(f"// Source netlist: circuit/netlists/full.json (schema_version {netlist.get('schema_version')})")
    lines.append(f"// Gates: {num_gates} total ({num_gates - num_latch} NAND + {num_latch} LATCH)")
    lines.append(f"// Input pins: {num_input_pins} (1 reset + {len(spike_pins)} spike_* + 2 const)")
    lines.append(f"// Total signals (input pins + gate outputs): {num_signals}")
    lines.append("")
    lines.append("library NandFlyNetlist {")
    lines.append(f"    uint256 internal constant NUM_GATES = {num_gates};")
    lines.append(f"    uint256 internal constant NUM_INPUT_PINS = {num_input_pins};")
    lines.append(f"    uint256 internal constant NUM_SIGNALS = {num_signals};")
    lines.append(f"    uint256 internal constant NUM_LATCHES = {num_latch};")
    lines.append("")
    lines.append("    // Global signal indices for the netlist's named leaves/outputs.")
    lines.append(f"    uint256 internal constant SIG_RESET = {reset_idx};")
    lines.append(f"    uint256 internal constant SIG_CONST_0 = {const0_idx};")
    lines.append(f"    uint256 internal constant SIG_CONST_1 = {const1_idx};")
    lines.append(f"    uint256 internal constant SIG_JUMP_LEFT = {jump_left_idx};")
    lines.append(f"    uint256 internal constant SIG_JUMP_RIGHT = {jump_right_idx};")
    lines.append(f"    uint256 internal constant SIG_JUMP = {jump_idx};")
    lines.append("")
    lines.append("    // Global signal index of stimulus bit i (bit 0 = LSB of the uint16 stimulus),")
    lines.append("    // in the order those spike_<body_id> pins first appear in full.json's")
    lines.append("    // input_pins array. Bit -> body ID, for provenance / a future circuit viewer:")
    for i, pin in enumerate(spike_pins):
        lines.append(f"    //   bit {i}: {pin}")
    array_items = ", ".join(
        f"uint256({i})" if idx == 0 else str(i) for idx, i in enumerate(spike_indices)
    )
    lines.append(f"    function spikeSignalIndices() internal pure returns (uint256[12] memory) {{")
    lines.append(f"        return [{array_items}];")
    lines.append("    }")
    lines.append("")
    lines.append("    // 661 gates x 4 bytes (big-endian uint32: [1 type bit | 15-bit left index |")
    lines.append("    // 15-bit right index]) = 2644 bytes. See gen_netlist_sol.py for the exact")
    lines.append("    // packing/decoding contract.")
    lines.append(f"    bytes internal constant PACKED_GATES = hex\"{hex_literal}\";")
    lines.append("}")
    lines.append("")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_PATH} ({len(packed)} bytes packed, {num_gates} gates, {num_signals} signals)")


if __name__ == "__main__":
    sys.exit(generate() or 0)
