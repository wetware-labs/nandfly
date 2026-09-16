"""Dedicated tests for the claim in circuit/DERIVATION.md section 7: seed.json
is a verbatim (parsed-equal -- same id/type/inputs; see
tests/test_netlist_schema.py for an actual byte-for-byte check of the
checked-in files) 2-NAND + 1-LATCH sub-piece of full.json, not a
hand-written stand-in."""
from circuit.binarize import build_full_netlist, extract_seed_fragment
from tests.test_binarize import TINY_SUBGRAPH


def test_seed_fragment_gate_count_and_types():
    full = build_full_netlist(TINY_SUBGRAPH)
    for hemisphere, output_key in (("L", "jump_left"), ("R", "jump_right")):
        seed = extract_seed_fragment(full, hemisphere=hemisphere)
        assert len(seed["gates"]) == 3
        types = sorted(g["type"] for g in seed["gates"])
        assert types == ["LATCH", "NAND", "NAND"]
        assert seed["output_pins"][output_key] == full["output_pins"][output_key]


def test_seed_fragment_gates_are_identical_objects_from_full_not_reconstructed():
    full = build_full_netlist(TINY_SUBGRAPH)
    seed = extract_seed_fragment(full, hemisphere="L")
    full_by_id = {g["id"]: g for g in full["gates"]}
    for g in seed["gates"]:
        # same id, same type, same input wiring -- not just "equivalent logic"
        assert g["id"] in full_by_id
        assert g == full_by_id[g["id"]]


def test_seed_fragment_source_metadata_names_the_exact_gate_ids():
    full = build_full_netlist(TINY_SUBGRAPH)
    seed = extract_seed_fragment(full, hemisphere="R")
    assert seed["source"]["hemisphere"] == "R"
    assert seed["source"]["netlist"] == "full.json"
    gate_ids_in_seed = {g["id"] for g in seed["gates"]}
    assert set(seed["source"]["gate_ids"]) == gate_ids_in_seed


def test_seed_fragment_latch_is_the_same_latch_that_drives_full_netlists_output():
    full = build_full_netlist(TINY_SUBGRAPH)
    seed = extract_seed_fragment(full, hemisphere="L")
    latch_gate_ids_full = {g["id"] for g in full["gates"] if g["type"] == "LATCH"}
    latch_gate_ids_seed = {g["id"] for g in seed["gates"] if g["type"] == "LATCH"}
    assert latch_gate_ids_seed <= latch_gate_ids_full
    assert full["output_pins"]["jump_left"] in latch_gate_ids_seed
