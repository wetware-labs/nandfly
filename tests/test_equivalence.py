"""Tests for circuit/equivalence.py: stimulus generation, the LIF reference
model, and the binarized-vs-LIF comparison harness."""
from circuit.binarize import build_full_netlist
from circuit.equivalence import (
    DRAWS_PER_LEVEL,
    generate_patterns,
    load_side_data,
    run_equivalence,
    simulate_binarized,
    simulate_lif,
    simulate_lif_side,
)
from tests.test_binarize import TINY_SUBGRAPH


def test_generate_patterns_count_and_determinism():
    side_data = load_side_data(TINY_SUBGRAPH)
    patterns_a = generate_patterns(side_data, draws_per_level=2, seed=42)
    patterns_b = generate_patterns(side_data, draws_per_level=2, seed=42)
    k_l = len(side_data["L"]["visual"])
    k_r = len(side_data["R"]["visual"])
    assert len(patterns_a) == (k_l + 1) * (k_r + 1) * 2
    assert patterns_a == patterns_b  # deterministic given a fixed seed


def test_generate_patterns_different_seed_differs():
    side_data = load_side_data(TINY_SUBGRAPH)
    a = generate_patterns(side_data, draws_per_level=2, seed=1)
    b = generate_patterns(side_data, draws_per_level=2, seed=2)
    assert a != b


def test_generate_patterns_subset_sizes_match_level():
    side_data = load_side_data(TINY_SUBGRAPH)
    for p in generate_patterns(side_data, draws_per_level=1, seed=7):
        assert len(p["active_L"]) == p["level_L"]
        assert len(p["active_R"]) == p["level_R"]


def test_simulate_lif_side_no_drive_never_spikes():
    side_data = load_side_data(TINY_SUBGRAPH)
    assert simulate_lif_side(set(), side_data["L"]) is False


def test_simulate_lif_side_full_drive_spikes():
    side_data = load_side_data(TINY_SUBGRAPH)
    all_ids = {nid for nid, _w in side_data["L"]["visual"]}
    assert simulate_lif_side(all_ids, side_data["L"]) is True


def test_simulate_lif_none_pattern_no_jump():
    side_data = load_side_data(TINY_SUBGRAPH)
    pattern = {"active_L": [], "active_R": []}
    assert simulate_lif(pattern, side_data) is False


def test_simulate_binarized_matches_full_drive_and_no_drive():
    net = build_full_netlist(TINY_SUBGRAPH)
    side_data = load_side_data(TINY_SUBGRAPH)
    all_left = [nid for nid, _w in side_data["L"]["visual"]]
    strong = {"active_L": all_left, "active_R": []}
    none = {"active_L": [], "active_R": []}
    assert simulate_binarized(strong, net) is True
    assert simulate_binarized(none, net) is False


def test_run_equivalence_summary_shape_and_bounds():
    net = build_full_netlist(TINY_SUBGRAPH)
    summary = run_equivalence(TINY_SUBGRAPH, net, draws_per_level=1, seed=99)
    assert summary["n_patterns"] > 0
    assert 0.0 <= summary["agreement_pct"] <= 100.0
    assert summary["n_agree"] + len(summary["disagreements"]) == summary["n_patterns"]
    for r in summary["rows"]:
        assert r["agree"] == (r["lif_jump"] == r["bin_jump"])


def test_run_equivalence_none_pattern_always_agrees_no_jump():
    net = build_full_netlist(TINY_SUBGRAPH)
    summary = run_equivalence(TINY_SUBGRAPH, net, draws_per_level=1, seed=5)
    none_rows = [r for r in summary["rows"] if r["level_L"] == 0 and r["level_R"] == 0]
    assert len(none_rows) == 1
    assert none_rows[0]["lif_jump"] is False
    assert none_rows[0]["bin_jump"] is False
