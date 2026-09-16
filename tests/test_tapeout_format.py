"""Tests for tapeout/format.py: round-trip encode/decode (seed.json +
synthetic edge cases), a byte-level golden test for the seed encoding, and an
exhaustive semantic check of the SR-latch -> TapeOut-native-LATCH translation
(see tapeout/format.py's module docstring for the derivation this checks)."""
import itertools
import json
from pathlib import Path

import pytest

from circuit.gates import evaluate_netlist
from tapeout import format as tf

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = REPO_ROOT / "circuit" / "netlists" / "seed.json"

# Golden byte encoding of circuit/netlists/seed.json, computed once by
# tapeout.format.encode_netlist and checked in here as a regression fixture.
# 60 bytes: 2 our-NAND cells (7 bytes each) + our-LATCH's 5-cell translation
# (1 LATCH cell, 4 bytes + 4 NAND cells, 7 bytes each = 32 bytes) + a 2-cell
# NAND identity-buffer tail for the single "jump_left" output pin (14 bytes).
SEED_GOLDEN_HEX = (
    "00000003000003000000020000040100000a000000060000060000000500000700"
    "000004000008000000090000090000000a00000a0000000b00000b"
)

SYNTHETIC_NETLISTS = {
    "single_nand": {
        "schema_version": 1,
        "gates": [{"id": "g1", "type": "NAND", "inputs": ["a", "b"]}],
        "input_pins": ["a", "b"],
        "output_pins": {"out": "g1"},
    },
    "latch_only": {
        "schema_version": 1,
        "gates": [{"id": "q", "type": "LATCH", "inputs": ["s", "r"]}],
        "input_pins": ["s", "r"],
        "output_pins": {"q": "q"},
    },
    "two_outputs": {
        "schema_version": 1,
        "gates": [
            {"id": "g1", "type": "NAND", "inputs": ["a", "b"]},
            {"id": "g2", "type": "NAND", "inputs": ["g1", "g1"]},
        ],
        "input_pins": ["a", "b"],
        "output_pins": {"nand_out": "g1", "not_nand_out": "g2"},
    },
}


def _load_seed():
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _schema_of(netlist: dict) -> dict:
    return {
        "schema_version": netlist["schema_version"],
        "gates": netlist["gates"],
        "input_pins": netlist["input_pins"],
        "output_pins": netlist["output_pins"],
    }


@pytest.mark.skipif(not SEED_PATH.exists(), reason="circuit/netlists/seed.json not present")
def test_roundtrip_seed_json():
    seed = _load_seed()
    data, meta = tf.encode_netlist(seed)
    decoded = tf.decode_to_schema(data, meta)
    assert decoded == _schema_of(seed)


@pytest.mark.skipif(not SEED_PATH.exists(), reason="circuit/netlists/seed.json not present")
def test_seed_encoding_is_byte_for_byte_golden():
    seed = _load_seed()
    data, _meta = tf.encode_netlist(seed)
    assert len(data) == 60
    assert data.hex() == SEED_GOLDEN_HEX


@pytest.mark.parametrize("name", sorted(SYNTHETIC_NETLISTS))
def test_roundtrip_synthetic_netlists(name):
    netlist = SYNTHETIC_NETLISTS[name]
    data, meta = tf.encode_netlist(netlist)
    decoded = tf.decode_to_schema(data, meta)
    assert decoded == _schema_of(netlist)


def test_single_gate_netlist_is_the_smallest_case():
    """Single NAND, 2 inputs, 1 output: 1 NAND cell (7B) + 2 buffer NAND
    cells (14B) = 21 bytes -- sanity-checks the encoder emits no more than
    the documented structure requires."""
    data, meta = tf.encode_netlist(SYNTHETIC_NETLISTS["single_nand"])
    assert len(data) == 21
    assert meta.n_inputs == 2 and meta.n_outputs == 1


def test_latch_only_netlist_roundtrips_through_generic_decode_circuit_too():
    netlist = SYNTHETIC_NETLISTS["latch_only"]
    data, meta = tf.encode_netlist(netlist)
    circuit = tf.decode_circuit(data, meta.n_inputs, meta.n_outputs)
    desc = circuit.describe()
    assert desc["latch"] == 1
    assert desc["nand"] == 4 + 2  # 4 for the SR-translation, 2 for the output buffer


def test_latch_translation_matches_our_sr_latch_truth_table_exhaustively():
    """The core correctness claim of tapeout/format.py's LATCH handling:
    for every combination of (set_n, reset_n, previous Q), the TapeOut-native
    circuit our encoder emits must agree with circuit/gates.py's own
    evaluate_netlist SR-latch semantics. See tapeout/format.py's module
    docstring for the closed-form derivation this exercises."""
    netlist = SYNTHETIC_NETLISTS["latch_only"]
    data, meta = tf.encode_netlist(netlist)

    mismatches = []
    for s_val, r_val, p_val in itertools.product((0, 1), repeat=3):
        ours = evaluate_netlist(netlist, {"s": s_val, "r": r_val}, prev_state={"q": p_val})["q"]

        circuit = tf.decode_circuit(data, meta.n_inputs, meta.n_outputs)
        outs, _next_state = tf.tick(circuit, [s_val, r_val], state=[p_val])
        chain = outs[0]

        if ours != chain:
            mismatches.append((s_val, r_val, p_val, ours, chain))

    assert not mismatches, mismatches


@pytest.mark.skipif(not SEED_PATH.exists(), reason="circuit/netlists/seed.json not present")
def test_seed_two_tick_protocol_matches_our_evaluator_for_every_input_combination():
    """The full end-to-end semantic claim: our documented two-call evaluation
    protocol (reset tick, then stimulus tick -- circuit/SCHEMA.md "Evaluation
    protocol") maps to two TapeOut ticks with bit-identical output, for every
    combination of the seed fragment's 2 non-const inputs across both ticks."""
    seed = _load_seed()
    data, meta = tf.encode_netlist(seed)
    circuit = tf.decode_circuit(data, meta.n_inputs, meta.n_outputs)

    mismatches = []
    for g326_1, reset_1, g326_2, reset_2 in itertools.product((0, 1), repeat=4):
        r1 = evaluate_netlist(seed, {"g326": g326_1, "reset": reset_1})
        r2 = evaluate_netlist(seed, {"g326": g326_2, "reset": reset_2}, prev_state=r1["_latch_state"])
        ours = r2["jump_left"]

        _o1, st1 = tf.tick(circuit, [g326_1, reset_1], state=None)
        o2, _st2 = tf.tick(circuit, [g326_2, reset_2], state=st1)
        chain = o2[0]

        if ours != chain:
            mismatches.append((g326_1, reset_1, g326_2, reset_2, ours, chain))

    assert not mismatches, mismatches


def test_decode_cells_rejects_truncated_bytes():
    with pytest.raises(ValueError, match="truncated"):
        tf.decode_cells(bytes([tf.OP_NAND, 0, 0]))  # NAND needs 6 operand bytes, only 2 given


def test_decode_cells_rejects_unknown_opcode():
    with pytest.raises(ValueError, match="unknown TapeOut opcode"):
        tf.decode_cells(bytes([0xFF]))


def test_decode_cells_rejects_forward_referencing_nand():
    # NAND referencing signal 5 when only signals 0..4 exist yet (n_inputs=2).
    bad = bytes([tf.OP_NAND]) + (5).to_bytes(3, "big") + (0).to_bytes(3, "big")
    with pytest.raises(ValueError, match="not-yet-defined"):
        tf.decode_cells(bad, n_inputs=2)


def test_encode_cells_rejects_signal_out_of_u24_range():
    with pytest.raises(ValueError, match="u24"):
        tf.encode_cells([tf.Nand(1 << 24, 0)])
