"""Schema validation for the checked-in generated artifacts
(circuit/data/subgraph.json, circuit/netlists/full.json,
circuit/netlists/seed.json) against circuit/SCHEMA.md, plus a determinism
check that re-running the pipeline on the checked-in subgraph reproduces the
checked-in netlists byte-for-byte."""
import json
from pathlib import Path

import pytest

from circuit.binarize import build_full_netlist, extract_seed_fragment

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBGRAPH_PATH = REPO_ROOT / "circuit" / "data" / "subgraph.json"
FULL_PATH = REPO_ROOT / "circuit" / "netlists" / "full.json"
SEED_PATH = REPO_ROOT / "circuit" / "netlists" / "seed.json"

pytestmark = pytest.mark.skipif(
    not (SUBGRAPH_PATH.exists() and FULL_PATH.exists() and SEED_PATH.exists()),
    reason="generated artifacts not present (run `python -m circuit.extract` "
           "and `python -m circuit.binarize` first)",
)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _all_signal_ids(netlist):
    ids = set(netlist["input_pins"])
    ids |= {g["id"] for g in netlist["gates"]}
    return ids


def _validate_netlist_shape(netlist, require_neuron_map=True):
    assert netlist["schema_version"] == 1
    assert isinstance(netlist["gates"], list) and netlist["gates"]
    assert isinstance(netlist["input_pins"], list)
    assert isinstance(netlist["output_pins"], dict) and netlist["output_pins"]

    seen_ids = set()
    defined = set(netlist["input_pins"])
    for g in netlist["gates"]:
        assert set(g.keys()) == {"id", "type", "inputs"}
        assert g["id"] not in seen_ids, f"duplicate gate id {g['id']}"
        seen_ids.add(g["id"])
        assert g["type"] in ("NAND", "LATCH")
        assert len(g["inputs"]) == 2
        for inp in g["inputs"]:
            assert inp in defined, f"gate {g['id']} references undefined signal {inp}"
        defined.add(g["id"])

    all_ids = _all_signal_ids(netlist)
    for name, gate_id in netlist["output_pins"].items():
        assert gate_id in all_ids, f"output pin {name} -> unknown signal {gate_id}"

    if require_neuron_map:
        assert isinstance(netlist["neuron_gate_map"], list) and netlist["neuron_gate_map"]
        for row in netlist["neuron_gate_map"]:
            assert row["signal"] in all_ids
            assert row["signal_kind"] in ("input_pin", "gate_output")
            assert row["role"] in ("visual_input", "gf", "jump_motor")


def test_full_netlist_matches_schema():
    net = _load(FULL_PATH)
    _validate_netlist_shape(net, require_neuron_map=True)
    assert "const_0" in net["input_pins"] and "const_1" in net["input_pins"]
    assert "reset" in net["input_pins"]
    assert set(net["output_pins"].keys()) == {"jump_left", "jump_right", "jump"}
    assert "params" in net
    gate_types = {g["type"] for g in net["gates"]}
    assert gate_types <= {"NAND", "LATCH"}
    n_latch = sum(1 for g in net["gates"] if g["type"] == "LATCH")
    assert n_latch == 2  # exactly one per hemisphere


def test_seed_netlist_matches_schema():
    seed = _load(SEED_PATH)
    _validate_netlist_shape(seed, require_neuron_map=False)
    assert len(seed["gates"]) == 3
    assert sum(1 for g in seed["gates"] if g["type"] == "NAND") == 2
    assert sum(1 for g in seed["gates"] if g["type"] == "LATCH") == 1
    assert "description" in seed and "source" in seed


def test_seed_is_byte_identical_subset_of_full():
    full = _load(FULL_PATH)
    seed = _load(SEED_PATH)
    full_gates_by_id = {g["id"]: g for g in full["gates"]}
    for g in seed["gates"]:
        assert g["id"] in full_gates_by_id
        assert full_gates_by_id[g["id"]] == g


def test_subgraph_neurons_all_have_valid_roles_and_sides():
    sub = _load(SUBGRAPH_PATH)
    for n in sub["neurons"]:
        assert n["role"] in ("gf", "visual_input", "jump_motor")
        assert n["side"] in ("L", "R")
        assert n["sign"] in (1, -1)


def test_regenerating_full_netlist_from_checked_in_subgraph_is_byte_identical():
    """The strongest reproducibility check: re-running the binarizer on the
    already-extracted (and checked-in) subgraph must reproduce the
    checked-in full.json exactly -- no hidden nondeterminism (dict
    ordering, randomness, wall-clock timestamps, etc)."""
    subgraph = _load(SUBGRAPH_PATH)
    regenerated = build_full_netlist(subgraph)
    checked_in = _load(FULL_PATH)
    assert regenerated == checked_in


def test_regenerating_seed_from_regenerated_full_is_byte_identical():
    subgraph = _load(SUBGRAPH_PATH)
    regenerated_full = build_full_netlist(subgraph)
    regenerated_seed = extract_seed_fragment(regenerated_full)
    checked_in_seed = _load(SEED_PATH)
    assert regenerated_seed["gates"] == checked_in_seed["gates"]
    assert regenerated_seed["input_pins"] == checked_in_seed["input_pins"]
    assert regenerated_seed["output_pins"] == checked_in_seed["output_pins"]


def test_running_binarize_twice_is_deterministic():
    subgraph = _load(SUBGRAPH_PATH)
    net_a = build_full_netlist(subgraph)
    net_b = build_full_netlist(subgraph)
    assert net_a == net_b
