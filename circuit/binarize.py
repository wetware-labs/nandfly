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

   Only 12 of the 311 LC4/LPLC2 neurons available in MaleCNS v1.0 for this
   pathway are kept (top-3 per population per side; 3.9% -- see
   circuit/extract.py and circuit/DERIVATION.md section 4). This is stated
   plainly here, in `params["visual_inputs_kept_fraction"]` below, and at
   the top of reports/equivalence.md, so nobody has to go hunting for it.

2. Threshold rule -- REVISED after the first review round. Two different
   rules are used, and which one applies is determined structurally by how
   many inputs a unit has (not hand-picked per unit):

   - Multi-input units (GF/DNp01 in this subgraph, 6 inputs each): fires
     when the weighted input sum is >= `(largest single input's quantized
     magnitude) + 1`. This is an a-priori "coincidence detector" rule,
     chosen ON PRINCIPLE from the biology (GF integrates converging looming
     channels; the published circuit's whole point is that no single LC4
     or LPLC2 afferent should be able to command a jump by itself) -- NOT
     because it scores best on the equivalence test set. See
     reports/equivalence.md for the full threshold-fraction sweep we ran
     before choosing this rule, including fractions that score higher, and
     an explicit statement of why we did not pick the best-scoring one.
   - Single-input units (TTMn in this subgraph): kept at the original rule,
     fires when its weighted input sum is >= `ceil(0.5 * max_possible_sum)`.
     The coincidence rule (largest + 1) is NOT applied here on purpose: for
     a one-input unit, max_possible_sum IS that one input's magnitude, so
     "largest + 1" would always exceed the unit's own maximum achievable
     sum, making it permanently unfirable. The 0.5 rule instead always
     reduces to "fires iff the input spikes" for a lone positive-sign input
     (see point 6, the identity-passthrough optimization this enables).

   We revised this rule after the first equivalence run used a single 0.5
   rule everywhere and scored 80.6% (exhaustive: 76.7%, see
   reports/equivalence.md); the coincidence rule was adopted afterward on
   principle, and the resulting equivalence number is reported honestly
   either way it lands (see reports/equivalence.md's headline).

3. Gate compilation: signed weighted sums are built as an unweighted-input,
   constant-weight adder tree (circuit/gates.py's `mask` + `add_many`), and
   the threshold comparison is a magnitude comparator (`compare_ge`) against
   a constant. All logic other than the two output LATCHes (one per
   hemisphere, holding the "jump commanded" motor decision) compiles to
   NAND only. See circuit/gates.py's module docstring for the exact NAND
   decompositions (4-NAND XOR, 9-NAND full adder, etc).

4. Sign handling: LC4, LPLC2, and DNp01 (every neuron in this subgraph
   EXCEPT TTMn) are 100% cholinergic (consensus_nt=acetylcholine, sign +1 --
   see circuit/data/subgraph.json), so every edge actually compiled into
   this netlist is excitatory. TTMn's own transmitter is glutamate (sign
   -1 under our inherited sign map, see circuit/extract.py's
   TRANSMITTER_NEGATIVE), but TTMn has no OUTGOING edges in this subgraph
   (it is a leaf/output neuron), so that sign is recorded in
   subgraph.json for completeness but never used to flip an edge weight.
   **Known limitation, disclosed rather than hidden**: the transmitter ->
   sign map we reused from FlyMarket (mirroring DOOMFLY's own proxy) maps
   glutamate to inhibitory (-1) uniformly. That is a reasonable population
   average in the insect CNS generally, but it is WRONG specifically for
   motor neurons at the Drosophila neuromuscular junction, where glutamate
   is the excitatory transmitter. It is harmless in this exact netlist
   (TTMn's sign is never read, since it has no outgoing edges here), but we
   are flagging it now rather than waiting for someone else to find it --
   see DERIVATION.md section 3.
   The `sign` field is still carried through end-to-end (and would flip a
   synapse's contribution by two's-complement negation before addition) for
   generality/reproducibility on a future extension of this circuit that
   does include inhibitory input; `negate_bits()` implements that path and
   is unit-tested even though it is unused by the current subgraph.

5. LATCH usage: exactly one LATCH per hemisphere, holding the jump-command
   decision. Reset protocol (see circuit/SCHEMA.md and circuit/equivalence.py):
   the shared `reset` input pin is driven to 1 (with all spike pins 0) to
   clear both latches to 0 before each stimulus pattern is evaluated, then
   driven to 0 while the pattern's spike pins are asserted.

6. Identity-passthrough optimization for single-input threshold units
   (added after the first review round). A single positive-sign input's
   threshold unit, under the 0.5-of-max rule in point 2, always reduces to
   "fires iff the input fires" (see the algebraic argument in point 2) --
   so no mask/adder/comparator gates are built for it at all; its "fires"
   signal is just wired directly to its one input (0 extra gates, instead
   of the ~60 gates/unit a generic mask+adder+comparator build would cost).
   A lone negative-sign input's unit is wired to the constant-0 pin (a
   single inhibitory input can never push a sum that starts at 0 above a
   positive threshold). This is purely a gate-count optimization -- see
   DERIVATION.md section 6 for the before/after gate count and the
   all-4096-patterns equivalence test proving it changes no jump output.

7. Reset-dominant LATCH conditioning (added after the first review round).
   Each hemisphere's `set_n` signal is computed as
   `NAND(fires_signal, reset_n)` rather than the simpler `NOT(fires_signal)`
   -- by De Morgan, `NAND(fires_signal, reset_n) = NOT(fires_signal) OR
   reset_pin`, which is forced to 1 (inactive) whenever `reset_pin=1`,
   REGARDLESS of `fires_signal`. Since `reset_n` is already needed as the
   LATCH's own second input, this costs no additional gate: the
   `set_n`/`reset_n` pair can now never both be 0 at the same tick by
   construction (not merely by the calling protocol in point 5), making
   reset dominance a structural property of the wiring, not just an
   evaluation convention (see gates.py's LATCH docstring, and
   test_binarize.py::test_latch_set_is_structurally_gated_by_reset).
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

VISUAL_INPUTS_AVAILABLE = 311   # 126 LC4 + 185 LPLC2, see circuit/DERIVATION.md section 2
VISUAL_INPUTS_KEPT = 12         # top-3 LC4 + top-3 LPLC2, per side (2 sides x 2 pops x 3)
VISUAL_INPUTS_KEPT_FRACTION = (
    f"{VISUAL_INPUTS_KEPT} of {VISUAL_INPUTS_AVAILABLE} available LC4/LPLC2 neurons "
    f"({100.0 * VISUAL_INPUTS_KEPT / VISUAL_INPUTS_AVAILABLE:.1f}%)"
)


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


def coincidence_threshold(inputs: list, max_possible_sum: int) -> int:
    """The default multi-input threshold rule (module docstring, point 2):
    one more than the single largest positive-sign input's quantized
    magnitude -- an a-priori coincidence-detector rule, not tuned against
    the equivalence test set."""
    largest_positive = max((magnitude for _pin, magnitude, sign in inputs if sign > 0), default=0)
    return largest_positive + 1


def _build_threshold_unit(builder: GateBuilder, inputs: list, bit_width: int,
                           multi_input_threshold_fn=coincidence_threshold,
                           optimize_single_input: bool = True):
    """inputs: list of (spike_pin_name, quantized_magnitude:int, sign:int).
    Returns (fires_signal, threshold_value, max_possible_sum, sum_bits).

    `multi_input_threshold_fn(inputs, max_possible_sum) -> int` selects the
    threshold for units with 2+ inputs; it defaults to `coincidence_threshold`
    but circuit/equivalence.py's threshold-fraction sweep overrides it to
    explore alternatives (see module docstring, point 2). It has no effect
    on single-input units, which always use the 0.5-of-max rule (see below).

    `optimize_single_input` controls the point-6 identity-passthrough
    optimization for single-input units; it defaults to True (the
    production behavior) and is only ever set False by
    test_binarize.py::test_identity_optimization_never_changes_jump_output,
    to build an intentionally-unoptimized comparison netlist."""
    if len(inputs) == 1:
        pin, magnitude, sign = inputs[0]
        max_possible_sum = magnitude if sign > 0 else 0
        threshold_value = math.ceil(0.5 * max_possible_sum) if max_possible_sum else 0
        if optimize_single_input:
            # Point 6: for a lone positive-sign input, "sum >= ceil(0.5*sum)"
            # is true exactly when the input fires (sum is either 0 or
            # `magnitude`, and ceil(0.5*magnitude) <= magnitude for any
            # magnitude >= 1) -- so wire straight through, 0 extra gates.
            # For a lone negative-sign input, the sum can never be positive,
            # so it can never reach a positive threshold -- wire to 0.
            fires = pin if sign > 0 else builder.const(0)
            return fires, threshold_value, max_possible_sum, [pin]
        # Unoptimized path (test-only): build the generic mask+adder+comparator
        # machinery even for one input, to prove the optimization above is a
        # pure gate-count change with no behavioral difference.
        weight_bits = builder.const_bits(magnitude, bit_width)
        masked = builder.mask(pin, weight_bits)
        if sign < 0:
            masked = negate_bits(builder, masked, bit_width)
        threshold_bits = builder.const_bits(threshold_value, len(masked))
        fires = builder.compare_ge(masked, threshold_bits)
        return fires, threshold_value, max_possible_sum, masked

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
    threshold_value = multi_input_threshold_fn(inputs, max_possible_sum)
    threshold_bits = builder.const_bits(threshold_value, len(total))
    fires = builder.compare_ge(total, threshold_bits)
    return fires, threshold_value, max_possible_sum, total


def build_full_netlist(subgraph: dict, bit_width: int = BIT_WIDTH, scale: int = SCALE,
                        multi_input_threshold_fn=coincidence_threshold,
                        optimize_single_input: bool = True) -> dict:
    b = GateBuilder(prefix="g")
    reset_pin = b.input_pin("reset")

    neurons_by_id = {n["id"]: n for n in subgraph["neurons"]}
    gf_by_side = {}
    ttmn_by_side = {}
    for n in subgraph["neurons"]:
        if n["role"] == "gf":
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
            b, gf_inputs, bit_width, multi_input_threshold_fn=multi_input_threshold_fn)
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
            b, [(gf_fires, ttmn_magnitude, ttmn_sign)], bit_width,
            optimize_single_input=optimize_single_input)

        # Reset-dominant conditioning (module docstring, point 7): set_n is
        # gated through NOT(reset) via a single De-Morgan-collapsed NAND,
        # rather than a plain NOT(ttmn_fires), so reset structurally
        # overrides set at this latch (reset_n is needed anyway as the
        # LATCH's own second input, so this costs no extra gate).
        reset_n = b.not_(reset_pin)
        set_n = b.nand(ttmn_fires, reset_n)
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
            "threshold_rule_multi_input": "(largest single positive input magnitude) + 1 "
                                           "(coincidence-detector rule, chosen on principle "
                                           "-- see reports/equivalence.md's threshold sweep)",
            "threshold_rule_single_input": "ceil(0.5 * max_possible_sum) "
                                            "(reduces to identity pass-through, see "
                                            "DERIVATION.md section 6)",
            "visual_inputs_kept": VISUAL_INPUTS_KEPT,
            "visual_inputs_available": VISUAL_INPUTS_AVAILABLE,
            "visual_inputs_kept_fraction": VISUAL_INPUTS_KEPT_FRACTION,
        },
    }


# --------------------------------------------------------------------- seed

SEED_HEMISPHERE = "L"
SEED_DESCRIPTION = (
    "A verbatim 2-NAND + 1-LATCH fragment of full.json: the final "
    "TTMn-to-jump output stage for the LEFT hemisphere. In full.json this is "
    "the reset-dominant set/reset conditioning (one NAND computing "
    "NOT(reset_pin), and one NAND computing NAND(ttmn_fires, that NOT(reset)) "
    "-- see build_full_netlist()'s point-7 docstring) feeding the "
    "'jump_left' LATCH that holds the fly's jump-commanded state. It is a "
    "real sub-piece of the real circuit -- the gate ids, gate types, and "
    "wiring below are copied unchanged from full.json (see "
    "test_seed_fragment.py), just with the two external signals this stage "
    "depends on (the left hemisphere's jump-firing decision, and the shared "
    "reset pin) re-exposed as this fragment's own named input pins instead "
    "of being computed by the (here, omitted) upstream adder-tree/comparator "
    "logic. This fragment IS the output stage; it carries no synaptic "
    "weights or thresholds of its own -- see circuit/SCHEMA.md for exactly "
    "how its pin names trace back to full.json."
)


def extract_seed_fragment(full_netlist: dict, hemisphere: str = SEED_HEMISPHERE) -> dict:
    latch_id = full_netlist["output_pins"]["jump_left" if hemisphere == "L" else "jump_right"]
    latch_gate = next(g for g in full_netlist["gates"] if g["id"] == latch_id)
    set_n_id, reset_n_id = latch_gate["inputs"]
    gate_by_id = {g["id"]: g for g in full_netlist["gates"]}
    set_n_gate = gate_by_id[set_n_id]
    reset_n_gate = gate_by_id[reset_n_id]
    assert set_n_gate["type"] == "NAND" and reset_n_gate["type"] == "NAND"

    # set_n_gate = NAND(upstream_fires_signal, reset_n_gate['id']) -- see
    # build_full_netlist()'s reset-dominant conditioning. Its second input
    # is reset_n_gate's own id (kept internal to this fragment, since
    # reset_n_gate is copied in below too); its other input is the upstream
    # jump-firing signal, which this fragment does not compute itself, so it
    # is re-exposed as an external input pin.
    upstream_fires_signal = next(i for i in set_n_gate["inputs"] if i != reset_n_gate["id"])
    reset_pin_name = reset_n_gate["inputs"][0]

    # Verbatim copies (same ids, same types, same inputs) of the 3 gates,
    # in dependency order: reset_n_gate must precede set_n_gate here since
    # set_n_gate's own inputs reference reset_n_gate's id (see
    # build_full_netlist()'s point-7 reset-dominant conditioning) --
    # evaluate_netlist() requires gates in a valid topological order.
    gates = [dict(reset_n_gate), dict(set_n_gate), dict(latch_gate)]

    return {
        "schema_version": 1,
        "description": SEED_DESCRIPTION,
        "source": {"netlist": "full.json", "hemisphere": hemisphere,
                   "gate_ids": [reset_n_gate["id"], set_n_gate["id"], latch_gate["id"]]},
        "gates": gates,
        "input_pins": [upstream_fires_signal, reset_pin_name],
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
