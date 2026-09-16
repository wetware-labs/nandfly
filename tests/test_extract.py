"""Unit tests for circuit/extract.py's pure subgraph-assembly logic (no real
MaleCNS files touched here -- those are exercised by `python -m
circuit.extract`, see circuit/DERIVATION.md)."""
import numpy as np
import pytest

from circuit.extract import (
    build_subgraph,
    neurons_of_type,
    retained_mask,
    top_k_by_weight,
    transmitter_sign,
)


def test_transmitter_sign_known_and_ambiguous():
    assert transmitter_sign("acetylcholine") == 1
    assert transmitter_sign("gaba") == -1
    assert transmitter_sign("glutamate") == -1
    assert transmitter_sign("histamine") == -1
    assert transmitter_sign("dopamine") == 1  # ambiguous default
    assert transmitter_sign(None) == 1
    assert transmitter_sign(None, ambiguous_sign=-1) == -1


def test_retained_mask_drops_glia_and_empty_superclass():
    annotations = {
        "superclass": ["visual_projection", "", None, "descending_neuron"],
        "status": ["Traced", "Traced", "Traced", "Glia"],
    }
    mask = retained_mask(annotations)
    assert mask.tolist() == [True, False, False, False]


def test_neurons_of_type_filters_by_type_and_retained():
    annotations = {
        "bodyId": np.array([1, 2, 3, 4], dtype=np.int64),
        "type": np.array(["LC4", "LC4", "LPLC2", "LC4"], dtype=object),
        "somaSide": np.array(["L", "R", "L", "L"], dtype=object),
    }
    retained = np.array([True, True, True, False])
    result = neurons_of_type(annotations, retained, "LC4")
    assert result == {1: "L", 2: "R"}  # body 4 dropped (not retained)


def test_top_k_by_weight_orders_descending_and_breaks_ties_by_id():
    pairs = [(10, 5), (11, 9), (12, 9), (13, 1)]
    assert top_k_by_weight(pairs, 2) == [(11, 9), (12, 9)]
    assert top_k_by_weight(pairs, 10) == sorted(pairs, key=lambda pw: (-pw[1], pw[0]))


def test_build_subgraph_keeps_only_ipsilateral_topk_visual_edges():
    node_types = {
        "DNp01": {100: "L", 101: "R"},
        "LC4": {1: "L", 2: "L", 3: "L", 4: "R"},
        "LPLC2": {5: "L", 6: "R"},
        "TTMn": {200: "L", 201: "R"},
    }
    consensus_nt = {i: "acetylcholine" for i in [100, 101, 1, 2, 3, 4, 5, 6, 200, 201]}
    candidate_edges = [
        (1, 100, 50), (2, 100, 80), (3, 100, 10),   # LC4-L -> DNp01-L, top2 by weight = {2,1}
        (4, 101, 5),                                  # LC4-R -> DNp01-R (cross-side ignored below)
        (5, 100, 20),                                  # LPLC2-L -> DNp01-L
        (6, 101, 30),                                  # LPLC2-R -> DNp01-R
        (4, 100, 999),                                  # cross-side LC4(R)->DNp01(L): must be dropped
        (100, 200, 20), (101, 201, 70),                 # GF -> TTMn, ipsilateral
    ]
    sub = build_subgraph(node_types, consensus_nt, candidate_edges, top_k=2)

    visual_edges = [e for e in sub["edges"] if e["post"] in (100, 101)]
    visual_pre_ids = sorted(e["pre"] for e in visual_edges)
    # top-2 LC4-L by weight are bodies 2 (80) and 1 (50); body 3 (10) dropped
    assert 3 not in visual_pre_ids
    assert 2 in visual_pre_ids and 1 in visual_pre_ids
    # cross-side edge (4 -> 100) must never appear
    assert not any(e["pre"] == 4 and e["post"] == 100 for e in sub["edges"])

    motor_edges = [e for e in sub["edges"] if e["pre"] in (100, 101)]
    assert {(e["pre"], e["post"], e["weight"]) for e in motor_edges} == {(100, 200, 20), (101, 201, 70)}


def test_build_subgraph_records_dlmn_as_excluded_when_no_direct_edge():
    node_types = {
        "DNp01": {100: "L"},
        "LC4": {1: "L"},
        "LPLC2": {},
        "TTMn": {200: "L"},
        "DLMn a, b": {300: "L"},
        "DLMn c-f": {},
    }
    consensus_nt = {i: "acetylcholine" for i in [100, 1, 200, 300]}
    candidate_edges = [(1, 100, 50), (100, 200, 20)]
    sub = build_subgraph(node_types, consensus_nt, candidate_edges, top_k=3)
    assert sub["excluded_motor_types"]["DLMn a, b"]["found_in_annotations"] == 1
    assert sub["excluded_motor_types"]["DLMn a, b"]["direct_synapse_from_DNp01"] is False
    assert not any(e["post"] == 300 for e in sub["edges"])


def test_build_subgraph_deterministic_output_order_independent_of_input_order():
    node_types = {
        "DNp01": {100: "L"},
        "LC4": {1: "L", 2: "L"},
        "LPLC2": {},
        "TTMn": {200: "L"},
    }
    consensus_nt = {i: "acetylcholine" for i in [100, 1, 2, 200]}
    edges_a = [(1, 100, 50), (2, 100, 80), (100, 200, 20)]
    edges_b = list(reversed(edges_a))
    sub_a = build_subgraph(node_types, consensus_nt, edges_a, top_k=2)
    sub_b = build_subgraph(node_types, consensus_nt, edges_b, top_k=2)
    assert sorted(sub_a["edges"], key=lambda e: (e["pre"], e["post"])) == \
        sorted(sub_b["edges"], key=lambda e: (e["pre"], e["post"]))
