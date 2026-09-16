"""Binarize the GF core subgraph (circuit/data/subgraph.json) into a
NAND/LATCH gate-level netlist. See circuit/SCHEMA.md for the netlist JSON
schema and circuit/DERIVATION.md for the full write-up of every design
choice made here; this module's docstrings are the source of truth for
both.

--------------------------------------------------------------------------
Design choices (all ours, none copied from any third-party netlist)
--------------------------------------------------------------------------
1. Weight quantization: each kept synapse's raw weight (a synapse contact
   count, e.g. 20-86 in this subgraph) is quantized to a signed 4-bit
   magnitude in [1, 15] via `quantize_weight()`: `clamp(floor(w / SCALE),
   1, 15)` with SCALE=6. Floor division (not a per-population min/max
   rescale) is used so quantization is a fixed, reproducible function of the
   raw weight alone -- it does not depend on which other synapses happen to
   be in this particular subgraph. The floor is clamped to a minimum of 1
   (never 0) so that a synapse that was deliberately selected as a top-K
   input can never binarize away to "no connection" -- see DERIVATION.md.
   4 bits (max magnitude 15) was chosen because SCALE=6 keeps this
   subgraph's largest raw weight (86, LC4-L -> DNp01-L) just inside the
   4-bit range (86 // 6 = 14).

2. Threshold rule: every threshold unit (GF and TTMn alike) fires when its
   weighted input sum is >= 50% of the maximum sum it could ever receive
   (all of its selected inputs firing at once). This is a single, uniform,
   parameter-free rule applied identically everywhere -- not tuned per unit
   against the equivalence test set, which would risk overfitting the
   reported agreement number. See DERIVATION.md for the biological
   rationale (GF as a coincidence detector across converging looming
   channels) and for the honest observation that for TTMn (a single-input
   unit in this subgraph) the rule collapses to "fires iff GF fired".

3. Gate compilation: signed weighted sums are built as an unweighted-input,
   constant-weight adder tree (circuit/gates.py's `mask` + `add_many`), and
   the threshold comparison is a magnitude comparator (`compare_ge`) against
   a constant. All logic other than the two output LATCHes (one per
   hemisphere, holding the "jump commanded" motor decision) compiles to
   NAND only. See circuit/gates.py's module docstring for the exact NAND
   decompositions (4-NAND XOR, 9-NAND full adder, etc).

4. Sign handling: this specific subgraph turned out to be 100% cholinergic
   (every LC4/LPLC2/DNp01 neuron in it has consensus_nt=acetylcholine, sign
   +1 -- see circuit/data/subgraph.json), so no edge here is inhibitory.
   The `sign` field is still carried through end-to-end (and would flip a
   synapse's contribution by two's-complement negation before addition) for
   generality/reproducibility on a future extension of this circuit that
   does include inhibitory input; `negate_bits()` implements that path and
   is unit-tested even though it is unused by the current subgraph.

5. LATCH usage: exactly one LATCH per hemisphere, holding the jump-command
   decision. Reset protocol (see circuit/SCHEMA.md and circuit/equivalence.py):
   the shared `reset` input pin is driven to 1 (with all spike pins 0) to
   clear both latches to 0 before each stimulus pattern is evaluated, then
   driven to 0 while the pattern's spike pins are asserted. Under this
   protocol `set_n` and `reset_n` are never both 0 at the same latch at the
   same evaluation tick (see gates.py's LATCH docstring for what that case
   would mean).
"""
import argparse
import json
import math
from pathlib import Path

from circuit.gates import GateBuilder

DEFAULT_SUBGRAPH = Path("circuit/data/subgraph.json")
DEFAULT_FULL_OUT = Path("circuit/netlists/full.json")
DEFAULT_SEED_OUT = Path("circuit/netlists/seed.json")

BIT_WIDTH = 4
SCALE = 6
MAX_MAGNITUDE = (1 << BIT_WIDTH) - 1  # 15


def quantize_weight(raw_weight: int, scale: int = SCALE, bit_width: int = BIT_WIDTH) -> int:
    """Quantize a raw (positive) synapse weight to an integer magnitude in
    [1, 2**bit_width - 1]. Deterministic, reproducible, no per-population
    normalization (see module docstring, point 1)."""
    if raw_weight <= 0:
        raise ValueError(f"raw_weight must be positive, got {raw_weight}")
    max_mag = (1 << bit_width) - 1
    return max(1, min(max_mag, raw_weight // scale))


def negate_bits(builder: GateBuilder, bits, width: int):
    """Two's-complement negation of an LSB-first bit vector, widened to
    `width` bits first. Unused by the current (all-excitatory) subgraph, but
    unit-tested and available for a future inhibitory-input extension (see
    module docstring, point 4)."""
    zero = builder.const(0)
    widened = list(bits) + [zero] * (width - len(bits))
    inverted = [builder.not_(b) for b in widened]
    one = builder.const_bits(1, width)
    result = builder.ripple_add(inverted, one)
    return result[:width]


def _spike_pin(neuron_id: int) -> str:
    return f"spike_{neuron_id}"


def _build_threshold_unit(builder: GateBuilder, inputs: list, bit_width: int):
    """inputs: list of (spike_pin_name, quantized_magnitude:int, sign:int).
    Returns (fires_signal, threshold_value, max_possible_sum, sum_bits).
    Signed inputs are supported (see module docstring point 4) even though
    this subgraph's inputs are all sign=+1."""
    sum_width = bit_width + max(1, (len(inputs) - 1).bit_length())
    terms = []
    for pin, magnitude, sign in inputs:
        weight_bits = builder.const_bits(magnitude, bit_width)
        masked = builder.mask(pin, weight_bits)
        if sign < 0:
            masked = negate_bits(builder, masked, sum_width)
        terms.append(masked)
    total = builder.add_many(terms)
    max_possible_sum = sum(magnitude for _pin, magnitude, sign in inputs if sign > 0)
    threshold_value = math.ceil(0.5 * max_possible_sum)
    threshold_bits = builder.const_bits(threshold_value, len(total))
    fires = builder.compare_ge(total, threshold_bits)
    return fires, threshold_value, max_possible_sum, total


def build_full_netlist(subgraph: dict, bit_width: int = BIT_WIDTH, scale: int = SCALE) -> dict:
    b = GateBuilder(prefix="g")
    reset_pin = b.input_pin("reset")

    neurons_by_id = {n["id"]: n for n in subgraph["neurons"]}
    visual_by_side = {"L": [], "R": []}
    gf_by_side = {}
    ttmn_by_side = {}
    for n in subgraph["neurons"]:
        if n["role"] == "visual_input":
            visual_by_side[n["side"]].append(n)
        elif n["role"] == "gf":
            gf_by_side[n["side"]] = n
        elif n["role"] == "jump_motor":
            ttmn_by_side[n["side"]] = n

    edges_to = {}  # post_id -> list of (pre_id, weight, sign)
    for e in subgraph["edges"]:
        edges_to.setdefault(e["post"], []).append((e["pre"], e["weight"], e["sign"]))

    neuron_gate_map = []
    output_pins = {}

    for side in ("L", "R"):
        gf_neuron = gf_by_side[side]
        gf_inputs = []
        for pre_id, weight, sign in edges_to.get(gf_neuron["id"], []):
            pin = b.input_pin(_spike_pin(pre_id))
            magnitude = quantize_weight(weight, scale, bit_width)
            gf_inputs.append((pin, magnitude, sign))
            neuron_gate_map.append({
                "neuron_id": pre_id, "type": neurons_by_id[pre_id]["type"],
                "side": side, "role": "visual_input", "signal": pin,
                "signal_kind": "input_pin",
            })
        gf_fires, gf_threshold, gf_max_sum, gf_sum_bits = _build_threshold_unit(
            b, gf_inputs, bit_width)
        neuron_gate_map.append({
            "neuron_id": gf_neuron["id"], "type": "DNp01", "side": side, "role": "gf",
            "signal": gf_fires, "signal_kind": "gate_output",
            "threshold": gf_threshold, "max_possible_sum": gf_max_sum,
        })

        ttmn_neuron = ttmn_by_side[side]
        ttmn_edges = edges_to.get(ttmn_neuron["id"], [])
        assert len(ttmn_edges) == 1, "this subgraph has exactly one GF->TTMn edge per side"
        _pre_id, ttmn_weight, ttmn_sign = ttmn_edges[0]
        ttmn_magnitude = quantize_weight(ttmn_weight, scale, bit_width)
        ttmn_fires, ttmn_threshold, ttmn_max_sum, _ttmn_sum_bits = _build_threshold_unit(
            b, [(gf_fires, ttmn_magnitude, ttmn_sign)], bit_width)

        set_n = b.not_(ttmn_fires)
        reset_n = b.not_(reset_pin)
        latch_id = f"jump_{'left' if side == 'L' else 'right'}"
        b.latch(set_n, reset_n, label=latch_id)

        neuron_gate_map.append({
            "neuron_id": ttmn_neuron["id"], "type": "TTMn", "side": side, "role": "jump_motor",
            "signal": latch_id, "signal_kind": "gate_output",
            "threshold": ttmn_threshold, "max_possible_sum": ttmn_max_sum,
        })
        output_pins["jump_left" if side == "L" else "jump_right"] = latch_id

    jump = b.or_(output_pins["jump_left"], output_pins["jump_right"])
    output_pins["jump"] = jump

    return {
        "schema_version": 1,
        "gates": b.gates,
        "input_pins": b.input_pins,
        "output_pins": output_pins,
        "neuron_gate_map": neuron_gate_map,
        "params": {
            "bit_width": bit_width,
            "scale": scale,
            "max_magnitude": (1 << bit_width) - 1,
            "threshold_rule": "ceil(0.5 * max_possible_weighted_sum)",
        },
    }


# --------------------------------------------------------------------- seed

SEED_HEMISPHERE = "L"
SEED_DESCRIPTION = (
    "A verbatim 2-NAND + 1-LATCH fragment of full.json: the final "
    "TTMn-to-jump output stage for the LEFT hemisphere. In full.json this is "
    "the pair of NAND inverters that convert the left TTMn threshold unit's "
    "single-bit firing decision (and the shared reset pin) into active-low "
    "set/reset pulses, feeding the 'jump_left' LATCH that holds the fly's "
    "jump-commanded state. It is a real sub-piece of the real circuit -- the "
    "gate ids, gate types, and wiring below are copied unchanged from "
    "full.json (see test_seed_fragment.py), just with the two upstream "
    "signals (the left TTMn firing decision and the reset pin) re-exposed as "
    "this fragment's own named input pins instead of being computed by the "
    "(here, omitted) upstream adder-tree/comparator logic."
)


def extract_seed_fragment(full_netlist: dict, hemisphere: str = SEED_HEMISPHERE) -> dict:
    latch_id = full_netlist["output_pins"]["jump_left" if hemisphere == "L" else "jump_right"]
    latch_gate = next(g for g in full_netlist["gates"] if g["id"] == latch_id)
    set_n_id, reset_n_id = latch_gate["inputs"]
    gate_by_id = {g["id"]: g for g in full_netlist["gates"]}
    set_n_gate = gate_by_id[set_n_id]
    reset_n_gate = gate_by_id[reset_n_id]
    assert set_n_gate["type"] == "NAND" and reset_n_gate["type"] == "NAND"

    ttmn_fires_pin, _ = set_n_gate["inputs"][0], set_n_gate["inputs"][1]
    reset_pin_name = reset_n_gate["inputs"][0]

    # Verbatim copies (same ids, same types, same inputs) of the 3 gates.
    gates = [dict(set_n_gate), dict(reset_n_gate), dict(latch_gate)]

    return {
        "schema_version": 1,
        "description": SEED_DESCRIPTION,
        "source": {"netlist": "full.json", "hemisphere": hemisphere,
                   "gate_ids": [set_n_gate["id"], reset_n_gate["id"], latch_gate["id"]]},
        "gates": gates,
        "input_pins": [ttmn_fires_pin, reset_pin_name],
        "output_pins": {"jump_left" if hemisphere == "L" else "jump_right": latch_id},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subgraph", default=str(DEFAULT_SUBGRAPH))
    parser.add_argument("--full-out", default=str(DEFAULT_FULL_OUT))
    parser.add_argument("--seed-out", default=str(DEFAULT_SEED_OUT))
    args = parser.parse_args(argv)

    with open(args.subgraph, encoding="utf-8") as f:
        subgraph = json.load(f)

    full = build_full_netlist(subgraph)
    seed = extract_seed_fragment(full)

    for path, netlist in ((args.full_out, full), (args.seed_out, seed)):
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(netlist, f, indent=2)

    gate_counts = {}
    for g in full["gates"]:
        gate_counts[g["type"]] = gate_counts.get(g["type"], 0) + 1
    print(json.dumps({
        "full_gates_total": len(full["gates"]),
        "full_gate_counts": gate_counts,
        "seed_gates_total": len(seed["gates"]),
        "full_out": args.full_out,
        "seed_out": args.seed_out,
    }, indent=2))


if __name__ == "__main__":
    main()
