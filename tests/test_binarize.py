"""Unit tests for circuit/binarize.py: weight quantization math, the
compiled threshold-unit/netlist builder, and the seed-fragment extractor."""
import json
from pathlib import Path

import pytest

from circuit.binarize import (
    BIT_WIDTH,
    SCALE,
    build_full_netlist,
    coincidence_threshold,
    extract_seed_fragment,
    negate_bits,
    quantize_weight,
)
from circuit.gates import GateBuilder, evaluate_netlist, to_int


def test_quantize_weight_known_cases():
    # raw // SCALE(=6), clamped to [1, 15]
    assert quantize_weight(86) == 14        # 86 // 6 = 14
    assert quantize_weight(70) == 11        # 70 // 6 = 11
    assert quantize_weight(20) == 3         # 20 // 6 = 3
    assert quantize_weight(6) == 1          # 6 // 6 = 1
    assert quantize_weight(1) == 1          # floors to 0, clamped up to 1
    assert quantize_weight(2) == 1          # 2 // 6 = 0, clamped up to 1
    assert quantize_weight(1000) == 15      # clamped down to max magnitude


def test_quantize_weight_rejects_nonpositive():
    with pytest.raises(ValueError):
        quantize_weight(0)
    with pytest.raises(ValueError):
        quantize_weight(-5)


def test_quantize_weight_custom_scale_and_width():
    assert quantize_weight(30, scale=10, bit_width=3) == 3   # 30//10=3, max=7
    assert quantize_weight(100, scale=10, bit_width=3) == 7  # clamped to 2**3-1


def test_negate_bits_two_complement_roundtrip():
    b = GateBuilder()
    bits = b.const_bits(5, 4)
    neg = negate_bits(b, bits, width=6)
    netlist = {"gates": b.gates, "input_pins": b.input_pins}
    result = evaluate_netlist(netlist, {})
    signed_value = to_int(neg, result)
    # two's complement of 5 in 6 bits is 64-5=59
    assert signed_value == 59


TINY_SUBGRAPH = {
    "neurons": [
        {"id": 100, "type": "DNp01", "side": "L", "role": "gf"},
        {"id": 101, "type": "DNp01", "side": "R", "role": "gf"},
        {"id": 1, "type": "LC4", "side": "L", "role": "visual_input"},
        {"id": 2, "type": "LPLC2", "side": "L", "role": "visual_input"},
        {"id": 3, "type": "LC4", "side": "R", "role": "visual_input"},
        {"id": 4, "type": "LPLC2", "side": "R", "role": "visual_input"},
        {"id": 200, "type": "TTMn", "side": "L", "role": "jump_motor"},
        {"id": 201, "type": "TTMn", "side": "R", "role": "jump_motor"},
    ],
    "edges": [
        {"pre": 1, "post": 100, "weight": 60, "sign": 1},
        {"pre": 2, "post": 100, "weight": 30, "sign": 1},
        {"pre": 3, "post": 101, "weight": 60, "sign": 1},
        {"pre": 4, "post": 101, "weight": 30, "sign": 1},
        {"pre": 100, "post": 200, "weight": 20, "sign": 1},
        {"pre": 101, "post": 201, "weight": 20, "sign": 1},
    ],
}


def test_build_full_netlist_has_expected_pins_and_only_nand_latch_gates():
    net = build_full_netlist(TINY_SUBGRAPH)
    assert set(g["type"] for g in net["gates"]) <= {"NAND", "LATCH"}
    assert "reset" in net["input_pins"]
    for nid in (1, 2, 3, 4):
        assert f"spike_{nid}" in net["input_pins"]
    assert set(net["output_pins"].keys()) == {"jump_left", "jump_right", "jump"}
    # exactly one LATCH per hemisphere
    latch_ids = [g["id"] for g in net["gates"] if g["type"] == "LATCH"]
    assert len(latch_ids) == 2
    assert set(latch_ids) == {net["output_pins"]["jump_left"], net["output_pins"]["jump_right"]}


def test_build_full_netlist_neuron_gate_map_covers_every_neuron():
    net = build_full_netlist(TINY_SUBGRAPH)
    mapped_ids = {m["neuron_id"] for m in net["neuron_gate_map"]}
    all_ids = {n["id"] for n in TINY_SUBGRAPH["neurons"]}
    assert mapped_ids == all_ids


def _eval_full(net, spikes: dict, reset: int, prev_state=None):
    values = {"reset": reset}
    for pin in net["input_pins"]:
        if pin.startswith("spike_"):
            nid = int(pin.split("_", 1)[1])
            values[pin] = spikes.get(nid, 0)
    return evaluate_netlist(net, values, prev_state=prev_state)


def test_coincidence_threshold_is_largest_input_plus_one():
    inputs = [("a", 10, 1), ("b", 5, 1), ("c", 3, -1)]
    # largest POSITIVE-sign magnitude is 10 -> threshold 11; the negative
    # (inhibitory) input's magnitude is never used as "largest".
    assert coincidence_threshold(inputs, max_possible_sum=15) == 11


def test_coincidence_threshold_no_positive_inputs_is_one():
    inputs = [("a", 7, -1)]
    assert coincidence_threshold(inputs, max_possible_sum=0) == 1


def test_full_netlist_jump_fires_when_enough_visual_drive_present():
    net = build_full_netlist(TINY_SUBGRAPH)
    # clear both latches first
    cleared = _eval_full(net, {}, reset=1)
    # left LC4(60)+LPLC2(30): quantized 10+5=15. Coincidence threshold =
    # (largest single input magnitude, 10) + 1 = 11. Both firing (sum=15)
    # clears 11; GF fires -> TTMn (single input, identity pass-through)
    # fires -> latch sets.
    result = _eval_full(net, {1: 1, 2: 1}, reset=0, prev_state=cleared["_latch_state"])
    assert result[net["output_pins"]["jump_left"]] == 1
    assert result[net["output_pins"]["jump_right"]] == 0
    assert result[net["output_pins"]["jump"]] == 1


def test_full_netlist_single_input_alone_never_fires_gf_coincidence_unit():
    """The whole point of the coincidence rule: one LC4-strength input alone
    (quantized 10) must NOT cross threshold 11 by itself -- only the
    combination of LC4+LPLC2 (sum 15) does."""
    net = build_full_netlist(TINY_SUBGRAPH)
    cleared = _eval_full(net, {}, reset=1)
    result = _eval_full(net, {1: 1}, reset=0, prev_state=cleared["_latch_state"])
    assert result[net["output_pins"]["jump_left"]] == 0


def test_full_netlist_jump_does_not_fire_with_no_drive():
    net = build_full_netlist(TINY_SUBGRAPH)
    cleared = _eval_full(net, {}, reset=1)
    result = _eval_full(net, {}, reset=0, prev_state=cleared["_latch_state"])
    assert result[net["output_pins"]["jump_left"]] == 0
    assert result[net["output_pins"]["jump_right"]] == 0
    assert result[net["output_pins"]["jump"]] == 0


def test_full_netlist_latch_holds_after_stimulus_removed():
    net = build_full_netlist(TINY_SUBGRAPH)
    cleared = _eval_full(net, {}, reset=1)
    fired = _eval_full(net, {1: 1, 2: 1}, reset=0, prev_state=cleared["_latch_state"])
    held = _eval_full(net, {}, reset=0, prev_state=fired["_latch_state"])
    assert held[net["output_pins"]["jump_left"]] == 1  # still held, not reset


def test_latch_set_is_structurally_gated_by_reset():
    """Point 7 (reset-dominant conditioning): whenever reset=1, the LATCH's
    set_n input must be forced to 1 (inactive) REGARDLESS of whether TTMn
    fired, because set_n is wired as NAND(ttmn_fires, reset_n) -- not merely
    "by evaluation convention" but because reset_n=0 (asserted) makes any
    NAND(..., 0) evaluate to 1 by construction. So (set_n=0, reset_n=0) is
    structurally unreachable at this latch."""
    net = build_full_netlist(TINY_SUBGRAPH)
    latch_id = net["output_pins"]["jump_left"]
    latch_gate = next(g for g in net["gates"] if g["id"] == latch_id)
    set_n_id, reset_n_id = latch_gate["inputs"]
    for spikes in ({}, {1: 1, 2: 1}):  # no drive, and full drive
        result = _eval_full(net, spikes, reset=1)
        assert result[reset_n_id] == 0   # reset asserted (active-low)
        assert result[set_n_id] == 1     # set forced inactive no matter what


def test_extract_seed_fragment_is_verbatim_subset_of_full():
    net = build_full_netlist(TINY_SUBGRAPH)
    seed = extract_seed_fragment(net, hemisphere="L")
    assert len(seed["gates"]) == 3
    assert sum(1 for g in seed["gates"] if g["type"] == "NAND") == 2
    assert sum(1 for g in seed["gates"] if g["type"] == "LATCH") == 1
    full_gates_by_id = {g["id"]: g for g in net["gates"]}
    for g in seed["gates"]:
        # parsed-equal (same id/type/inputs) to the full netlist's gate --
        # see test_netlist_schema.py for an actual byte-for-byte check
        # against the checked-in full.json/seed.json files on disk.
        assert full_gates_by_id[g["id"]] == g


def test_seed_fragment_reproduces_latch_behavior_standalone():
    net = build_full_netlist(TINY_SUBGRAPH)
    seed = extract_seed_fragment(net, hemisphere="L")
    ttmn_pin, reset_pin = seed["input_pins"]
    cleared = evaluate_netlist(seed, {ttmn_pin: 0, reset_pin: 1})
    fired = evaluate_netlist(seed, {ttmn_pin: 1, reset_pin: 0}, prev_state=cleared["_latch_state"])
    assert fired[seed["output_pins"]["jump_left"]] == 1


# ------------------------------------------------------------------------
# Point 6: the identity-passthrough optimization for single-input threshold
# units must never change any jump decision, only the gate count. Checked
# exhaustively (all 4096 stimulus patterns) against the real, checked-in
# GF subgraph -- not just the tiny synthetic fixture above.
# ------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SUBGRAPH_PATH = _REPO_ROOT / "circuit" / "data" / "subgraph.json"


@pytest.mark.skipif(not _SUBGRAPH_PATH.exists(),
                     reason="circuit/data/subgraph.json not present "
                            "(run `python -m circuit.extract` first)")
def test_identity_optimization_never_changes_jump_output_across_all_patterns():
    from circuit.equivalence import generate_exhaustive_patterns, load_side_data, simulate_binarized

    with open(_SUBGRAPH_PATH, encoding="utf-8") as f:
        subgraph = json.load(f)

    optimized = build_full_netlist(subgraph, optimize_single_input=True)
    unoptimized = build_full_netlist(subgraph, optimize_single_input=False)
    assert len(optimized["gates"]) < len(unoptimized["gates"]), \
        "the identity-passthrough optimization should strictly reduce gate count"

    side_data = load_side_data(subgraph)
    patterns = generate_exhaustive_patterns(side_data)
    assert len(patterns) == 4096

    mismatches = [
        p for p in patterns
        if simulate_binarized(p, optimized) != simulate_binarized(p, unoptimized)
    ]
    assert mismatches == [], (
        f"identity-passthrough optimization changed the jump decision on "
        f"{len(mismatches)}/4096 patterns, e.g. {mismatches[:3]}"
    )
