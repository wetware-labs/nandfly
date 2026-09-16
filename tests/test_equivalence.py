"""Tests for circuit/equivalence.py: exhaustive stimulus generation, the LIF
reference model, the binarized-vs-LIF comparison harness, and the
threshold-fraction sweep."""
from circuit.binarize import build_full_netlist
from circuit.equivalence import (
    generate_exhaustive_patterns,
    load_side_data,
    run_equivalence,
    run_threshold_fraction_sweep,
    simulate_binarized,
    simulate_lif,
    simulate_lif_side,
)
from tests.test_binarize import TINY_SUBGRAPH


def test_generate_exhaustive_patterns_count_is_2_pow_k_each_side():
    side_data = load_side_data(TINY_SUBGRAPH)
    k_l = len(side_data["L"]["visual"])
    k_r = len(side_data["R"]["visual"])
    patterns = generate_exhaustive_patterns(side_data)
    assert len(patterns) == (2 ** k_l) * (2 ** k_r)


def test_generate_exhaustive_patterns_covers_every_subset_exactly_once():
    side_data = load_side_data(TINY_SUBGRAPH)
    left_ids = tuple(nid for nid, _w in side_data["L"]["visual"])
    patterns = generate_exhaustive_patterns(side_data)
    left_subsets_seen = {tuple(sorted(p["active_L"])) for p in patterns}
    # every subset of left_ids must appear, and only once per (L, R) pair
    import itertools
    expected = {tuple(sorted(c)) for r in range(len(left_ids) + 1)
                for c in itertools.combinations(left_ids, r)}
    assert left_subsets_seen == expected


def test_generate_exhaustive_patterns_is_deterministic():
    side_data = load_side_data(TINY_SUBGRAPH)
    a = generate_exhaustive_patterns(side_data)
    b = generate_exhaustive_patterns(side_data)
    assert a == b


def test_generate_exhaustive_patterns_subset_sizes_match_level():
    side_data = load_side_data(TINY_SUBGRAPH)
    for p in generate_exhaustive_patterns(side_data):
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
    summary = run_equivalence(TINY_SUBGRAPH, net)
    assert summary["n_patterns"] > 0
    assert 0.0 <= summary["agreement_pct"] <= 100.0
    assert summary["n_agree"] + len(summary["disagreements"]) == summary["n_patterns"]
    for r in summary["rows"]:
        assert r["agree"] == (r["lif_jump"] == r["bin_jump"])


def test_run_equivalence_is_exhaustive_by_default():
    side_data = load_side_data(TINY_SUBGRAPH)
    net = build_full_netlist(TINY_SUBGRAPH)
    summary = run_equivalence(TINY_SUBGRAPH, net)
    assert summary["n_patterns"] == len(generate_exhaustive_patterns(side_data))


def test_run_equivalence_none_pattern_always_agrees_no_jump():
    net = build_full_netlist(TINY_SUBGRAPH)
    summary = run_equivalence(TINY_SUBGRAPH, net)
    none_rows = [r for r in summary["rows"] if r["level_L"] == 0 and r["level_R"] == 0]
    assert len(none_rows) == 1
    assert none_rows[0]["lif_jump"] is False
    assert none_rows[0]["bin_jump"] is False


def test_threshold_fraction_sweep_covers_every_requested_fraction():
    fractions = (0.5, 0.25)
    rows = run_threshold_fraction_sweep(TINY_SUBGRAPH, fractions=fractions)
    assert [r["fraction"] for r in rows] == list(fractions)
    for r in rows:
        assert 0.0 <= r["exhaustive_agreement_pct"] <= 100.0


def test_threshold_fraction_sweep_lower_fraction_never_raises_threshold():
    """A lower threshold FRACTION should never require MORE weighted drive
    than a higher one to fire, for the same subgraph -- i.e. the multi-input
    unit's actual fires-decision for "all inputs active" must stay true
    across the whole swept range (sanity check on the sweep's own rule, not
    on any agreement number)."""
    for frac in (0.5, 0.3, 0.1):
        def rule(inputs, max_possible_sum, frac=frac):
            import math
            return math.ceil(frac * max_possible_sum)

        net = build_full_netlist(TINY_SUBGRAPH, multi_input_threshold_fn=rule)
        side_data = load_side_data(TINY_SUBGRAPH)
        all_left = [nid for nid, _w in side_data["L"]["visual"]]
        assert simulate_binarized({"active_L": all_left, "active_R": []}, net) is True
