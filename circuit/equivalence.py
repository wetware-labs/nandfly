"""Equivalence check: binarized NAND/LATCH full netlist vs. a leaky
integrate-and-fire (LIF) reference model, on a generated set of looming-style
visual stimulus patterns. Writes reports/equivalence.md.

--------------------------------------------------------------------------
Reference model
--------------------------------------------------------------------------
Same functional form as FlyMarket's sim/core/lif.py (`v = leak*v +
weight_scale*syn + external; spike = v >= v_thresh; reset to 0 on spike`),
reduced to this subgraph's 2-stage per-hemisphere chain: visual neurons are
treated as an external stimulus (not themselves simulated with LIF dynamics
-- they ARE the input), driving DNp01 (GF), whose spikes drive TTMn one tick
later (matching LIFBrain.step's synaptic-delay convention: a neuron's spike
at tick t only reaches postsynaptic targets at tick t+1, via `w_t @
last_spikes`).

`weight_scale = 1/50` is a single, documented, round constant (not tuned
against this test set): it means one visual synapse of "median" real
strength (~50 raw synapse-count in this subgraph) alone drives GF's membrane
potential to exactly its LIF threshold (1.0) in one tick. This is an
independent modeling choice from the binarized comparator's own "50% of
max-possible-sum" calibration (circuit/binarize.py) -- the two models are
NOT constructed to agree; agreement is measured, not assumed.

--------------------------------------------------------------------------
Stimulus generation ("looming ramps")
--------------------------------------------------------------------------
Each stimulus pattern picks, independently per hemisphere, a count c in
0..K (K = number of visual inputs on that side, 6 in this subgraph: top-3
LC4 + top-3 LPLC2) of active visual neurons, and a specific random subset of
that size (fixed RNG seed for reproducibility). The chosen neurons' combined
raw synaptic weight is ramped linearly from 0 at tick 0 up to full strength
at the last tick (`drive(t) = (t+1)/T * sum(raw_weight for active)`),
modeling a looming object's retinal drive increasing as it approaches. c=0
is the "none" stimulus; low c is "weak"; high c is "strong". For each (c_L,
c_R) pair (7x7=49 combinations) we draw `DRAWS_PER_LEVEL=2` independent
random subsets, giving 98 total patterns.

--------------------------------------------------------------------------
Binarized-side evaluation protocol
--------------------------------------------------------------------------
The binarized netlist is combinational (a single snapshot), so it is
evaluated once per pattern with the FULLY-FORMED stimulus (every chosen
active neuron's spike pin = 1, i.e. the ramp's final tick), preceded by a
reset-clear evaluation (reset=1, all spikes=0). This is an explicit,
documented limitation: the binarized model has no notion of the ramp's time
course, only of the final activated set. See the "Limitations" section
written into reports/equivalence.md by `write_report()`.
"""
import argparse
import json
import random
from pathlib import Path

from circuit.gates import evaluate_netlist

DEFAULT_SUBGRAPH = Path("circuit/data/subgraph.json")
DEFAULT_NETLIST = Path("circuit/netlists/full.json")
DEFAULT_REPORT = Path("reports/equivalence.md")

LIF_V_THRESH = 1.0
LIF_LEAK = 0.9
LIF_RESET = 0.0
LIF_WEIGHT_SCALE = 1.0 / 50.0
RAMP_TICKS = 6
DRAWS_PER_LEVEL = 2
RNG_SEED = 1234


def load_side_data(subgraph: dict) -> dict:
    neurons_by_id = {n["id"]: n for n in subgraph["neurons"]}
    edges_to = {}
    for e in subgraph["edges"]:
        edges_to.setdefault(e["post"], []).append(e)

    sides = {}
    for side in ("L", "R"):
        gf = next(n for n in subgraph["neurons"] if n["role"] == "gf" and n["side"] == side)
        ttmn = next(n for n in subgraph["neurons"] if n["role"] == "jump_motor" and n["side"] == side)
        visual_edges = [e for e in edges_to.get(gf["id"], [])]
        ttmn_edges = edges_to.get(ttmn["id"], [])
        assert len(ttmn_edges) == 1
        sides[side] = {
            "gf_id": gf["id"],
            "ttmn_id": ttmn["id"],
            "visual": [(e["pre"], e["weight"]) for e in visual_edges],
            "gf_to_ttmn_weight": ttmn_edges[0]["weight"],
        }
    return sides


def generate_patterns(side_data: dict, draws_per_level: int = DRAWS_PER_LEVEL,
                       seed: int = RNG_SEED) -> list:
    """Returns a list of patterns: {"active_L": [ids], "active_R": [ids]}."""
    rng = random.Random(seed)
    ids_by_side = {s: [nid for nid, _w in side_data[s]["visual"]] for s in ("L", "R")}
    k_by_side = {s: len(ids_by_side[s]) for s in ("L", "R")}

    def random_subset(side, count):
        return sorted(rng.sample(ids_by_side[side], count))

    patterns = []
    for c_l in range(k_by_side["L"] + 1):
        for c_r in range(k_by_side["R"] + 1):
            for _ in range(draws_per_level):
                patterns.append({
                    "active_L": random_subset("L", c_l),
                    "active_R": random_subset("R", c_r),
                    "level_L": c_l,
                    "level_R": c_r,
                })
    return patterns


def _label_for_level(c: int, k: int) -> str:
    if c == 0:
        return "none"
    if c <= k // 3:
        return "weak"
    if c <= (2 * k) // 3:
        return "medium"
    return "strong"


def simulate_lif_side(active_ids: set, side: dict, ticks: int = RAMP_TICKS) -> bool:
    """Runs the 2-stage (GF then TTMn) leaky-integrate-and-fire chain for
    `ticks` steps under a linearly-ramping external drive to GF. Returns
    whether TTMn ever spiked."""
    full_drive = sum(w for nid, w in side["visual"] if nid in active_ids)
    ttmn_weight = side["gf_to_ttmn_weight"]
    v_gf = 0.0
    v_ttmn = 0.0
    last_gf_spike = 0.0
    ttmn_ever_spiked = False
    for t in range(ticks):
        ext = LIF_WEIGHT_SCALE * full_drive * (t + 1) / ticks
        v_gf = LIF_LEAK * v_gf + ext
        gf_spike = v_gf >= LIF_V_THRESH
        if gf_spike:
            v_gf = LIF_RESET

        v_ttmn = LIF_LEAK * v_ttmn + LIF_WEIGHT_SCALE * ttmn_weight * last_gf_spike
        ttmn_spike = v_ttmn >= LIF_V_THRESH
        if ttmn_spike:
            v_ttmn = LIF_RESET
            ttmn_ever_spiked = True

        last_gf_spike = 1.0 if gf_spike else 0.0
    return ttmn_ever_spiked


def simulate_lif(pattern: dict, side_data: dict, ticks: int = RAMP_TICKS) -> bool:
    left = simulate_lif_side(set(pattern["active_L"]), side_data["L"], ticks)
    right = simulate_lif_side(set(pattern["active_R"]), side_data["R"], ticks)
    return left or right


def simulate_binarized(pattern: dict, netlist: dict) -> bool:
    all_spike_pins = [p for p in netlist["input_pins"] if p.startswith("spike_")]
    cleared = evaluate_netlist(
        netlist, {"reset": 1, **{p: 0 for p in all_spike_pins}}
    )
    active_ids = set(pattern["active_L"]) | set(pattern["active_R"])
    values = {"reset": 0}
    for p in all_spike_pins:
        nid = int(p.split("_", 1)[1])
        values[p] = 1 if nid in active_ids else 0
    result = evaluate_netlist(netlist, values, prev_state=cleared["_latch_state"])
    return bool(result[netlist["output_pins"]["jump"]])


def run_equivalence(subgraph: dict, netlist: dict, draws_per_level: int = DRAWS_PER_LEVEL,
                     seed: int = RNG_SEED, ticks: int = RAMP_TICKS) -> dict:
    side_data = load_side_data(subgraph)
    patterns = generate_patterns(side_data, draws_per_level, seed)
    k_by_side = {s: len(side_data[s]["visual"]) for s in ("L", "R")}

    rows = []
    for pattern in patterns:
        lif_jump = simulate_lif(pattern, side_data, ticks)
        bin_jump = simulate_binarized(pattern, netlist)
        label = _label_for_level(max(pattern["level_L"], pattern["level_R"]),
                                  max(k_by_side["L"], k_by_side["R"]))
        rows.append({
            "active_L": pattern["active_L"], "active_R": pattern["active_R"],
            "level_L": pattern["level_L"], "level_R": pattern["level_R"],
            "label": label, "lif_jump": lif_jump, "bin_jump": bin_jump,
            "agree": lif_jump == bin_jump,
        })

    n = len(rows)
    n_agree = sum(1 for r in rows if r["agree"])
    disagreements = [r for r in rows if not r["agree"]]
    by_label = {}
    for r in rows:
        by_label.setdefault(r["label"], {"n": 0, "agree": 0})
        by_label[r["label"]]["n"] += 1
        by_label[r["label"]]["agree"] += int(r["agree"])

    return {
        "n_patterns": n,
        "n_agree": n_agree,
        "agreement_pct": 100.0 * n_agree / n if n else 0.0,
        "by_label": by_label,
        "disagreements": disagreements,
        "rows": rows,
    }


def write_report(summary: dict, out_path: Path = DEFAULT_REPORT):
    lines = []
    lines.append("# GF Core Equivalence Report: Binarized NAND/LATCH vs. LIF Reference\n")
    lines.append(
        f"Stimulus set: {summary['n_patterns']} looming-ramp patterns "
        f"(see circuit/equivalence.py module docstring for generation).\n"
    )
    lines.append("## Headline result\n")
    lines.append(
        f"- **Overall jump/no-jump agreement: {summary['agreement_pct']:.1f}% "
        f"({summary['n_agree']}/{summary['n_patterns']})**\n"
    )
    lines.append("## Agreement by drive level\n")
    lines.append("| Drive level | Patterns | Agreement |")
    lines.append("|---|---|---|")
    for label in ("none", "weak", "medium", "strong"):
        d = summary["by_label"].get(label)
        if not d:
            continue
        pct = 100.0 * d["agree"] / d["n"] if d["n"] else 0.0
        lines.append(f"| {label} | {d['n']} | {d['agree']}/{d['n']} ({pct:.1f}%) |")
    lines.append("")

    lines.append("## Disagreement analysis\n")
    n_dis = len(summary["disagreements"])
    if n_dis == 0:
        lines.append("No disagreements on this stimulus set.\n")
    else:
        lif_only = sum(1 for r in summary["disagreements"] if r["lif_jump"] and not r["bin_jump"])
        bin_only = sum(1 for r in summary["disagreements"] if r["bin_jump"] and not r["lif_jump"])
        lines.append(
            f"{n_dis} of {summary['n_patterns']} patterns disagree. "
            f"LIF-jumped-but-binarized-didn't: {lif_only}. "
            f"Binarized-jumped-but-LIF-didn't: {bin_only}.\n"
        )
        lines.append("Sample disagreements (up to 10):\n")
        lines.append("| level_L | level_R | LIF | binarized |")
        lines.append("|---|---|---|---|")
        for r in summary["disagreements"][:10]:
            lines.append(f"| {r['level_L']} | {r['level_R']} | {r['lif_jump']} | {r['bin_jump']} |")
        lines.append("")

    lines.append("## Honest limitations\n")
    lines.append(
        "- The binarized netlist is purely combinational: it is evaluated once "
        "against the stimulus pattern's *fully-formed* active set, not against "
        "the LIF reference's tick-by-tick ramp. It has no notion of approach "
        "speed, only of the final visual population that ends up active.\n"
        "- The LIF reference and the binarized comparator use *independently "
        "chosen* calibration constants (LIF's weight_scale=1/50 vs. the "
        "binarized comparator's ceil(0.5 * max_possible_sum) rule) -- they are "
        "not fit to agree with each other, so the agreement number above is a "
        "genuine measurement, not a tautology.\n"
        "- This subgraph only models the GF/TTMn (jump) pathway; the DLMn "
        "flight-muscle pathway is excluded (see circuit/DERIVATION.md) because "
        "MaleCNS v1.0 has no direct DNp01->DLMn synapse in this data (it is "
        "known to be indirect, via the PSI interneuron, which is out of scope).\n"
        "- Only the chemical synapse count is modeled. The GF->TTMn synapse "
        "is well documented in the literature to have a strong electrical "
        "(gap-junction) component that synapse-count data cannot see, so the "
        "TTMn stage's real coupling strength is likely understated here.\n"
        "- Both models are toy-scale reductions (top-3-per-population visual "
        "input, 4-bit weight quantization); neither is a claim of accurately "
        "predicting a real fly's behavior, only of a documented, reproducible "
        "relationship between two models of the same wiring diagram.\n"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subgraph", default=str(DEFAULT_SUBGRAPH))
    parser.add_argument("--netlist", default=str(DEFAULT_NETLIST))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)

    with open(args.subgraph, encoding="utf-8") as f:
        subgraph = json.load(f)
    with open(args.netlist, encoding="utf-8") as f:
        netlist = json.load(f)

    summary = run_equivalence(subgraph, netlist)
    write_report(summary, Path(args.report))
    print(json.dumps({
        "n_patterns": summary["n_patterns"],
        "agreement_pct": round(summary["agreement_pct"], 2),
        "report": args.report,
    }, indent=2))


if __name__ == "__main__":
    main()
